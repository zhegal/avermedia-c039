# SPDX-License-Identifier: GPL-2.0-or-later
"""Persistent native-format preview, independent of fixed-geometry archive muxers."""
from collections import deque
import queue
import sys
import threading
import time

from capture_stream import PacketWindow, StreamError
from preview_decoder import PreviewDecoder
from windows_native import NativeSession


def put_latest(target, item):
    dropped = 0
    while True:
        try:
            target.put_nowait(item); return dropped
        except queue.Full:
            try:
                target.get_nowait(); dropped += 1
            except queue.Empty:
                pass


class PreviewCapture:
    def __init__(self, audio, standard='auto'):
        self.audio = audio
        self.standard = standard
        self.closing = threading.Event(); self.done = threading.Event(); self.processed = threading.Event()
        self.input = queue.Queue(128); self.frames = queue.Queue(3)
        self.native = None; self.native_lock = threading.Lock()
        self.generation = 0
        self.signal = None
        self.events = deque(maxlen=32)
        self.state = dict(frames=0, partial_frames=0, preview_drops=0, recoveries=0,
                          geometry_changes=0, silence_samples=0, source_audio_samples=0,
                          height=576, rate='25/1', error='', waiting=True, native_result=None)
        self.video_window = PacketWindow(); self.audio_window = PacketWindow()
        self.video_offset = self.audio_offset = self.decoder_base = self.video_stamp = 0
        self.pending_pcm = bytearray()
        self.decoder = self._decoder(576)
        self.capture_thread = threading.Thread(target=self._capture, daemon=True)
        self.process_thread = threading.Thread(target=self._process, daemon=True)

    def _event(self, text):
        self.events.append((time.monotonic(), text))
        print('preview_event ' + text, file=sys.stderr, flush=True)

    def _enqueue(self, item):
        if self.closing.is_set():
            return
        try:
            self.input.put_nowait(item)
        except queue.Full as error:
            raise RuntimeError('bounded native preview processing queue exhausted') from error

    def _decoder(self, height):
        images = []

        def event(index, first, second):
            frame = images.pop()
            try:
                stamp = self.video_window.byte_time(self.decoder_base + first)
            except StreamError:
                if not self.decoder.last_partial:
                    raise
                stamp = self.video_stamp - (40000 if height == 576 else 1001000 / 30)
            self.state['frames'] += 1
            self.state['partial_frames'] += int(self.decoder.last_partial)
            self.state['preview_drops'] += put_latest(self.frames, (frame, height, stamp, self.generation))
            self.state['waiting'] = False

        return PreviewDecoder(720, height, images.append, event)

    def _reset_epoch(self, generation):
        self.generation = generation
        self.video_window = PacketWindow(); self.audio_window = PacketWindow()
        self.video_offset = self.audio_offset = self.decoder_base = self.video_stamp = 0
        self.pending_pcm.clear()
        self.decoder = self._decoder(self.state['height'])
        if self.audio:
            self.audio.reset()
        self.state['waiting'] = True

    def _profile(self, ident, height, numerator, denominator):
        rate = f'{numerator}/{denominator}'
        if height != self.state['height'] or rate != self.state['rate']:
            self.state['geometry_changes'] += 1
            self.decoder_base = self.video_offset
            self.decoder = self._decoder(height)
            self.state['waiting'] = True
        self.state['height'], self.state['rate'] = height, rate
        self._event(f'profile id={ident} native=720x{height} rate={rate}; USB session retained')

    def _batch(self, endpoint, data, packets, first):
        if endpoint == 4:
            chunks = []
            for n, (offset, length, status) in enumerate(packets):
                if status or length > 2892 or offset + length > len(data):
                    raise RuntimeError('invalid native video packet')
                self.video_stamp = first + n * 125
                self.video_window.add_packet(self.video_offset, length, self.video_stamp)
                self.video_offset += length
                if length:
                    chunks.append(data[offset:offset + length])
            self.decoder.feed(b''.join(chunks))
        elif endpoint == 3:
            for n, (offset, length, status) in enumerate(packets):
                if status or length % 4 or offset + length > len(data):
                    raise RuntimeError('invalid native stereo PCM packet')
                self.state['source_audio_samples'] += length // 4
                chunk = data[offset:offset + length]
                if not chunk:
                    # Display monitoring only. Never used by strict recording.
                    chunk = bytes(24); self.state['silence_samples'] += 6
                self.audio_window.add_packet(self.audio_offset, len(chunk), first + n * 125)
                self.audio_offset += len(chunk); self.pending_pcm.extend(chunk)
            if self.audio:
                size = self.audio.block_bytes
                while len(self.pending_pcm) >= size and not self.closing.is_set():
                    self.audio.write(bytes(self.pending_pcm[:size]), self.closing)
                    del self.pending_pcm[:size]
            else:
                self.pending_pcm.clear()

    def _process(self):
        failed_epoch = False
        try:
            while True:
                try:
                    item = self.input.get(timeout=.1)
                except queue.Empty:
                    if self.done.is_set():
                        return
                    continue
                if self.closing.is_set():
                    continue
                try:
                    if item[0] == 'epoch':
                        self._reset_epoch(item[1])
                        failed_epoch = False
                    elif failed_epoch:
                        continue
                    elif item[0] == 'profile':
                        self._profile(*item[1:])
                    else:
                        self._batch(*item[1:])
                except Exception as error:
                    failed_epoch = True
                    self.state['error'] = str(error); self._event(f'processing_error {error}')
                    with self.native_lock:
                        if self.native:
                            self.native.stop()
                    # Keep the logical viewer alive. A fresh native epoch will
                    # reset decoder/PCM queues after the stopped source drains.
        finally:
            self.processed.set()

    def _capture(self):
        generation = 0
        try:
            while not self.closing.is_set():
                generation += 1
                self._enqueue(('epoch', generation))
                source = None
                try:
                    source = NativeSession(standard=self.standard, decode_frames=False,
                        on_batch=lambda *values: self._enqueue(('batch', *values)),
                        on_standard=lambda *values: self._enqueue(('profile', *values)),
                        on_signal=lambda value: setattr(self, 'signal', value))
                    with self.native_lock:
                        self.native = source
                    result = source.run()
                    self.state['native_result'] = result
                    if not self.closing.is_set():
                        self.state['error'] = f'USB result {result}; ожидание восстановления'
                        self._event(f'native_result={result}; logical preview remains open')
                except Exception as error:
                    result = getattr(source, 'last_result', None) or 1
                    self.state['error'] = str(error); self._event(f'native_error {error}')
                finally:
                    with self.native_lock:
                        self.native = None
                        if source:
                            source.close()
                if self.closing.is_set():
                    break
                self.state['recoveries'] += 1
                if result == 2:
                    # Do not blindly reopen after an unconfirmed restore/drain.
                    # The logical session/window remains open until manual Stop.
                    self.state['error'] = 'Ошибка восстановления USB; окно остаётся открытым. Требуется переподключение устройства.'
                    self._event('cleanup not confirmed; automatic reopen suspended')
                    self.closing.wait()
                else:
                    self.closing.wait(1)
        finally:
            self.done.set()

    def start(self):
        self.process_thread.start(); self.capture_thread.start()

    def stop(self):
        self.closing.set()
        with self.native_lock:
            if self.native:
                self.native.stop()

    def target_sample(self, stamp):
        window = self.audio_window
        with window.changed:
            if not window.rows:
                return None
            if stamp >= window.rows[-1][2] + 125:
                return None  # Video batch arrived before matching PCM metadata.
            if stamp < window.rows[0][2]:
                return 0 if window.rows[0][0] == 0 else -1
        return window.audio_offset(stamp) // 4
