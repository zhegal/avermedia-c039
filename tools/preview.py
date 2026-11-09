#!/usr/bin/env python3
"""Live firmware-free C039 Composite preview through ffplay; no raw recording."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bt656 import Decoder
from video_standards import NAMES, geometry


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--standard', choices=NAMES, default='pal')
    parser.add_argument('--seconds', type=int, default=600)
    parser.add_argument('--log', type=Path, default=ROOT / 'build' / 'preview.log')
    args = parser.parse_args()
    if not 0 <= args.seconds <= 3600:
        parser.error('seconds must be 0..3600')
    stopped = False
    capture = player = None

    def stop(signum, frame):
        nonlocal stopped
        stopped = True
        if capture is not None and capture.poll() is None:
            capture.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    height, rate = geometry(args.standard)
    with tempfile.TemporaryDirectory(prefix='c039-preview-') as temp, args.log.open('w') as log:
        fifo = Path(temp) / 'video.fifo'
        os.mkfifo(fifo)
        # Open reader non-blocking first, so startup failures cannot deadlock.
        fd = os.open(fifo, os.O_RDONLY | os.O_NONBLOCK)
        try:
            player = subprocess.Popen(['ffplay', '-hide_banner', '-loglevel', 'warning',
                '-window_title', 'AVerMedia C039 — Composite ' + args.standard.upper(),
                '-f', 'rawvideo', '-pixel_format', 'uyvy422', '-video_size', f'720x{height}',
                '-framerate', rate, '-probesize', '32', '-sync', 'ext', '-framedrop', '-i', '-'],
                stdin=subprocess.PIPE, stdout=log, stderr=log)
            capture = subprocess.Popen([str(ROOT / 'build' / 'c039-probe'), '--calibrate',
                '--seconds', str(args.seconds), '--video-probe', args.standard, str(fifo),
                str(Path(temp) / 'configuration.bin')], stdout=log, stderr=log)
            # Open the player even while the VCR is stopped or changing standard.
            player.stdin.write(bytes([128, 16, 128, 16]) * (720 * height // 2))
            player.stdin.flush()
            decoder = Decoder(720, height, player.stdin.write)
            import select
            while capture.poll() is None and player.poll() is None and not stopped:
                ready, _, _ = select.select([fd], [], [], 0.05)
                if ready:
                    chunk = os.read(fd, 65536)
                    if chunk:
                        decoder.feed(chunk)
                        player.stdin.flush()
            if capture.poll() is None and player.poll() in (0, 123, -signal.SIGTERM):
                stopped = True
            print(decoder.summary(), file=log, flush=True)
        except BrokenPipeError:
            pass
        finally:
            if capture is not None and capture.poll() is None:
                capture.terminate()
                # Keep draining the FIFO while USB cancellation and rollback run.
                # Closing the reader first could strand a blocking USB writer.
                until = time.monotonic() + 15
                while capture.poll() is None and time.monotonic() < until:
                    ready, _, _ = select.select([fd], [], [], 0.05)
                    if ready:
                        os.read(fd, 65536)
                capture.wait(timeout=15)
            os.close(fd)
            if player is not None:
                if player.poll() is None:
                    player.terminate()
                player.wait(timeout=5)
        return 0 if stopped or (capture is not None and capture.returncode == 0) else 1


if __name__ == '__main__':
    raise SystemExit(main())
