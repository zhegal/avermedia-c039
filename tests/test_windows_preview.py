"""Persistent-viewer processing checks; no USB handle or audio device is opened."""
import os
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


class AudioSink:
    block_bytes = 3840
    def __init__(self):
        self.bytes = 0
    def reset(self):
        self.bytes = 0
    def write(self, data, stopped):
        self.bytes += len(data)


@unittest.skipUnless(os.name == 'nt', 'Windows preview binding')
class NativePreviewProcessing(unittest.TestCase):
    def test_all_profile_families_keep_logical_session_open(self):
        from windows_preview import PreviewCapture
        source = PreviewCapture(AudioSink())
        source._reset_epoch(1)
        for ident, height, num, den in ((1,576,25,1),(2,576,25,1),(3,480,30000,1001),
                                      (5,480,30000,1001),(6,480,30000,1001),(7,480,30000,1001),
                                      (8,576,25,1),(9,576,25,1),(10,480,30000,1001),(2,576,25,1)):
            source._profile(ident, height, num, den)
            self.assertEqual(source.state['height'], height)
            self.assertFalse(source.closing.is_set()); self.assertFalse(source.done.is_set())
        self.assertEqual(source.state['geometry_changes'], 4)
        self.assertEqual(source.generation, 1)

    def test_pcm_runs_without_any_complete_video_and_silence_is_counted(self):
        from windows_preview import PreviewCapture
        audio = AudioSink(); source = PreviewCapture(audio); source._reset_epoch(1)
        for batch in range(5):
            payload = b''.join(b'\0' * 24 for _ in range(64))
            descriptors = tuple((n*24, 24 if n else 0, 0) for n in range(64))
            source._batch(3, payload, descriptors, 1000000 + batch * 8000)
        self.assertEqual(source.state['frames'], 0)
        self.assertEqual(audio.bytes, 7680)
        self.assertEqual(source.state['silence_samples'], 30)
        self.assertFalse(source.closing.is_set())
