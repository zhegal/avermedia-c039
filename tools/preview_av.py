#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Live C039 preview using the shared streaming engine and ffplay."""
import argparse
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from capture_stream import CaptureStream


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--standard', choices=['pal', 'secam', 'ntsc', 'auto'], default='pal')
    p.add_argument('--seconds', type=int, default=600, help='0: until interrupted')
    p.add_argument('--audio-attenuation-db', type=int, default=6)
    p.add_argument('--strict', action='store_true', help='stop at video gaps instead of correcting viewing cadence')
    p.add_argument('--log', type=Path, default=ROOT / 'build/preview-av.log')
    args = p.parse_args()
    try:
        engine = CaptureStream(standard=args.standard, seconds=args.seconds,
                               attenuation=args.audio_attenuation_db, conceal_gaps=not args.strict)
    except ValueError as error:
        p.error(str(error))
    if not shutil.which('ffplay'):
        p.error('ffplay is required')
    args.log.parent.mkdir(parents=True, exist_ok=True)
    signal.signal(signal.SIGINT, lambda *_: engine.stop())
    signal.signal(signal.SIGTERM, lambda *_: engine.stop())
    result = []
    with args.log.with_suffix('.player.log').open('w') as player_log:
        player = subprocess.Popen(['ffplay', '-hide_banner', '-loglevel', 'warning', '-autoexit',
            '-window_title', 'AVerMedia C039 — Composite + RCA ' + args.standard.upper(),
            '-probesize', '32', '-analyzeduration', '0', '-sync', 'audio', '-i', '-'],
            stdin=subprocess.PIPE, stdout=player_log, stderr=player_log)

        def capture():
            try:
                result.append(engine.run(player.stdin, args.log, allow_disconnect=True))
            except Exception as error:
                print(f'c039-preview: {error}', file=sys.stderr)
                result.append(1)

        worker = threading.Thread(target=capture, daemon=True)
        worker.start()
        try:
            while worker.is_alive() and player.poll() is None:
                time.sleep(.05)
            if player.poll() is not None and worker.is_alive():
                engine.stop()
            worker.join(timeout=30)
            if worker.is_alive():
                print('c039-preview: capture worker did not stop', file=sys.stderr)
                return 1
        finally:
            engine.stop()
            if worker.is_alive():
                worker.join(timeout=15)
            player.stdin.close()
            try:
                player.wait(timeout=5)
            except subprocess.TimeoutExpired:
                player.terminate(); player.wait(timeout=5)
        return result[0] if result and player.returncode in (0, 123, -signal.SIGTERM) else 1


if __name__ == '__main__':
    raise SystemExit(main())
