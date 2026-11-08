#!/usr/bin/env python3
"""Live Composite + RCA preview, aligned by USB arrival timestamps.

Raw frames and PCM travel through FIFOs/pipes, not video files. Packet CSVs
live in the temporary directory and are removed after a clean shutdown.
"""
import argparse
import csv
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bt656 import Decoder


def read_packets(path):
    try:
        with Path(path).open() as stream:
            for row in csv.DictReader(stream):
                if not row.get('file_offset') or not row.get('length'):
                    continue
                length = int(row['length'])
                if length:
                    yield (int(row['file_offset']), length,
                           int(row['bus_frame']) * 1000 + int(row['microframe']) * 125)
    except FileNotFoundError:
        return


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--standard', choices=['pal', 'secam', 'ntsc'], default='pal')
    p.add_argument('--seconds', type=int, default=600)
    p.add_argument('--audio-attenuation-db', type=int, default=6)
    p.add_argument('--log', type=Path, default=ROOT / 'build' / 'preview-av.log')
    args = p.parse_args()
    if not 1 <= args.seconds <= 3600 or not 0 <= args.audio_attenuation_db <= 48:
        p.error('seconds must be 1..3600; attenuation 0..48')
    height, rate = (480, '30000/1001') if args.standard == 'ntsc' else (576, '25')
    capture = merger = player = None
    stopped = threading.Event()
    aligned = threading.Event()
    errors = []
    first_video_us = []
    reader_fds = []
    writers = []
    threads = []

    def stop(signum, frame):
        stopped.set()
        if capture is not None and capture.poll() is None:
            capture.terminate()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    with tempfile.TemporaryDirectory(prefix='c039-av-preview-') as temp, args.log.open('w') as log:
        prefix = Path(temp) / 'capture'
        fifo_paths = [str(prefix) + '.video.bin', str(prefix) + '.audio.s16le']
        for path in fifo_paths:
            os.mkfifo(path)
            reader_fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))
        vr, vw = os.pipe()
        ar, aw = os.pipe()
        writers = [os.fdopen(vw, 'wb'), os.fdopen(aw, 'wb')]
        try:
            merger = subprocess.Popen(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'warning',
                '-thread_queue_size', '32', '-f', 'rawvideo', '-pixel_format', 'uyvy422',
                '-video_size', f'720x{height}', '-framerate', rate, '-probesize', '32', '-analyzeduration', '0', '-i', f'pipe:{vr}',
                '-thread_queue_size', '128', '-f', 's16le', '-ar', '48000', '-ac', '2',
                '-probesize', '32', '-analyzeduration', '0', '-i', f'pipe:{ar}',
                '-map', '0:v:0', '-map', '1:a:0', '-c:v', 'rawvideo', '-threads:v', '1',
                '-c:a', 'pcm_s16le', '-flush_packets', '1', '-f', 'nut', 'pipe:1'],
                pass_fds=(vr, ar), stdout=subprocess.PIPE, stderr=log)
            os.close(vr)
            os.close(ar)
            player = subprocess.Popen(['ffplay', '-hide_banner', '-loglevel', 'warning', '-autoexit',
                '-window_title', 'AVerMedia C039 — Composite + RCA ' + args.standard.upper(),
                '-probesize', '32', '-analyzeduration', '0', '-sync', 'audio', '-i', '-'],
                stdin=merger.stdout, stdout=log, stderr=log)
            merger.stdout.close()
            capture = subprocess.Popen([str(ROOT / 'build' / 'c039-probe'),
                '--seconds', str(args.seconds), '--audio-attenuation-db', str(args.audio_attenuation_db),
                '--log-fifo-packets', '--capture', args.standard, str(prefix),
                str(prefix) + '.configuration.bin'], stdout=log, stderr=log)

            def chunks(fd):
                while True:
                    ready, _, _ = select.select([fd], [], [], 0.05)
                    if not ready:
                        if capture.poll() is not None:
                            # macOS FIFO EOF is not always returned by select
                            # after the writer disappears; drain nonblocking.
                            try:
                                remaining = os.read(fd, 65536)
                            except BlockingIOError:
                                break
                            if remaining:
                                yield remaining
                                continue
                            break
                        continue
                    data = os.read(fd, 65536)
                    if data:
                        yield data
                    elif capture.poll() is not None:
                        break
                    else:
                        time.sleep(0.005)

            def send(stream, data):
                try:
                    stream.write(data)
                    stream.flush()
                    return True
                except (BrokenPipeError, OSError):
                    return False

            def first_frame(index, field1, field2):
                if first_video_us:
                    return
                for start, length, stamp in read_packets(fifo_paths[0] + '.packets.csv'):
                    if start <= field1 < start + length:
                        first_video_us.append(stamp + (field1 - start) * 125 / length)
                        aligned.set()
                        return
                raise RuntimeError('first frame timestamp not present in flushed packet telemetry')

            def video_worker():
                alive = True

                def emit(frame):
                    nonlocal alive
                    if alive:
                        alive = send(writers[0], frame)

                decoder = Decoder(720, height, emit, first_frame)
                try:
                    for data in chunks(reader_fds[0]):
                        decoder.feed(data)
                    print('preview_video', decoder.summary(), file=log, flush=True)
                except Exception as error:
                    errors.append(str(error)); stop(None, None)
                finally:
                    try:
                        writers[0].close()
                    except OSError:
                        pass

            def audio_worker():
                pending = bytearray()
                skip = None
                alive = True
                output_bytes = 0
                try:
                    for data in chunks(reader_fds[1]):
                        pending.extend(data)
                        if skip is None and aligned.is_set():
                            candidate = None
                            for offset, length, stamp in read_packets(fifo_paths[1] + '.packets.csv'):
                                if stamp <= first_video_us[0]:
                                    candidate = (offset, length, stamp)
                                else:
                                    break
                            if candidate:
                                offset, length, stamp = candidate
                                skip = offset + min(length, max(0, round((first_video_us[0] - stamp) * .048) * 4))
                                print('preview_audio_skip_samples=', skip // 4, file=log, flush=True)
                        if skip is None:
                            if len(pending) > 768000:
                                raise RuntimeError('no synchronized video after four seconds of audio')
                            continue
                        drop = min(skip, len(pending))
                        del pending[:drop]
                        skip -= drop
                        if skip == 0 and pending:
                            if alive:
                                alive = send(writers[1], pending)
                            output_bytes += len(pending)
                            pending.clear()
                    print('preview_audio_bytes=', output_bytes, file=log, flush=True)
                except Exception as error:
                    errors.append(str(error)); stop(None, None)
                finally:
                    try:
                        writers[1].close()
                    except OSError:
                        pass

            threads = [threading.Thread(target=video_worker, daemon=True),
                       threading.Thread(target=audio_worker, daemon=True)]
            for thread in threads:
                thread.start()
            while capture.poll() is None and player.poll() is None and merger.poll() is None and not stopped.wait(.05):
                pass
            # FFplay handles SIGTERM itself and exits 123 on this build.
            if capture.poll() is None and player.poll() in (0, 123, -signal.SIGTERM):
                stopped.set()
        finally:
            if capture is not None and capture.poll() is None:
                capture.terminate()
            if capture is not None:
                capture.wait(timeout=15)
            for thread in threads:
                thread.join(timeout=15)
            for stream in writers:
                try:
                    stream.close()
                except OSError:
                    pass
            for proc in (merger, player):
                if proc is not None:
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.terminate(); proc.wait(timeout=5)
            for fd in reader_fds:
                os.close(fd)
        for error in errors:
            print('preview_error:', error, file=log)
        print('preview_process_codes', {name: proc.returncode if proc is not None else None
            for name, proc in [('capture', capture), ('ffmpeg', merger), ('ffplay', player)]}, file=log)
        return 1 if errors else 0 if stopped.is_set() or capture.returncode == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
