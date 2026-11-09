# SPDX-License-Identifier: GPL-2.0-or-later
"""Private application diagnostics, never sidecars in the recording directory."""
import os
import shutil
import sys
from pathlib import Path


def application_data_root():
    if os.name == 'nt':
        return Path(os.environ['LOCALAPPDATA']) / 'C039Recorder'
    return Path.home() / 'Library/Application Support/C039Recorder'


def binary_path(name):
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'bin' / name
    return Path(__file__).resolve().parents[1] / 'build' / name


def ffmpeg_path(name='ffmpeg'):
    filename = name + ('.exe' if os.name == 'nt' else '')
    if getattr(sys, 'frozen', False):
        bundled = binary_path(filename)
        if not bundled.is_file():
            raise FileNotFoundError('Missing bundled component: '+str(bundled))
        return str(bundled)
    local = binary_path('ffmpeg') / filename
    return str(local) if local.is_file() else shutil.which(name)


def default_recordings_folder():
    if getattr(sys, 'frozen', False):
        return Path.home() / 'Videos' / 'C039 Recordings'
    return Path(__file__).resolve().parents[1] / 'build/recordings'


def timestamp_ffmpeg_path():
    path = (binary_path('ffmpeg-timestamps.exe') if getattr(sys,'frozen',False) else
            Path(__file__).resolve().parents[1]/'build/timestamp-ffmpeg/bin/ffmpeg.exe')
    if not path.is_file():
        raise FileNotFoundError('Missing timestamp-aware encoder: '+str(path))
    return str(path)


def diagnostics_root():
    override = os.environ.get('C039_DIAGNOSTICS_DIR')
    if override:
        root = Path(override)
    elif os.name == 'nt':
        root = application_data_root() / 'Diagnostics'
    else:
        root = Path.home() / 'Library/Logs/C039Recorder'
    root.mkdir(parents=True, exist_ok=True)
    return root
