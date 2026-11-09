# SPDX-License-Identifier: GPL-2.0-or-later
"""User-armed strict recording with explicit new files after source breaks."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
import uuid

from runtime_paths import diagnostics_root
from windows_recording import StrictRecording


class RecordingSession:
    def __init__(self, source, path, *, field_order, video_bitrate=12, auto_restart=True,
                 seconds=0, part_factory=StrictRecording, ready=None, diagnostics_dir=None):
        self.source, self.path = source, Path(path).resolve()
        if self.path.exists():
            raise FileExistsError('Recording already exists; choose a new filename')
        self.field_order, self.video_bitrate = field_order, video_bitrate
        self.auto_restart, self.seconds = auto_restart and not seconds, seconds
        self.part_factory, self.ready_override = part_factory, ready
        self.diagnostics = Path(diagnostics_dir or diagnostics_root()/'Recordings')/uuid.uuid4().hex
        self.diagnostics.mkdir(parents=True)
        self.manifest = self.diagnostics/'session.json'
        self.done = threading.Event(); self.stopping = threading.Event()
        self.current = None; self.lock = threading.Lock()
        self.wait_baseline = source.state.get('complete_frames',0)
        self.stable_since = None; self.stable_profile = None
        self.retry = None; self.retry_token = None
        self.state = dict(phase='waiting', armed=True, auto_restart=self.auto_restart,
            requested_path=str(self.path), started_utc=datetime.now(timezone.utc).isoformat(),
            parts=[], breaks=0, errors=[], diagnostics=str(self.diagnostics),
            retry_stability_seconds=2.0, retry_candidates=0, retry_rejections=0, retry_events=[])
        self.thread = threading.Thread(target=self._run,daemon=True)
        self._save()

    @property
    def engine(self):
        return self.current.engine if self.current else None

    def _save(self):
        self.state['auto_restart'] = self.auto_restart
        temporary=self.diagnostics/(uuid.uuid4().hex+'.tmp')
        with temporary.open('x',encoding='utf-8') as target:
            json.dump(self.state,target,indent=2); target.flush(); os.fsync(target.fileno())
        os.replace(temporary,self.manifest)

    def _signal_ready(self):
        if self.ready_override:
            return self.ready_override()
        profile, signal = self.source.current_profile, self.source.signal
        if not profile or not signal or not (signal['present'] and signal['hlock'] and signal['vlock']):
            self.stable_since=None; return False
        if self.source.standard=='auto' and signal['selected']!=signal['detected']:
            self.stable_since=None; return False
        state=self.source.state
        if getattr(self.source,'enable_preview',False):
            return (state.get('full_streak',0)>=3 and state.get('complete_frames',0)-self.wait_baseline>=3
                    and time.monotonic()-state.get('last_complete_monotonic',0)<.3)
        if self.stable_profile!=profile or self.stable_since is None:
            self.stable_profile=profile; self.stable_since=time.monotonic()
        return time.monotonic()-self.stable_since>=.6

    def _discard_retry(self, reason):
        if self.retry is None:
            return
        self.state['retry_rejections'] += 1
        self.state['retry_events'].append(dict(reason=reason, bytes=self.retry.buffer_bytes,
            first_usb_us=self.retry.start_us, last_usb_us=self.retry.last_buffered_us))
        del self.state['retry_events'][:-32]
        self.retry.close(); self.retry = None; self.retry_token = None

    def _ready(self):
        healthy = self._signal_ready()
        if not self.state['parts'] or self.ready_override:
            return healthy
        if not healthy:
            self._discard_retry('signal/complete-frame stability lost')
            return False
        state = self.source.state
        token = (self.source.current_profile, getattr(self.source,'generation',0),
                 state.get('complete_frames',0)-state.get('full_streak',0))
        if self.retry is not None and (token!=self.retry_token or self.retry.failure):
            self._discard_retry(str(self.retry.failure or 'complete-frame sequence changed'))
        if self.retry is None:
            from windows_shared import SharedSession
            self.retry = SharedSession(self.source, queue_capacity=768)
            self.retry.prime(); self.retry_token = token
            self.retry_started = time.monotonic()
            self.retry_baseline = state.get('complete_frames',0)
            self.state['retry_candidates'] += 1
        elapsed = time.monotonic()-self.retry_started
        self.state['retry_stable_seconds'] = min(elapsed,2.0)
        # Require both elapsed time and actual complete frames. Raw packets from
        # this entire interval are replayed to the strict parser after admission.
        _, _, num, den = self.source.current_profile
        enough_frames = (not getattr(self.source,'enable_preview',False) or
                         state.get('complete_frames',0)-self.retry_baseline >= (2*num+den-1)//den)
        return elapsed>=2.0 and enough_frames and self.retry.admit()

    @staticmethod
    def _source_break(errors):
        text=' '.join(errors)
        return any(fragment in text for fragment in ('timestamp gap','USB packet','geometry/rate family',
            'source epoch','USB source ended','native capture failed','shared-source consumer queue'))

    def _part_path(self, number):
        if number==1:
            return self.path
        return self.path.with_name(f'{self.path.stem}.part{number:04}{self.path.suffix}')

    def _run(self):
        try:
            previous_end=None
            while not self.stopping.is_set():
                self.state['phase']='waiting'; self._save()
                while not self.stopping.is_set() and not self._ready():
                    if self.state['parts'] and not self.auto_restart:
                        self.state['phase']='failed'; return
                    self.stopping.wait(.05)
                if self.stopping.is_set():
                    break
                number=len(self.state['parts'])+1
                path=self._part_path(number)
                part=self.part_factory(self.source,path,field_order=self.field_order,
                    video_bitrate=self.video_bitrate,seconds=self.seconds,
                    diagnostics_dir=self.diagnostics/'Parts',
                    **({'native_factory':self.retry.factory} if self.retry else {}))
                with self.lock:
                    self.current=part
                    if self.stopping.is_set():
                        part.stop()
                    self.state['phase']='recording'
                    self.state['parts'].append(dict(file=str(path), manifest=str(part.manifest), state='recording'))
                    self._save(); part.start(); self.retry = None; self.retry_token = None
                while not part.done.wait(.05):
                    if self.stopping.is_set():
                        part.stop()
                details=part.state
                counters=details.get('windows') or {}
                start=counters.get('first_video_usb_us'); end=counters.get('last_video_usb_us')
                entry=self.state['parts'][-1]
                entry.update(state=details['state'], errors=details.get('errors',[]), return_code=details.get('return_code'),
                    first_video_usb_us=start,last_video_usb_us=end,
                    video_frames=(details.get('capture') or {}).get('video_frames',0))
                if start is not None and previous_end is not None:
                    entry['source_gap_before_us']=start-previous_end
                if end is not None:
                    num,den=map(int,details['rate'].split('/')); previous_end=end+1000000*den/num
                self._save()
                if self.stopping.is_set() or (self.seconds and details.get('return_code')==0):
                    break
                errors=details.get('errors',[])
                if not self.auto_restart or (details.get('return_code') and not self._source_break(errors)):
                    self.state['phase']='failed'; self.state['errors']=errors; return
                self.state['breaks']+=1
                self.wait_baseline=self.source.state.get('complete_frames',0)
                self.stable_since=None
                self.state['phase']='waiting'; self._save()
                self.stopping.wait(.1)
            self.state['phase']='stopped'
        except Exception as error:
            self.state.update(phase='failed',errors=[str(error)])
        finally:
            self._discard_retry('recording disarmed before buffer admission')
            self.state['armed']=False
            self.state['ended_utc']=datetime.now(timezone.utc).isoformat()
            try:
                self._save()
            finally:
                self.done.set()

    def start(self):
        self.thread.start()

    def stop(self):
        self.stopping.set()
        with self.lock:
            if self.current and not self.current.done.is_set():
                self.current.stop()
