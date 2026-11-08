"""Streaming integrity: packet errors, bounded history and delayed telemetry."""
import sys
from pathlib import Path
import threading
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from capture_stream import PacketWindow, StreamError, held_frames, VideoCadence


def packet(offset, time_us=1000000, length=24, status='00000000'):
    return f'{time_us // 1000},{time_us % 1000 // 125},00000000,{status},{length},{offset}'.encode()


class StreamingTimestamps(unittest.TestCase):
    def test_viewing_recovers_fractional_vhs_phase_change_without_accumulating_time(self):
        clock = VideoCadence(40000, True)
        self.assertEqual([clock.advance(t) for t in (0, 40000, 110000, 150000, 190000)],
                         [0, 0, 1, 0, 0])
        self.assertEqual(clock.sent, 6)

    def test_viewing_skips_early_frame_and_rejects_unbounded_outage(self):
        clock = VideoCadence(40000, True)
        self.assertEqual([clock.advance(t) for t in (0, 10000, 40000)], [0, -1, 0])
        with self.assertRaises(StreamError):
            clock.advance(3000000)

    def test_default_cadence_rejects_fractional_phase_change(self):
        clock = VideoCadence(40000)
        clock.advance(0)
        with self.assertRaises(StreamError):
            clock.advance(70000)

    def test_archival_timing_never_silently_holds_lost_frames(self):
        self.assertEqual(held_frames(1000000, 1039875, 40000), 0)
        with self.assertRaisesRegex(StreamError, 'timestamp gap'):
            held_frames(1000000, 1080000, 40000)

    def test_viewer_can_fill_bounded_integral_frame_gaps(self):
        self.assertEqual(held_frames(1000000, 1080000, 40000, True), 1)
        self.assertEqual(held_frames(1000000, 1280125, 40000, True), 6)
        self.assertEqual(held_frames(1000000, 1000000 + 3 * 1001000 / 30,
                                     1001000 / 30, True), 2)

    def test_viewer_rejects_large_reversed_or_unstable_timing(self):
        for delta in (0, -40000, 70000, 40000 * 52):
            with self.subTest(delta=delta), self.assertRaises(StreamError):
                held_frames(1000000, 1000000 + delta, 40000, True)

    def test_exact_byte_time_and_complete_stereo_sample_offset(self):
        window = PacketWindow()
        window.add(b'bus_frame,microframe,transfer_status,packet_status,length,file_offset')
        window.add(packet(0, length=0))
        window.add(packet(0, time_us=1000125))
        window.add(packet(24, time_us=1000250, status='e00002e7'))
        self.assertEqual(window.byte_time(12), 1000187.5)
        self.assertEqual(window.audio_offset(1000187.5), 12)
        self.assertEqual(window.audio_offset(1000250), 24)
        self.assertEqual(window.packets, 3)

    def test_history_eviction_fails_instead_of_guessing_time(self):
        window = PacketWindow(limit=2)
        for i in range(3):
            window.add(packet(i * 24, 1000000 + i * 125))
        with self.assertRaisesRegex(StreamError, 'outside bounded'):
            window.byte_time(0)
        self.assertEqual(window.byte_time(48), 1000250)

    def test_usb_error_and_missing_eof_packet_are_not_silent(self):
        window = PacketWindow()
        with self.assertRaisesRegex(StreamError, 'USB packet'):
            window.add(packet(0, status='e00002ed'))
        window.close()
        with self.assertRaisesRegex(StreamError, 'unavailable'):
            window.byte_time(0)

    def test_waits_for_metadata_flushed_after_media(self):
        window = PacketWindow()
        thread = threading.Thread(target=lambda: (time.sleep(.01), window.add(packet(0))))
        thread.start()
        self.assertEqual(window.byte_time(0), 1000000)
        thread.join()
