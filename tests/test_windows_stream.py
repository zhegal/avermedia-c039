"""Windows FFmpeg integration with synthetic USB packets, never physical capture."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


class SyntheticSession:
    gap = False
    incompatible = False
    opened = 0

    def __init__(self, **options):
        self.packet = options['on_packet']; self.standard = options['on_standard']
        self.stopped = threading.Event(); self.last_result = None
        type(self).opened += 1

    def run(self):
        self.standard(3, 480, 30000, 1001) if self.incompatible else self.standard(1, 576, 25, 1)
        stamp = 1000000
        for frame in range(5):
            raw = b''.join(b'\xff\0\0' + bytes([0x80 | (field << 6)]) +
                           bytes([16 + frame * 8 + field]) * 1440
                           for field in (0, 1) for _ in range(288))
            for packet in range(320):
                if self.stopped.is_set():
                    self.last_result = 0; return 0
                begin, end = len(raw) * packet // 320, len(raw) * (packet + 1) // 320
                data = b'' if self.gap and frame == 2 else raw[begin:end]
                self.packet(4, data, stamp)
                self.packet(3, b'\x10\0\xf0\xff' * 6, stamp)
                stamp += 125
        self.packet(4, b'\xff\0\0\x80', stamp)
        self.packet(3, b'\0' * 24, stamp)
        self.last_result = 0; return 0

    def stop(self):
        self.stopped.set()

    def close(self):
        pass


@unittest.skipUnless(os.name == 'nt' and shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'Windows and FFmpeg/ffprobe required')
class WindowsStreamIntegration(unittest.TestCase):
    def execute(self, factory=SyntheticSession, conceal=False):
        from capture_stream import CaptureStream
        from windows_stream import run_windows
        # Retain generated media and diagnostics for review, outside Git.
        folder = ROOT / 'build/windows-stream-tests' / uuid.uuid4().hex
        folder.mkdir(parents=True)
        engine = CaptureStream(standard='auto', seconds=1, container='mpegts', field_order='tff',
                               conceal_gaps=conceal, video_bitrate=8)
        with (folder / 'synthetic.ts').open('xb') as output:
            code = run_windows(engine, output, folder / 'stream.log', native_factory=factory)
        return code, engine, folder

    def test_strict_mpeg2_mp2_preserves_frames_fields_audio_and_rate(self):
        SyntheticSession.opened = 0
        code, engine, folder = self.execute()
        self.assertEqual(code, 0, (engine.errors, (folder / 'stream.log').read_text()))
        self.assertEqual(SyntheticSession.opened, 1)
        self.assertEqual(engine.stats.video_frames, 5)
        self.assertEqual(engine.stats.audio_bytes, 9600 * 4)
        self.assertEqual(engine.stats.held_video_frames, 0)
        self.assertEqual(engine.stats.dropped_video_frames, 0)
        data = json.loads(subprocess.check_output(['ffprobe', '-v', 'error', '-count_frames',
            '-show_streams', '-of', 'json', str(folder / 'synthetic.ts')]))
        video, audio = data['streams']
        self.assertEqual((video['codec_name'], video['width'], video['height'], video['r_frame_rate']),
                         ('mpeg2video', 720, 576, '25/1'))
        self.assertEqual(video['field_order'], 'tt')
        self.assertEqual(int(video['nb_read_frames']), 5)
        self.assertEqual((audio['codec_name'], audio['sample_rate'], audio['channels'], audio['bit_rate']),
                         ('mp2', '48000', 2, '256000'))
        subprocess.run(['ffmpeg', '-v', 'error', '-i', str(folder / 'synthetic.ts'), '-f', 'null', '-'], check=True)

    def test_strict_gap_fails_and_viewing_gap_is_explicitly_counted(self):
        class Gap(SyntheticSession):
            gap = True
        code, strict, folder = self.execute(Gap)
        self.assertNotEqual(code, 0)
        self.assertTrue(any('timestamp gap' in error for error in strict.errors), strict.errors)
        self.assertEqual(strict.stats.held_video_frames, 0)
        code, viewing, folder = self.execute(Gap, conceal=True)
        self.assertEqual(code, 0, viewing.errors)
        self.assertEqual(viewing.stats.video_frames, 4)
        self.assertEqual(viewing.stats.held_video_frames, 1)
        self.assertEqual(viewing.windows_status['output_frames'], 5)

    def test_geometry_family_change_is_an_error_without_scaling(self):
        class Incompatible(SyntheticSession):
            incompatible = True
        code, engine, folder = self.execute(Incompatible)
        self.assertNotEqual(code, 0)
        self.assertTrue(any('geometry/rate family changed' in error for error in engine.errors), engine.errors)
        self.assertEqual(engine.stats.video_frames, 0)
