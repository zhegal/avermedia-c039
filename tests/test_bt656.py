"""Synthetic protocol tests; these do not establish capture hardware support."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bt656 import Decoder, PREFIX


def marker(value):
    return PREFIX + bytes([value])


def fields(width=4, count=2, short=False, extra=False):
    out = bytearray()
    expected = []
    for field in (0, 1):
        for line in range(count + (1 if extra and field == 1 else 0)):
            payload = bytes([16 + (field * 10 + line) % 200]) * width * 2
            expected.append(payload)
            if short and field == 0 and line == 0:
                payload = payload[:-1]
            out += marker(0x80 | field * 0x40) + payload
            out += marker(0x90 | field * 0x40)
        out += marker(0xa0 | field * 0x40) + b'blanking'
    out += marker(0xa0)  # next field boundary; no next active line required
    return bytes(out), expected


class Tests(unittest.TestCase):
    def test_every_byte_boundary_and_field_weaving(self):
        stream, lines = fields()
        for chunk_size in (1, 2, 3, 4, 7, 11, 4096):
            frames = []
            decoder = Decoder(4, 4, frames.append)
            for pos in range(0, len(stream), chunk_size):
                decoder.feed(stream[pos:pos + chunk_size])
            self.assertEqual(frames, [lines[0] + lines[2] + lines[1] + lines[3]])

    def test_damaged_pair_dropped_then_recovers(self):
        frames = []
        decoder = Decoder(4, 4, frames.append)
        decoder.feed(fields(short=True)[0] + fields()[0])
        self.assertEqual(len(frames), 1)
        self.assertEqual(decoder.short_lines, 1)

    def test_extra_lines_rejected(self):
        frames = []
        decoder = Decoder(4, 4, frames.append)
        decoder.feed(fields(extra=True)[0])
        self.assertEqual(frames, [])

    def test_unframed_and_truncated_never_emit(self):
        frames = []
        decoder = Decoder(4, 4, frames.append)
        decoder.feed(b'x' * 100000 + fields()[0][:20])
        self.assertEqual(frames, [])
        self.assertLess(len(decoder.buffer), 100)

    def test_full_pal_and_ntsc_sizes(self):
        for height in (576, 480):
            frames = []
            decoder = Decoder(720, height, frames.append)
            stream, _ = fields(720, height // 2)
            for start in range(0, len(stream), 2892):
                decoder.feed(stream[start:start + 2892])
            self.assertEqual(len(frames), 1)
            self.assertEqual(len(frames[0]), 720 * height * 2)

    def test_sav_only_wire_stream_and_byte_offsets(self):
        data = b'noise' + b''.join(marker(0x80 | (field << 6)) + bytes([line + 16]) * 8
            for field in (0, 1, 0, 1, 0) for line in range(2))
        for chunk in (1, 17, 1000):
            events, frames = [], []
            decoder = Decoder(4, 4, frames.append, lambda *event: events.append(event))
            for i in range(0, len(data), chunk):
                decoder.feed(data[i:i + chunk])
            self.assertEqual(len(frames), 2)
            self.assertEqual(events, [(0, 5, 29), (1, 53, 77)])


if __name__ == '__main__':
    unittest.main()
