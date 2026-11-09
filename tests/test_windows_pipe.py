"""Real Windows named-pipe framing and deadline tests; no USB or driver access."""
import os
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


@unittest.skipUnless(os.name == 'nt', 'Windows named pipes only')
class WindowsPipes(unittest.TestCase):
    def test_byte_exact_writes_larger_than_pipe_capacity_and_eof(self):
        from windows_pipe import PipeWriter
        pipe = PipeWriter(); errors = []
        expected = bytes(range(256)) * 16000

        def writer():
            try:
                pipe.connect(); pipe.write(expected)
            except Exception as error:
                errors.append(error)
            finally:
                pipe.close()

        thread = threading.Thread(target=writer); thread.start()
        with open(pipe.path, 'rb', buffering=0) as source:
            actual = bytearray()
            while chunk := source.read(17391):
                actual.extend(chunk)
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive()); self.assertFalse(errors)
        self.assertEqual(actual, expected)

    def test_absent_reader_has_bounded_connect_and_releases_resources(self):
        from windows_pipe import PipeWriter
        pipe = PipeWriter()
        with self.assertRaises(TimeoutError):
            pipe.connect(timeout=.05)
        pipe.close(); self.assertIsNone(pipe.handle)

    def test_connected_but_stalled_reader_times_out_without_partial_success(self):
        from windows_pipe import PipeWriter
        pipe = PipeWriter(); errors = []

        def writer():
            try:
                pipe.connect(); pipe.write(b'x' * 4000000, timeout=.1)
            except Exception as error:
                errors.append(error)
            finally:
                pipe.close()

        thread = threading.Thread(target=writer); thread.start()
        with open(pipe.path, 'rb', buffering=0):
            thread.join(timeout=3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1); self.assertIsInstance(errors[0], TimeoutError)
        self.assertIsNone(pipe.handle)
