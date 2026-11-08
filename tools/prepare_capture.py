#!/usr/bin/env python3
"""Weave C039 fields and align PCM by USB packet timestamps, without resampling.

USB arrival alignment cannot establish analogue decoder latency or lip sync.
"""
import argparse
from array import array
from bisect import bisect_right
import csv
from contextlib import nullcontext
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from bt656 import Decoder


class PacketIndex:
    """Compact index: a multi-minute capture has millions of USB packets."""
    def __init__(self):
        self.offsets = array('Q')
        self.lengths = array('I')
        self.times = array('Q')
        self.span_start_us = None
        self.span_end_us = None

    def append(self, row):
        offset, length, time = row
        self.offsets.append(offset)
        self.lengths.append(length)
        self.times.append(time)

    def __len__(self):
        return len(self.offsets)

    def __getitem__(self, index):
        return self.offsets[index], self.lengths[index], self.times[index]


def packets(path):
    result = PacketIndex()
    with Path(path).open() as source:
        for row in csv.DictReader(source):
            if row['packet_status'] not in ('00000000', 'e00002e7'):
                raise ValueError('USB packet errors: raw stream is discontinuous')
            length = int(row['length'])
            timestamp = int(row['bus_frame']) * 1000 + int(row['microframe']) * 125
            if result.span_start_us is None:
                result.span_start_us = timestamp
            result.span_end_us = timestamp + 125
            if length:
                result.append((int(row['file_offset']), length,
                               timestamp))
    if not result:
        raise ValueError('no nonempty USB packets')
    return result


def time_for_byte(rows, offsets, offset):
    i = bisect_right(offsets, offset) - 1
    if i < 0:
        raise ValueError('byte precedes first packet')
    start, length, time = rows[i]
    if offset >= start + length:
        raise ValueError('byte falls outside packet')
    return time + (offset - start) * 125 / length


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('prefix', type=Path, help='prefix supplied to c039-probe --capture')
    p.add_argument('--standard', choices=['pal', 'secam', 'ntsc'], default='pal')
    p.add_argument('--audit-only', action='store_true', help='verify timing without writing duplicate raw media')
    args = p.parse_args()
    prefix = str(args.prefix)
    video_packets = packets(prefix + '.video.bin.packets.csv')
    video_offsets = video_packets.offsets
    audio_packets = packets(prefix + '.audio.s16le.packets.csv')
    frames = []

    def event(index, field1, field2):
        frames.append(dict(index=index, field1_offset=field1, field2_offset=field2,
            usb_time_us=time_for_byte(video_packets, video_offsets, field1)))

    height = 480 if args.standard == 'ntsc' else 576
    rate = 30000 / 1001 if args.standard == 'ntsc' else 25
    output_context = nullcontext(None) if args.audit_only else open(prefix + '.uyvy', 'xb')
    with output_context as output, open(prefix + '.video.bin', 'rb') as source:
        decoder = Decoder(720, height, output.write if output else lambda frame: None, event)
        while chunk := source.read(65536):
            decoder.feed(chunk)
    if not frames:
        raise ValueError('no complete frames')
    deltas = [b['usb_time_us'] - a['usb_time_us'] for a, b in zip(frames, frames[1:])]
    expected_us = 1000000 / rate
    # Packet transport quantization is 125us. A gap of a frame is material.
    gaps = [i for i, delta in enumerate(deltas, 1) if abs(delta - expected_us) > 1000]
    with open(prefix + ('.audit.frames.json' if args.audit_only else '.frames.json'), 'x') as out:
        json.dump(frames, out, indent=2)
    if gaps:
        raise ValueError(f'discontinuous video at frames {gaps[:10]}; timestamps saved, no CFR export')
    first_us = frames[0]['usb_time_us']
    audio_times = audio_packets.times
    i = bisect_right(audio_times, first_us) - 1
    if i < 0:
        raise ValueError('video begins before audio')
    offset, length, time = audio_packets[i]
    # Start at a complete stereo PCM frame; refine within its 125us packet.
    skip = offset + min(length, max(0, round((first_us - time) * 48000 / 1000000) * 4))
    count = round(len(frames) / rate * 48000) * 4
    if Path(prefix + '.audio.s16le').stat().st_size < skip + count:
        raise ValueError('audio ends before video')
    if not args.audit_only:
        with open(prefix + '.audio.s16le', 'rb') as source, open(prefix + '.aligned.s16le', 'xb') as output:
            source.seek(skip)
            left = count
            while left:
                chunk = source.read(min(left, 65536))
                if not chunk:
                    raise ValueError('audio ends before video')
                output.write(chunk)
                left -= len(chunk)
    summary = dict(decoder.summary(), first_video_usb_us=first_us,
        audio_skip_samples=skip // 4, aligned_audio_samples=count // 4,
        duration_seconds=len(frames) / rate,
        frame_delta_us_min=min(deltas) if deltas else None,
        frame_delta_us_max=max(deltas) if deltas else None,
        video_span_drift_us=frames[-1]['usb_time_us'] - frames[0]['usb_time_us'] - (len(frames) - 1) * expected_us,
        usb_span_seconds=(audio_packets.span_end_us - audio_packets.span_start_us) / 1000000,
        source_audio_samples=Path(prefix + '.audio.s16le').stat().st_size // 4,
        byte_order='UYVY, observed on physical PAL Composite capture',
        alignment='USB arrival timestamps; analog decoder latency uncalibrated')
    with open(prefix + ('.audit.json' if args.audit_only else '.summary.json'), 'x') as out:
        json.dump(summary, out, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
