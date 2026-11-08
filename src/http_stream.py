# SPDX-License-Identifier: GPL-2.0-or-later
"""Loopback MPEG-TS fanout with bounded GOP replay and per-client queues."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import queue
import threading
import time

PACKET = 188


class Subscriber:
    def __init__(self, capacity):
        self.queue = queue.Queue(maxsize=capacity)
        self.closed = False


class TransportBroker:
    def __init__(self, *, queue_size=64, max_clients=8, replay_limit=4 * 1024 * 1024):
        self.changed = threading.Condition()
        self.clients = set()
        self.queue_size, self.max_clients = queue_size, max_clients
        self.replay_limit = replay_limit
        self.tables = {}
        self.gop = bytearray()
        self.pending = bytearray()
        self.ended = False
        self.bytes = self.slow_clients = 0

    def publish(self, data):
        with self.changed:
            if self.ended:
                return
            self.pending.extend(data)
            count = len(self.pending) // PACKET * PACKET
            if not count:
                return
            batch = bytes(self.pending[:count]); del self.pending[:count]
            for pos in range(0, len(batch), PACKET):
                packet = batch[pos:pos + PACKET]
                if packet[0] != 0x47 or packet[1] & 0x80:
                    raise ValueError('invalid MPEG-TS packet')
                pid = ((packet[1] & 31) << 8) | packet[2]
                # IDs from the fixed FFmpeg single-program mux configuration.
                if pid in (0, 17, 4096):
                    self.tables[pid] = packet
                random_access = (pid == 256 and packet[3] & 0x20
                                 and packet[4] and packet[5] & 0x40)
                if random_access and 0 in self.tables and 4096 in self.tables:
                    self.gop = bytearray(b''.join(self.tables[k] for k in (0, 4096, 17) if k in self.tables))
                if self.gop:
                    self.gop.extend(packet)
                    if len(self.gop) > self.replay_limit:
                        self.gop.clear()
            self.bytes += len(batch)
            for client in tuple(self.clients):
                try:
                    client.queue.put_nowait(batch)
                except queue.Full:
                    client.closed = True
                    self.clients.remove(client)
                    self.slow_clients += 1
            self.changed.notify_all()

    def subscribe(self, timeout=5):
        with self.changed:
            deadline = time.monotonic() + timeout
            while not self.gop and not self.ended:
                left = deadline - time.monotonic()
                if left <= 0:
                    return None
                self.changed.wait(left)
            if self.ended or len(self.clients) >= self.max_clients:
                return None
            client = Subscriber(self.queue_size)
            client.queue.put_nowait(bytes(self.gop))
            self.clients.add(client)
            return client

    def unsubscribe(self, client):
        with self.changed:
            client.closed = True
            self.clients.discard(client)

    def close(self):
        with self.changed:
            self.ended = True
            for client in self.clients:
                try:
                    client.queue.put_nowait(None)
                except queue.Full:
                    client.closed = True
            self.changed.notify_all()

    def status(self):
        with self.changed:
            return dict(ready=bool(self.gop) and not self.ended, clients=len(self.clients),
                        slow_clients=self.slow_clients, transport_bytes=self.bytes,
                        replay_bytes=len(self.gop), ended=self.ended)


def make_server(port, broker, status=None):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            if self.path in ('/status', '/health'):
                state = broker.status()
                if status:
                    state.update(status())
                data = json.dumps(state).encode()
                self.send_response(200 if self.path == '/status' or state['ready'] else 503)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers(); self.wfile.write(data)
                return
            if self.path != '/live.ts':
                self.send_error(404); return
            client = broker.subscribe()
            if client is None:
                self.send_error(503, 'stream not ready or client limit reached'); return
            self.connection.settimeout(2)
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp2t')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Connection', 'close')
                self.end_headers()
                while not client.closed:
                    try:
                        data = client.queue.get(timeout=1)
                    except queue.Empty:
                        continue
                    if data is None:
                        break
                    self.wfile.write(data)
            except (OSError, BrokenPipeError):
                pass
            finally:
                broker.unsubscribe(client)

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    return server
