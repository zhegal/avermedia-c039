# SPDX-License-Identifier: GPL-2.0-or-later
"""Private application diagnostics, never sidecars in the recording directory."""
import os
from pathlib import Path


def application_data_root():
    if os.name == 'nt':
        return Path(os.environ['LOCALAPPDATA']) / 'C039Recorder'
    return Path.home() / 'Library/Application Support/C039Recorder'


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
