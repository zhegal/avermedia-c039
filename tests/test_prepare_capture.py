"""Integration checks for USB-based alignment and refusal of timing gaps."""
import array
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HEADER = ['bus_frame', 'microframe', 'transfer_status', 'packet_status', 'length', 'file_offset']


def fixture(prefix, gap=False):
    raw = bytearray()
    rows = []
    for frame in range(3):
        data = b''.join(b'\xff\0\0' + bytes([0x80 | (field << 6)]) + bytes([16 + field]) * 1440
                        for field in (0, 1) for line in range(288))
        for i in range(0, len(data), 2888):
            time = 1000000 + frame * 40000 + (i // 2888) * 125 + (40000 if gap and frame else 0)
            chunk = data[i:i + 2888]
            rows.append([time // 1000, time % 1000 // 125, '00000000', '00000000', len(chunk), len(raw)])
            raw.extend(chunk)
    rows.append([1120, 0, '00000000', '00000000', 4, len(raw)])
    raw.extend(b'\xff\0\0\x80')
    Path(str(prefix) + '.video.bin').write_bytes(raw)
    with open(str(prefix) + '.video.bin.packets.csv', 'w') as out:
        writer = csv.writer(out); writer.writerow(HEADER); writer.writerows(rows)
    samples = array.array('h', (sample * sign for sample in range(6720) for sign in (1, -1)))
    Path(str(prefix) + '.audio.s16le').write_bytes(samples.tobytes())
    with open(str(prefix) + '.audio.s16le.packets.csv', 'w') as out:
        writer = csv.writer(out); writer.writerow(HEADER)
        for i in range(0, len(samples) * 2, 24):
            time = 990000 + (i // 24) * 125
            writer.writerow([time // 1000, time % 1000 // 125, '00000000', '00000000', 24, i])


class PrepareTests(unittest.TestCase):
    def test_aligns_complete_frames_and_stereo_sample_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / 'capture'; fixture(prefix)
            result = subprocess.run([sys.executable, str(ROOT / 'tools/prepare_capture.py'), str(prefix)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary['frames'], 3)
            self.assertEqual(summary['audio_skip_samples'], 480)
            self.assertEqual(summary['aligned_audio_samples'], 5760)
            audio = array.array('h', Path(str(prefix) + '.aligned.s16le').read_bytes())
            self.assertEqual(audio[:4].tolist(), [480, -480, 481, -481])
            self.assertEqual(Path(str(prefix) + '.uyvy').stat().st_size, 3 * 720 * 576 * 2)

    def test_timing_gap_does_not_silently_create_cfr_export(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / 'capture'; fixture(prefix, gap=True)
            result = subprocess.run([sys.executable, str(ROOT / 'tools/prepare_capture.py'), str(prefix)],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('discontinuous video', result.stderr)
            self.assertFalse(Path(str(prefix) + '.aligned.s16le').exists())
