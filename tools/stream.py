#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Stream synchronized C039 video/audio to stdout or a new NUT/MPEG-TS file."""
import argparse
from contextlib import nullcontext
from pathlib import Path
import signal
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from capture_stream import CaptureStream, StreamError


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--standard', choices=['pal', 'secam', 'ntsc'], default='pal')
    p.add_argument('--seconds', type=int, default=0, help='0: until interrupted')
    p.add_argument('--audio-attenuation-db', type=int, default=6)
    p.add_argument('--format', choices=['nut', 'mpegts'], default='nut')
    p.add_argument('--field-order', choices=['tff', 'bff'])
    p.add_argument('--output', default='-', help='-: binary stdout; otherwise a new file')
    p.add_argument('--log', type=Path, default=ROOT / 'build/stream.log')
    args = p.parse_args()
    try:
        engine = CaptureStream(standard=args.standard, seconds=args.seconds,
            attenuation=args.audio_attenuation_db, container=args.format, field_order=args.field_order)
    except ValueError as error:
        p.error(str(error))
    if args.output == '-' and sys.stdout.isatty():
        p.error('binary output requires a pipe, redirection or --output FILE')
    signal.signal(signal.SIGINT, lambda *_: engine.stop())
    signal.signal(signal.SIGTERM, lambda *_: engine.stop())
    try:
        target = nullcontext(sys.stdout.buffer) if args.output == '-' else open(args.output, 'xb')
        with target as output:
            return engine.run(output, args.log, allow_disconnect=args.output == '-')
    except (OSError, StreamError) as error:
        print(f'c039-stream: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
