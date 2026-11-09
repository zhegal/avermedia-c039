"""Frozen bundles use private components and writable per-user destinations."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import runtime_paths


class BundlePaths(unittest.TestCase):
    def test_frozen_missing_encoder_never_uses_system_path(self):
        with patch.object(sys,'frozen',True,create=True), patch.object(sys,'_MEIPASS',str(ROOT/'build/missing-bundle'),create=True):
            with patch.object(runtime_paths.shutil,'which',side_effect=AssertionError('system lookup forbidden')):
                with self.assertRaisesRegex(FileNotFoundError,'bundled component'):
                    runtime_paths.ffmpeg_path()
            self.assertEqual(runtime_paths.binary_path('c039-capture.dll'),ROOT/'build/missing-bundle/bin/c039-capture.dll')

    def test_frozen_default_recordings_are_outside_install_directory(self):
        with patch.object(sys,'frozen',True,create=True):
            self.assertEqual(runtime_paths.default_recordings_folder(),Path.home()/'Videos/C039 Recordings')
