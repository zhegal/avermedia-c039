# SPDX-License-Identifier: GPL-2.0-or-later
"""Private application diagnostics, never sidecars in the recording directory."""
import os
from pathlib import Path


def diagnostics_root():
    override = os.environ.get('C039_DIAGNOSTICS_DIR')
    if override:
        root = Path(override)
    elif os.name == 'nt':
        root = Path(os.environ['LOCALAPPDATA']) / 'C039Recorder' / 'Diagnostics'
    else:
        root = Path.home() / 'Library/Logs/C039Recorder'
    root.mkdir(parents=True, exist_ok=True)
    return root
