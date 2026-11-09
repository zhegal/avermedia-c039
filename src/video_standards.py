# SPDX-License-Identifier: GPL-2.0-or-later
"""Use the driver's profile table for every CLI; listing never opens USB."""
import json
import os
from pathlib import Path
import subprocess
from runtime_paths import binary_path

_probe = binary_path('c039-probe.exe' if os.name == 'nt' else 'c039-probe')
if not _probe.is_file():
    raise RuntimeError('build/c039-probe is required; run make first')
STANDARDS = {row['name']: row for row in json.loads(subprocess.check_output([str(_probe), '--list-standards'],
    **({'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {})))}
NAMES = tuple(STANDARDS)
FIXED_NAMES = tuple(name for name in NAMES if name != 'auto')


def geometry(standard, auto_geometry='pal'):
    profile = STANDARDS[auto_geometry if standard == 'auto' else standard]
    return profile['height'], f"{profile['rate_num']}/{profile['rate_den']}"
