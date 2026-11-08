"""TS replay boundaries, independent slow consumers and loopback HTTP transport."""
import http.client
import json
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from http_stream import TransportBroker, make_server


def packet(pid, keyframe=False, value=0):
    head = bytes([0x47, 0x40 | (pid >> 8), pid & 255, 0x30 if keyframe else 0x10])
    return head + (bytes([1, 0x40]) if keyframe else b'') + bytes([value]) * (182 if keyframe else 184)


PAT, PMT, KEY, P = packet(0), packet(4096), packet(256, True, 1), packet(256, value=2)


class HTTPStreams(unittest.TestCase):
    def test_fragmented_writes_replay_tables_and_latest_keyframe(self):
        broker = TransportBroker()
        data = PAT + PMT + KEY + P
        for i in range(0, len(data), 53):
            broker.publish(data[i:i + 53])
        client = broker.subscribe(timeout=0)
        self.assertEqual(client.queue.get_nowait(), data)
        newer = packet(256, True, 3)
        broker.publish(newer)
        late = broker.subscribe(timeout=0)
        self.assertEqual(late.queue.get_nowait(), PAT + PMT + newer)

    def test_slow_client_does_not_drop_data_for_fast_client(self):
        broker = TransportBroker(queue_size=2)
        broker.publish(PAT + PMT + KEY)
        slow, fast = broker.subscribe(timeout=0), broker.subscribe(timeout=0)
        fast.queue.get_nowait()
        for _ in range(4):
            broker.publish(P)
            self.assertEqual(fast.queue.get_nowait(), P)
        self.assertTrue(slow.closed)
        self.assertFalse(fast.closed)
        self.assertEqual(broker.status()['slow_clients'], 1)

    def test_bounded_replay_and_client_limit(self):
        broker = TransportBroker(max_clients=1, replay_limit=4 * 188)
        broker.publish(PAT + PMT + KEY)
        client = broker.subscribe(timeout=0)
        self.assertIsNone(broker.subscribe(timeout=0))
        broker.publish(P * 3)
        self.assertLessEqual(broker.status()['replay_bytes'], 4 * 188)
        broker.unsubscribe(client); broker.close()
        self.assertIsNone(broker.subscribe(timeout=0))

    def test_invalid_transport_is_not_forwarded(self):
        broker = TransportBroker()
        with self.assertRaisesRegex(ValueError, 'MPEG-TS'):
            broker.publish(bytes(188))

    def test_loopback_http_media_and_status(self):
        broker = TransportBroker()
        broker.publish(PAT + PMT + KEY)
        server = make_server(0, broker)
        worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
        try:
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            client.request('GET', '/live.ts'); response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.getheader('Content-Type'), 'video/mp2t')
            self.assertEqual(response.read(3 * 188), PAT + PMT + KEY)
            broker.close()
            self.assertEqual(response.read(), b'')
            client.close()
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
            client.request('GET', '/health'); response = client.getresponse()
            self.assertEqual(response.status, 503)
            self.assertFalse(json.loads(response.read())['ready'])
            client.request('GET', '/status'); response = client.getresponse()
            self.assertEqual(response.status, 200)
            self.assertTrue(json.loads(response.read())['ended'])
            client.close()
        finally:
            server.shutdown(); server.server_close(); worker.join()
