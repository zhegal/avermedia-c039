"""The native camera parser must match the established Python capture parser."""
import ctypes as C
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from bt656 import Decoder
from test_bt656 import fields, marker

LIB = C.CDLL(str(Path(__file__).resolve().parents[1] / 'build/libc039-frame.dylib'))
CALLBACK = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint)
LIB.c039_frame_decoder_create.argtypes = [C.c_uint, CALLBACK, C.c_void_p]
LIB.c039_frame_decoder_create.restype = C.c_void_p
LIB.c039_frame_decoder_feed.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
LIB.c039_frame_decoder_set_height.argtypes = [C.c_void_p, C.c_uint]
LIB.c039_frame_decoder_destroy.argtypes = [C.c_void_p]


class NativeFrames(unittest.TestCase):
    def native(self, data, height, chunk=2892):
        result = []
        callback = CALLBACK(lambda _, pointer, size, actual: result.append((C.string_at(pointer, size), actual)))
        decoder = LIB.c039_frame_decoder_create(height, callback, None)
        self.assertTrue(decoder)
        try:
            for start in range(0, len(data), chunk):
                part = data[start:start + chunk]
                LIB.c039_frame_decoder_feed(decoder, part, len(part))
        finally:
            LIB.c039_frame_decoder_destroy(decoder)
        return result

    def test_native_weaving_matches_python_at_packet_boundaries(self):
        for height in (480, 576):
            data = fields(720, height // 2)[0]
            expected = []; Decoder(720, height, expected.append).feed(data)
            for chunk in (1439, 1443, 2892, 65536):
                self.assertEqual(self.native(data, height, chunk), [(expected[0], height)])

    def test_native_rejects_damage_excess_lines_and_garbage_then_recovers(self):
        good = fields(720, 288)[0]
        data = b'x' * 200000 + fields(720, 288, short=True)[0] + fields(720, 288, extra=True)[0] + good
        expected = []; Decoder(720, 576, expected.append).feed(data)
        self.assertEqual([frame for frame, _ in self.native(data, 576)], expected)
        self.assertEqual(len(expected), 1)

    def test_native_height_switch_discards_partial_fields(self):
        result = []
        callback = CALLBACK(lambda _, pointer, size, height: result.append((size, height)))
        decoder = LIB.c039_frame_decoder_create(576, callback, None)
        try:
            partial = fields(720, 288)[0][:100000]
            LIB.c039_frame_decoder_feed(decoder, partial, len(partial))
            for height in (480, 576):
                LIB.c039_frame_decoder_set_height(decoder, height)
                data = fields(720, height // 2)[0]
                LIB.c039_frame_decoder_feed(decoder, data, len(data))
            self.assertEqual(result, [(720 * 480 * 2, 480), (720 * 576 * 2, 576)])
        finally:
            LIB.c039_frame_decoder_destroy(decoder)

    def test_sav_only_matches_python(self):
        data = b''.join(marker(0x80 | field * 0x40) + bytes([16 + row % 200]) * 1440
                        for field in (0, 1, 0) for row in range(288))
        expected = []; Decoder(720, 576, expected.append).feed(data)
        self.assertEqual([frame for frame, _ in self.native(data, 576)], expected)
