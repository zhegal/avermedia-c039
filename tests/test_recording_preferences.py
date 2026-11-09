"""Recording dialog persistence without opening Tk, USB or capture media."""
from datetime import datetime
import json
from pathlib import Path
import sys
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from recording_preferences import RecordingPreferences


class RecordingDialogPreferences(unittest.TestCase):
    def setUp(self):
        self.root = ROOT/'build/preferences-tests'/uuid.uuid4().hex
        self.media = self.root/'media'; self.media.mkdir(parents=True)
        self.settings = self.root/'private/preferences.json'

    def test_restart_restores_folder_and_format_with_fresh_timestamp(self):
        preferences = RecordingPreferences(self.settings)
        options = preferences.dialog_options(self.media, now=datetime(2026,11,9,23,59,30))
        self.assertEqual(options['initialfile'], '2026-11-09_23-59-30.ts')
        preferences.remember(self.media/'chosen.mpg')
        restored = RecordingPreferences(self.settings)
        options = restored.dialog_options(self.root, now=datetime(2026,11,10,0,0,5))
        self.assertEqual(Path(options['initialdir']), self.media.resolve())
        self.assertEqual(options['initialfile'], '2026-11-10_00-00-05.mpg')
        self.assertEqual(options['defaultextension'], '.mpg')
        self.assertEqual(options['filetypes'][0], ('MPEG-PS', '*.mpg'))
        self.assertEqual(list(self.media.iterdir()), [])
        restored.remember(self.media/'another.ts')
        self.assertEqual(RecordingPreferences(self.settings).extension, '.ts')

    def test_unavailable_folder_falls_back_without_creating_old_folder(self):
        self.settings.parent.mkdir()
        self.settings.write_text(json.dumps(dict(folder=str(self.root/'unavailable'),extension='.mpg')))
        preferences = RecordingPreferences(self.settings)
        self.assertEqual(Path(preferences.dialog_options(self.media)['initialdir']), self.media)
        self.assertFalse((self.root/'unavailable').exists())

    def test_invalid_preferences_do_not_block_dialog_or_create_files(self):
        self.settings.parent.mkdir()
        self.settings.write_text('invalid json')
        preferences = RecordingPreferences(self.settings)
        self.assertIsNotNone(preferences.load_error)
        options = preferences.dialog_options(self.media)
        self.assertEqual(options['defaultextension'], '.ts')
        self.assertEqual(list(self.media.iterdir()), [])
