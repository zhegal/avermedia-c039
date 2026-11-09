#!/usr/bin/env python3
"""Reassemble cx231xx SAV/EAV payloads, preserving byte order and interlacing.

Protocol reference: Linux v6.12 cx231xx-video.c and cx231xx-reg.h.
Hardware PAL Composite/UYVY transport validated; signal timing remains external.
"""
import argparse
import json
import sys

PREFIX = b'\xff\x00\x00'


class Decoder:
    def __init__(self, width, height, emit, frame_event=None):
        if width <= 0 or width % 2 or height <= 0 or height % 2:
            raise ValueError('width and height must be positive even integers')
        self.width, self.height, self.emit = width, height, emit
        self.frame_event = frame_event
        self.offset = 0
        self.marker_offset = 0
        self.starts = [None, None]
        self.stride = width * 2
        self.buffer = bytearray()
        self.marker = None
        self.field = None
        self.lines = [[], []]
        self.bad = [False, False]
        self.first_complete = False
        self.frames = self.short_lines = self.dropped_pairs = self.markers = 0
        self.trailing_bytes = 0

    def _line(self, field, payload):
        if field != self.field:
            if field == 0:
                if self.lines[0] or self.lines[1]:
                    self.dropped_pairs += 1
                self.lines = [[], []]
                self.bad = [False, False]
                self.first_complete = False
                self.starts = [None, None]
            else:
                self.first_complete = (len(self.lines[0]) == self.height // 2
                                       and not self.bad[0])
            self.field = field
        if len(payload) < self.stride:
            self.short_lines += 1
            self.bad[field] = True
        else:
            self.trailing_bytes += len(payload) - self.stride
            if not self.lines[field]:
                self.starts[field] = self.marker_offset
            self.lines[field].append(bytes(payload[:self.stride]))
        if len(self.lines[field]) > self.height // 2:
            self.bad[field] = True

    def _boundary(self, next_marker):
        # Publish only on a field boundary: this detects excess/repeated lines
        # before committing a frame, instead of silently dropping the extra line.
        next_field = 1 if next_marker & 0x40 else 0
        if self.field == 1 and next_field == 0:
            if (self.first_complete and not any(self.bad)
                    and len(self.lines[1]) == self.height // 2):
                frame = bytearray(self.stride * self.height)
                for field in (0, 1):
                    for line, data in enumerate(self.lines[field]):
                        offset = (line * 2 + field) * self.stride
                        frame[offset:offset + self.stride] = data
                self.emit(bytes(frame))
                if self.frame_event:
                    self.frame_event(self.frames, *self.starts)
                self.frames += 1
                self.lines = [[], []]
                self.bad = [False, False]
                self.first_complete = False
                self.field = None

    def _consume(self, count):
        del self.buffer[:count]
        self.offset += count

    def feed(self, data):
        self.buffer.extend(data)
        while True:
            pos = self.buffer.find(PREFIX)
            if pos < 0:
                # Keep a full active line until its EAV; discard unframed garbage.
                if self.marker is None and len(self.buffer) > 3:
                    self._consume(len(self.buffer) - 3)
                elif len(self.buffer) > self.stride + 65536:
                    self.bad = [True, True]
                    self.marker = None
                    self._consume(len(self.buffer) - 3)
                return
            if len(self.buffer) < pos + 4:
                return
            marker = self.buffer[pos + 3]
            if marker & 0xf0 not in (0x80, 0x90, 0xa0, 0xb0, 0xc0, 0xd0, 0xe0, 0xf0):
                # Invalid marker cannot terminate a valid line.
                if self.marker is not None:
                    self.bad = [True, True]
                self._consume(pos + 1)
                continue
            if self.marker is not None and self.marker & 0xf0 in (0x80, 0xc0):
                self._line(1 if self.marker & 0x40 else 0, self.buffer[:pos])
            self._boundary(marker)
            self.marker = marker
            self.marker_offset = self.offset + pos
            self.markers += 1
            self._consume(pos + 4)

    def summary(self):
        return dict(frames=self.frames, markers=self.markers,
                    short_lines=self.short_lines, dropped_pairs=self.dropped_pairs,
                    trailing_bytes=self.trailing_bytes,
                    partial_field_lines=list(map(len, self.lines)),
                    width=self.width, height=self.height,
                    byte_order='unchanged; verify UYVY on real signal',
                    field_mapping='field1 -> even raster rows; temporal dominance unverified')


def main():
    from video_standards import FIXED_NAMES, geometry
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input', help='raw endpoint 0x84 payload file, or - for stdin')
    p.add_argument('output', help='woven raw frames, or - for stdout')
    p.add_argument('--standard', choices=FIXED_NAMES, default='pal')
    args = p.parse_args()
    source = sys.stdin.buffer if args.input == '-' else open(args.input, 'rb')
    target = sys.stdout.buffer if args.output == '-' else open(args.output, 'xb')
    decoder = Decoder(720, geometry(args.standard)[0], target.write)
    try:
        while chunk := source.read(65536):
            decoder.feed(chunk)
        target.flush()
    finally:
        if source is not sys.stdin.buffer:
            source.close()
        if target is not sys.stdout.buffer:
            target.close()
    print(json.dumps(decoder.summary()), file=sys.stderr)
    return 0 if decoder.frames else 2


if __name__ == '__main__':
    raise SystemExit(main())
