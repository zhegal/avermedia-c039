"""Recording arm/retry control without USB or an encoder."""
from pathlib import Path
import sys
import threading
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from recording_session import RecordingSession


class SessionControl(unittest.TestCase):
    def test_source_break_creates_part_and_manual_stop_disarms(self):
        folder = ROOT/'build/session-tests'/uuid.uuid4().hex
        folder.mkdir(parents=True)
        started = threading.Event()
        parts = []

        class Source:
            state = {}

        class Part:
            def __init__(self, source, path, **options):
                self.path = path
                self.manifest = options['diagnostics_dir']/'manifest.json'
                self.done = threading.Event()
                self.state = dict(state='failed', return_code=1,
                                  errors=['video timestamp gap'], rate='25/1')
                parts.append(self)

            def start(self):
                self.path.write_bytes(b'test media')
                if len(parts) == 1:
                    self.done.set()
                else:
                    started.set()

            def stop(self):
                self.done.set()

        session = RecordingSession(Source(), folder/'capture.ts', field_order='tff',
            part_factory=Part, ready=lambda: True, diagnostics_dir=folder.parent/'private')
        session.start()
        try:
            self.assertTrue(started.wait(5))
        finally:
            session.stop()
        self.assertTrue(session.done.wait(5))
        self.assertEqual(session.state['phase'], 'stopped')
        self.assertFalse(session.state['armed'])
        self.assertEqual(session.state['breaks'], 1)
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         ['capture.part0002.ts', 'capture.ts'])
        self.assertEqual(len(parts), 2)
