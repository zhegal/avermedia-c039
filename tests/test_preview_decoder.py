"""Preview damage tolerance is explicit and never changes archival decoding."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bt656 import Decoder
from preview_decoder import PreviewDecoder
from test_bt656 import fields, marker


class PreviewFields(unittest.TestCase):
    def test_good_fields_match_archival_bytes_and_damage_is_display_only(self):
        strict, viewing = [], []
        a = Decoder(4, 4, strict.append); p = PreviewDecoder(4, 4, viewing.append)
        good = fields()[0]
        a.feed(good); p.feed(good)
        self.assertEqual(strict, viewing); self.assertEqual(p.partial_frames, 0)
        a.feed(fields(short=True)[0]); p.feed(fields(short=True)[0])
        self.assertEqual(len(strict), 1); self.assertEqual(len(viewing), 2)
        self.assertEqual(p.partial_frames, 1); self.assertTrue(p.last_partial)
        a.feed(good); p.feed(good)
        self.assertEqual(strict[-1], viewing[-1]); self.assertFalse(p.last_partial)

    def test_native_480_and_576_frames_preserve_both_fields(self):
        for height in (480, 576):
            strict, viewing = [], []
            stream = fields(720, height // 2)[0]
            Decoder(720, height, strict.append).feed(stream)
            PreviewDecoder(720, height, viewing.append).feed(stream)
            self.assertEqual(strict, viewing)
            self.assertEqual(len(viewing[0]), 720 * height * 2)

    def test_repeated_damaged_field_uses_bounded_memory(self):
        frames = []
        p = PreviewDecoder(720, 576, frames.append)
        p.feed((marker(0x80) + bytes([16]) * 1440) * 2000)
        self.assertLessEqual(len(p.lines[0]), 289)
        self.assertLess(len(p.buffer), 70000); self.assertFalse(frames)
