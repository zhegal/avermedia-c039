"""Every public standard name selects the driver's native geometry and cadence."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from video_standards import STANDARDS, geometry
from capture_stream import CaptureStream


class VideoStandards(unittest.TestCase):
    def test_regional_composite_aliases_share_profiles(self):
        for base, suffixes in [('pal', ['b', 'd', 'g', 'h', 'i']),
                               ('secam', ['b', 'd', 'g', 'h', 'k', 'k1', 'l', 'l1'])]:
            for suffix in suffixes:
                self.assertEqual(STANDARDS[f'{base}-{suffix}']['id'], STANDARDS[base]['id'])

    def test_525_profiles_use_native_480_lines_and_fractional_frame_rate(self):
        for name in ['ntsc', 'ntsc-m', 'ntsc-j', 'ntsc-443', 'ntsc-433', 'pal-m', 'pal-60']:
            self.assertEqual(geometry(name), (480, '30000/1001'))
            stream = CaptureStream(standard=name)
            self.assertEqual(stream.height, 480)
            self.assertIn('30000/1001', stream.mux_command(3, 4))
        for name in ['pal', 'secam', 'pal-n', 'pal-nc']:
            self.assertEqual(geometry(name), (576, '25/1'))

    def test_fixed_pipe_geometry_can_be_selected_for_auto_ntsc_preview(self):
        stream = CaptureStream(standard='auto', auto_geometry='ntsc')
        self.assertEqual((stream.height, stream.rate), (480, '30000/1001'))
