"""Strict file lifecycle/full-decode checks over synthetic data, no USB access."""
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src')); sys.path.insert(0,str(ROOT/'tools'))
from test_windows_stream import SyntheticSession


class SyntheticSource:
    current_profile = (1,576,25,1)
    standard = 'auto'
    session_factory = SyntheticSession


@unittest.skipUnless(os.name=='nt' and shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'Windows and FFmpeg required')
class RecordingLifecycle(unittest.TestCase):
    def folder(self):
        folder=ROOT/'build/recording-tests'/uuid.uuid4().hex; folder.mkdir(parents=True)
        return folder

    def test_success_is_unverified_until_full_offline_decode_and_no_overwrite(self):
        from windows_recording import StrictRecording
        from verify_windows_recording import verify
        target=self.folder()/'recording.ts'
        source=SyntheticSource()
        recording=StrictRecording(source,target,field_order='tff',seconds=1)
        recording.start(); self.assertTrue(recording.done.wait(10))
        self.assertEqual(recording.state['state'],'captured-unverified',recording.state)
        self.assertEqual(list(target.parent.iterdir()), [target])
        self.assertNotEqual(recording.manifest.parent, target.parent)
        self.assertTrue(recording.log_path.exists())
        result=verify(recording.manifest)
        self.assertTrue(result['verified']); self.assertEqual(result['video_frames'],5)
        self.assertEqual(result['source_pcm_samples'],9600)
        self.assertLess(result['mp2_padding_samples'],1152)
        self.assertTrue(result['audio_pts_checked'])
        # Corrupt one decoded audio timestamp while retaining all media counts.
        # Qualification must detect timing damage even when lengths still match.
        import verify_windows_recording as checker
        actual_run = checker.subprocess.run
        def corrupt_audio_timestamp(*args, **kwargs):
            response = actual_run(*args, **kwargs)
            decoded = json.loads(response.stdout)
            audio = [f for f in decoded['frames'] if f['media_type']=='audio']
            audio[2]['best_effort_timestamp_time'] = str(float(audio[2]['best_effort_timestamp_time'])+.05)
            response.stdout = json.dumps(decoded)
            return response
        with patch.object(checker.subprocess, 'run', side_effect=corrupt_audio_timestamp):
            with self.assertRaisesRegex(ValueError, 'audio timestamps'):
                checker.verify(recording.manifest)
        with self.assertRaises(FileExistsError):
            StrictRecording(source,target,field_order='tff',seconds=1)

    def test_failed_gap_retains_media_and_cannot_be_qualified(self):
        from windows_recording import StrictRecording
        from verify_windows_recording import verify
        class Gap(SyntheticSession):
            gap=True
        class Source(SyntheticSource):
            session_factory=Gap
        recording=StrictRecording(Source(),self.folder()/'failed.ts',field_order='tff',seconds=1)
        recording.start(); self.assertTrue(recording.done.wait(10))
        self.assertEqual(recording.state['state'],'failed',recording.state)
        self.assertTrue(recording.path.exists()); self.assertTrue(recording.manifest.exists())
        self.assertEqual(list(recording.path.parent.iterdir()), [recording.path])
        with self.assertRaisesRegex(ValueError,'incomplete/failed'):
            verify(recording.manifest)
