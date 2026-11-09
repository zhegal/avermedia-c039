# SPDX-License-Identifier: GPL-2.0-or-later
"""HTTP MPEG-TS consumer of the persistent native source; never owns USB."""
from collections import deque
from dataclasses import asdict
import os
from pathlib import Path
import threading
import time

from capture_stream import CaptureStream, ROOT
from http_stream import TransportBroker, make_server
from windows_stream import run_windows
from runtime_paths import diagnostics_root


class LiveHttpSource:
    def __init__(self, source, *, port=8079, field_order='tff', video_bitrate=12, strict=False):
        if field_order not in ('tff', 'bff'):
            raise ValueError('HTTP field order must be explicit tff/bff')
        self.source = source; self.port = port
        self.field_order, self.video_bitrate = field_order, video_bitrate
        self.strict = strict
        self.broker = TransportBroker(); self.stopping = threading.Event(); self.done = threading.Event()
        self.engine = None; self.last_summary = None
        self.events = deque(maxlen=32); self.parts = 0
        self.server = make_server(port, self.broker, self.status)
        self.port = self.server.server_address[1]
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.started = time.monotonic()
        self.log_folder = diagnostics_root() / 'Http' / str(time.time_ns())
        self.log_folder.mkdir(parents=True)

    def status(self):
        engine = self.engine
        return dict(ready=bool(engine and self.broker.status()['ready']),
            source='shared-native-windows', loss_policy='strict-parts' if self.strict else 'viewing-concealment',
            native_profile=self.source.current_profile, signal=self.source.signal,
            logical_viewer_open=not self.source.closing.is_set(),
            source_recoveries=self.source.state['recoveries'], encoded_parts=self.parts,
            video_bitrate_mbit=self.video_bitrate, field_order=self.field_order,
            capture=asdict(engine.stats) if engine else None,
            windows=getattr(engine, 'windows_status', None),
            errors=list(engine.errors) if engine else [], last_part=self.last_summary,
            events=list(self.events))

    def _run(self):
        try:
            while not self.stopping.is_set() and not self.source.closing.is_set():
                profile = self.source.current_profile
                if not profile:
                    self.stopping.wait(.1); continue
                _, height, numerator, denominator = profile
                self.parts += 1
                self.broker.begin_segment()
                engine = CaptureStream(standard=self.source.standard, container='mpegts',
                    field_order=self.field_order, video_bitrate=self.video_bitrate,
                    auto_geometry='ntsc' if height == 480 else 'pal', conceal_gaps=not self.strict)
                # Manual 525-line standards already select their native geometry.
                # Auto parts use the explicitly announced current source family.
                engine.timestamp_offset = max(0, time.monotonic() - self.started)
                engine.initial_discontinuity = True
                self.engine = engine
                self.events.append(dict(part=self.parts, native=f'720x{height}',
                                        rate=f'{numerator}/{denominator}', reason='encoder part started'))
                reader, writer = os.pipe()
                relay_error = []

                def relay():
                    try:
                        while chunk := os.read(reader, 188 * 64):
                            self.broker.publish(chunk)
                    except Exception as error:
                        relay_error.append(str(error)); engine.fail(error)
                    finally:
                        os.close(reader)

                relay_thread = threading.Thread(target=relay, daemon=True); relay_thread.start()
                try:
                    with os.fdopen(writer, 'wb') as output:
                        code = run_windows(engine, output,
                            self.log_folder / f'part-{self.parts:04}.log', native_factory=self.source.session_factory)
                except Exception as error:
                    engine.fail(error); code = 1
                relay_thread.join(timeout=3)
                if relay_thread.is_alive():
                    engine.fail('HTTP relay did not drain'); code = 1
                self.last_summary = dict(part=self.parts, return_code=code,
                    capture=asdict(engine.stats), errors=list(engine.errors), relay_errors=relay_error)
                self.events.append(dict(part=self.parts, reason='encoder part ended', errors=list(engine.errors)))
                self.engine = None
                if not self.stopping.is_set():
                    # Geometry/source errors end an explicit encoded part only.
                    # The native owner, viewer and HTTP listener remain alive.
                    self.stopping.wait(.25 if 'geometry' in ' '.join(engine.errors) else 1)
        finally:
            self.broker.close()
            self.server.shutdown(); self.server.server_close()
            self.server_thread.join(timeout=2)
            self.done.set()

    def start(self):
        self.server_thread.start(); self.thread.start()

    def stop(self):
        self.stopping.set()
        engine = self.engine
        if engine:
            engine.stop()  # Detaches its SharedSession, never stops native USB.


def run_headless(*, standard='auto', port=8079, field_order='tff', video_bitrate=12, strict=False, seconds=0):
    import signal
    from windows_preview import PreviewCapture
    source = PreviewCapture(None, standard, enable_preview=False)
    service = LiveHttpSource(source, port=port, field_order=field_order, video_bitrate=video_bitrate, strict=strict)
    stopped = threading.Event()

    def stop(*_):
        stopped.set(); service.stop(); source.stop()

    signal.signal(signal.SIGINT, stop); signal.signal(signal.SIGTERM, stop)
    source.start(); service.start()
    print(f'http://127.0.0.1:{service.port}/live.ts', flush=True)
    deadline = time.monotonic() + seconds if seconds else None
    try:
        while not stopped.wait(.1):
            if deadline and time.monotonic() >= deadline:
                stop()
    finally:
        stop()
        source.capture_thread.join(timeout=15); service.thread.join(timeout=20)
    return 1 if source.capture_thread.is_alive() or service.thread.is_alive() else 0
