"""Real HTTP/FFmpeg tests over a synthetic shared source, never USB hardware."""
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import unittest
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


class PacketPublisher:
    def __init__(self, source, change_family=False):
        self.source, self.change_family = source, change_family
        self.stop = threading.Event(); self.cursor = 1000000
        self.video, self.audio = [], []
        self.thread = threading.Thread(target=self.run, daemon=True)

    def packet(self, video):
        self.video.append(video); self.audio.append(b'\x10\0\xf0\xff'*6)
        if len(self.video) == 64:
            for endpoint, chunks in ((4, self.video), (3, self.audio)):
                descriptors = []; offset = 0
                for chunk in chunks:
                    descriptors.append((offset, len(chunk), 0)); offset += len(chunk)
                self.source._publish(('batch', endpoint, b''.join(chunks), tuple(descriptors), self.cursor))
            self.cursor += 8000; self.video.clear(); self.audio.clear()

    def run(self):
        frame = 0
        while not self.stop.is_set():
            ntsc = self.change_family and frame >= 30
            if frame == 30 and ntsc:
                while self.video:
                    self.packet(b'')
                self.source._publish(('profile', 3, 480, 30000, 1001))
            height, count = (480, 267) if ntsc else (576, 320)
            raw = b''.join(b'\xff\0\0'+bytes([0x80 | field<<6])+bytes([32+frame%100+field])*1440
                           for field in (0,1) for _ in range(height//2))
            for n in range(count):
                self.packet(raw[len(raw)*n//count:len(raw)*(n+1)//count])
            frame += 1
            self.stop.wait(.033375 if ntsc else .04)

    def close(self):
        self.stop.set(); self.thread.join(timeout=2)


@unittest.skipUnless(os.name == 'nt' and shutil.which('ffmpeg') and shutil.which('ffprobe'),
                     'Windows and FFmpeg required')
class WindowsHTTP(unittest.TestCase):
    def setup_source(self, change=False):
        from windows_preview import PreviewCapture
        from windows_http import LiveHttpSource
        source = PreviewCapture(None, enable_preview=False)
        source._publish(('profile', 1, 576, 25, 1))
        service = LiveHttpSource(source, port=0, field_order='tff', video_bitrate=8)
        service.start()
        publisher = PacketPublisher(source, change); publisher.thread.start()
        return source, service, publisher

    def get(self, service, path):
        connection = http.client.HTTPConnection('127.0.0.1', service.port, timeout=5)
        connection.request('GET', path); response = connection.getresponse()
        data = response.read(); code = response.status; connection.close()
        return code, json.loads(data)

    def wait_ready(self, service, part=1):
        deadline = time.monotonic()+8
        while time.monotonic() < deadline:
            code, state = self.get(service, '/health')
            if code == 200 and state['encoded_parts'] >= part:
                return state
            time.sleep(.02)
        self.fail(f'HTTP did not become ready: {service.status()}')

    def test_two_clients_and_health_use_one_encoder_and_do_not_stop_owner(self):
        source, service, publisher = self.setup_source()
        clients = []
        try:
            state = self.wait_ready(service)
            self.assertEqual(state['loss_policy'], 'viewing-concealment')
            for _ in range(2):
                client = http.client.HTTPConnection('127.0.0.1', service.port, timeout=5)
                client.request('GET','/live.ts')
                response = client.getresponse(); self.assertEqual(response.status,200)
                clients.append((client,response))
                data=response.read(188*8)
                self.assertEqual(len(data),188*8); self.assertTrue(all(data[n]==0x47 for n in range(0,len(data),188)))
            code, state = self.get(service,'/status')
            self.assertEqual(code,200); self.assertEqual(state['clients'],2)
            self.assertEqual(len(source.subscribers),1)
            self.assertIsNone(source.native); self.assertFalse(source.closing.is_set())
        finally:
            for client,response in clients:
                response.close(); client.close()
            service.stop(); self.assertTrue(service.done.wait(10)); publisher.close()
        self.assertFalse(source.closing.is_set()); self.assertFalse(source.subscribers)

    def test_625_to_525_is_announced_and_existing_http_client_decodes_both(self):
        source, service, publisher = self.setup_source(change=True)
        folder=ROOT/'build/http-tests'/uuid.uuid4().hex; folder.mkdir(parents=True)
        client=None; collector=None; failures=[]
        try:
            self.wait_ready(service)
            client=http.client.HTTPConnection('127.0.0.1',service.port,timeout=5)
            client.request('GET','/live.ts'); response=client.getresponse()

            def collect():
                try:
                    with (folder/'mixed.ts').open('xb') as output:
                        while data:=response.read(188*64):
                            output.write(data)
                except Exception as error:
                    failures.append(str(error))

            collector=threading.Thread(target=collect,daemon=True); collector.start()
            state=self.wait_ready(service,part=2)
            self.assertEqual(tuple(state['native_profile'][1:]),(480,30000,1001))
            self.assertTrue(any('geometry/rate family changed' in ' '.join(event.get('errors',[]))
                                for event in state['events']),state)
            time.sleep(.5)
        finally:
            service.stop(); self.assertTrue(service.done.wait(10)); publisher.close()
            if collector:
                collector.join(timeout=5); self.assertFalse(collector.is_alive())
            if client:
                client.close()
        self.assertFalse(failures,failures); self.assertFalse(source.closing.is_set())
        info=json.loads(subprocess.check_output(['ffprobe','-v','error','-select_streams','v:0',
            '-show_frames','-of','json',str(folder/'mixed.ts')]))
        self.assertEqual({frame['height'] for frame in info['frames']},{480,576})
        subprocess.run(['ffmpeg','-v','error','-i',str(folder/'mixed.ts'),'-f','null','-'],check=True)
