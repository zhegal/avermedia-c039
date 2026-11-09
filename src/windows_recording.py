# SPDX-License-Identifier: GPL-2.0-or-later
"""Strict recording subscription. A failure never stops the persistent source."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import threading
import time
import uuid

from capture_stream import CaptureStream
from windows_stream import run_windows
from runtime_paths import diagnostics_root


class StrictRecording:
    def __init__(self, source, path, *, field_order, video_bitrate=12, seconds=0, diagnostics_dir=None):
        self.source = source; self.path = Path(path).resolve()
        if self.path.exists():
            raise FileExistsError('Recording already exists; choose a new filename')
        self.diagnostics = Path(diagnostics_dir or diagnostics_root()/'Recordings') / uuid.uuid4().hex
        self.diagnostics.mkdir(parents=True)
        self.manifest = self.diagnostics/'manifest.json'
        self.log_path = self.diagnostics/'capture.log'
        profile = source.current_profile
        if not profile:
            raise RuntimeError('source has not selected a native profile yet')
        _, height, numerator, denominator = profile
        needed = int((video_bitrate * 1000000 + 256000) / 8 * seconds * 1.15) + 67108864
        free = shutil.disk_usage(self.path.parent).free
        if free < needed:
            raise OSError(f'Insufficient recording disk budget: need {needed}, free {free}')
        container = 'mpeg' if self.path.suffix.lower() in ('.mpg','.mpeg') else 'mpegts'
        self.engine = CaptureStream(standard=source.standard, seconds=seconds, container=container,
            field_order=field_order, video_bitrate=video_bitrate,
            auto_geometry='ntsc' if height == 480 else 'pal', conceal_gaps=False)
        self.done = threading.Event(); self.stopping = threading.Event()
        self.state = dict(state='recording', source='shared-native-windows', file=str(self.path),
            started_utc=datetime.now(timezone.utc).isoformat(), native_profile=profile,
            width=720, height=height, rate=f'{numerator}/{denominator}', field_order=field_order,
            field_dominance_physically_calibrated=False, video_bitrate_mbit=video_bitrate,
            loss_policy='strict-no-concealment', requested_seconds=seconds,
            container=container,
            disk_budget_bytes=needed, initial_free_bytes=free, return_code=None, errors=[])
        with self.manifest.open('x', encoding='utf-8') as target:
            json.dump(self.state, target)
        self.output = self.path.open('xb')
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.monitor = threading.Thread(target=self._disk_monitor, daemon=True)

    def _save(self):
        temporary = self.manifest.with_name(self.manifest.name + '.' + uuid.uuid4().hex + '.tmp')
        with temporary.open('x', encoding='utf-8') as target:
            json.dump(self.state, target, indent=2)
            target.flush(); os.fsync(target.fileno())
        os.replace(temporary, self.manifest)  # Only this session's reserved manifest.

    def _disk_monitor(self):
        while not self.done.wait(1):
            try:
                free = shutil.disk_usage(self.path.parent).free
                self.state['free_bytes'] = free
                if free < 67108864:
                    self.engine.fail('recording disk reserve exhausted'); self.stopping.set(); return
            except OSError as error:
                self.engine.fail(error); return

    def _run(self):
        try:
            try:
                code = run_windows(self.engine, self.output, self.log_path,
                                   native_factory=self.source.session_factory)
            finally:
                self.output.close()
            if not self.engine.stats.video_frames or not self.engine.stats.audio_bytes:
                self.engine.errors.append('empty recording is not a successful archive'); code = 1
            self.state.update(state='failed' if code else 'captured-unverified', return_code=code,
                ended_utc=datetime.now(timezone.utc).isoformat(), capture=asdict(self.engine.stats),
                windows=getattr(self.engine, 'windows_status', None), errors=list(self.engine.errors),
                file_bytes=self.path.stat().st_size, manually_stopped=self.engine.requested_stop)
        except Exception as error:
            self.state.update(state='failed', return_code=1, errors=list(self.engine.errors)+[str(error)])
        finally:
            try:
                self._save()
            finally:
                self.done.set()

    def start(self):
        self.thread.start(); self.monitor.start()

    def stop(self):
        self.stopping.set(); self.engine.stop()
