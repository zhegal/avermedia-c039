# SPDX-License-Identifier: GPL-2.0-or-later
"""Private recording-dialog preferences, independent of capture ownership."""
from datetime import datetime
import json
import os
from pathlib import Path
import uuid

from runtime_paths import application_data_root


class RecordingPreferences:
    def __init__(self, path=None):
        self.path = Path(path) if path is not None else application_data_root()/'recording-preferences.json'
        self.folder = None
        self.extension = '.ts'
        self.load_error = None
        try:
            state = json.loads(self.path.read_text(encoding='utf-8'))
            if isinstance(state, dict):
                if isinstance(state.get('folder'), str) and state['folder']:
                    self.folder = Path(state['folder'])
                if state.get('extension') in ('.ts', '.mpg'):
                    self.extension = state['extension']
        except FileNotFoundError:
            pass
        except (OSError, ValueError) as error:
            self.load_error = str(error)

    def dialog_options(self, fallback, *, now=None):
        folder = self.folder if self.folder and self.folder.is_dir() else Path(fallback)
        if self.extension == '.mpg':
            types = [('MPEG-PS', '*.mpg'), ('MPEG-TS', '*.ts')]
        else:
            types = [('MPEG-TS', '*.ts'), ('MPEG-PS', '*.mpg')]
        return dict(initialdir=str(folder),
                    initialfile=(now or datetime.now()).strftime('%Y-%m-%d_%H-%M-%S')+self.extension,
                    defaultextension=self.extension, filetypes=types)

    def remember(self, recording_path):
        recording_path = Path(recording_path).resolve()
        self.folder = recording_path.parent
        suffix = recording_path.suffix.lower()
        self.extension = '.mpg' if suffix in ('.mpg', '.mpeg') else '.ts'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name+'.'+uuid.uuid4().hex+'.tmp')
        try:
            with temporary.open('x', encoding='utf-8') as target:
                json.dump(dict(folder=str(self.folder), extension=self.extension), target, indent=2)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.path)
        finally:
            # Only this operation's private temporary file, never user media.
            temporary.unlink(missing_ok=True)
