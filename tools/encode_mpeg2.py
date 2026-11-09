#!/usr/bin/env python3
"""Encode already captured raw A/V. Does not acquire USB or synchronize clocks."""
import argparse
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_standards import FIXED_NAMES, geometry


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--standard', choices=FIXED_NAMES, required=True)
    p.add_argument('--field-order', choices=['tff', 'bff'], required=True,
                   help='must be measured from the real input; no assumed default')
    p.add_argument('--pixel-format', choices=['uyvy422', 'yuyv422'], required=True)
    p.add_argument('video', help='raw woven frames')
    p.add_argument('audio', help='stereo s16le 48000 Hz')
    p.add_argument('output', help='MPEG transport stream (.ts)')
    p.add_argument('--print-command', action='store_true')
    a = p.parse_args()
    height, rate = geometry(a.standard)
    cmd = ['ffmpeg', '-hide_banner', '-n', '-f', 'rawvideo', '-pixel_format',
           a.pixel_format, '-video_size', f'720x{height}', '-framerate', rate,
           '-i', a.video, '-f', 's16le', '-ar', '48000', '-ac', '2', '-i', a.audio,
           '-map', '0:v:0', '-map', '1:a:0', '-vf', f'setfield={a.field_order}',
           '-c:v', 'mpeg2video', '-pix_fmt', 'yuv422p', '-b:v', '12M',
           '-flags', '+ilme+ildct', '-alternate_scan', '1', '-g', '15',
           '-c:a', 'mp2', '-b:a', '256k', '-ar', '48000', '-ac', '2',
           '-f', 'mpegts', a.output]
    if a.print_command:
        import shlex
        print(shlex.join(cmd))
        return 0
    return subprocess.run(cmd).returncode


if __name__ == '__main__':
    raise SystemExit(main())
