#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Share one C039 capture with local VLC/OBS/FFmpeg clients over HTTP MPEG-TS."""
import argparse
from dataclasses import asdict
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from capture_stream import CaptureStream
from http_stream import TransportBroker, make_server
from video_standards import NAMES


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--standard', choices=NAMES, default='pal')
    p.add_argument('--auto-geometry', choices=['pal', 'ntsc'], default='pal')
    p.add_argument('--field-order', choices=['tff', 'bff'])
    p.add_argument('--video-bitrate', type=int, choices=range(8, 13), default=12, help='MPEG-2 target Mbit/s')
    p.add_argument('--preview', action='store_true', help='open local A/V viewer using this shared HTTP source')
    p.add_argument('--seconds', type=int, default=0)
    p.add_argument('--audio-attenuation-db', type=int, default=6)
    p.add_argument('--port', type=int, default=8079)
    p.add_argument('--strict', action='store_true', help='stop at video gaps instead of holding the last frame')
    p.add_argument('--replay', type=Path, help='loop a recorded TS to test clients without accessing USB')
    p.add_argument('--log', type=Path, default=ROOT / 'build/serve.log')
    args = p.parse_args()
    if not 1024 <= args.port <= 65535:
        p.error('port must be 1024..65535')
    if args.replay and not args.replay.is_file():
        p.error('replay file does not exist')
    try:
        engine = None if args.replay else CaptureStream(standard=args.standard, seconds=args.seconds,
            attenuation=args.audio_attenuation_db, container='mpegts', field_order=args.field_order,
            conceal_gaps=not args.strict, auto_geometry=args.auto_geometry, video_bitrate=args.video_bitrate)
    except ValueError as error:
        p.error(str(error))
    broker = TransportBroker()
    stopped = threading.Event()
    errors, result = [], []
    producer = None

    def stop(*_):
        stopped.set()
        if engine:
            engine.stop()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    server = make_server(args.port, broker, lambda: dict(source='replay' if args.replay else args.standard,
        capture=asdict(engine.stats) if engine else None,
        signal=getattr(engine, 'latest_signal', None), windows=getattr(engine, 'windows_status', None),
        loss_policy='strict' if args.strict else 'viewing-concealment',
        errors=errors + (engine.errors if engine else [])))
    args.log.parent.mkdir(parents=True, exist_ok=True)
    reader, writer_fd = os.pipe()

    def capture():
        nonlocal producer
        with os.fdopen(writer_fd, 'wb') as output:
            try:
                if engine:
                    result.append(engine.run(output, args.log))
                else:
                    with args.log.open('w') as log:
                        producer = subprocess.Popen(['ffmpeg', '-nostdin', '-hide_banner', '-v', 'warning',
                            '-re', '-stream_loop', '-1', '-i', str(args.replay), '-map', '0:v:0', '-map', '0:a:0',
                            '-c', 'copy', '-mpegts_flags', '+pat_pmt_at_frames', '-f', 'mpegts', 'pipe:1'],
                            stdout=output, stderr=log)
                        while producer.poll() is None and not stopped.wait(.05):
                            pass
                        if producer.poll() is None:
                            producer.terminate()
                        try:
                            producer.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            producer.kill(); producer.wait(timeout=3)
                        result.append(0 if stopped.is_set() else producer.returncode)
            except Exception as error:
                errors.append(str(error)); stop()

    def relay():
        try:
            while data := os.read(reader, 188 * 64):
                broker.publish(data)
        except Exception as error:
            errors.append(str(error)); stop()
        finally:
            os.close(reader); broker.close()

    workers = [threading.Thread(target=capture, daemon=True), threading.Thread(target=relay, daemon=True),
               threading.Thread(target=server.serve_forever, daemon=True)]
    for worker in workers:
        worker.start()
    print(f'http://127.0.0.1:{args.port}/live.ts', flush=True)
    print(f'Status: http://127.0.0.1:{args.port}/status', file=sys.stderr, flush=True)
    try:
        if args.preview:
            from preview_http import show_preview
            show_preview(args.port, engine, stop, workers[0])
        else:
            while workers[0].is_alive() and not stopped.wait(.1):
                pass
    finally:
        stop()
        workers[0].join(timeout=30)
        workers[1].join(timeout=3)
        broker.close(); server.shutdown(); server.server_close()
        workers[2].join(timeout=2)
    if workers[0].is_alive() or workers[1].is_alive():
        errors.append('capture or relay worker did not stop')
    print(f'HTTP stream stopped: {broker.status()}, errors={errors}', file=sys.stderr)
    return 1 if errors or not result or result[0] else 0


if __name__ == '__main__':
    raise SystemExit(main())
