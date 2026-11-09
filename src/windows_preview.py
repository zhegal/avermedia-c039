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
    def __init__(self, audio, standard='auto', *, enable_preview=True):
        self.audio = audio
        self.standard = standard
        self.enable_preview = enable_preview
        self.closing = threading.Event(); self.done = threading.Event(); self.processed = threading.Event()
        self.input = queue.Queue(128); self.frames = queue.Queue(3)
        self.native = None; self.native_lock = threading.Lock()
        self.manual_restart = threading.Event()
        self.subscriber_lock = threading.Lock(); self.subscribers = set()
        self.current_profile = None; self.last_batch = {}; self.native_generation = 0
        self.generation = 0
        self.signal = None
        self.events = deque(maxlen=32)
        self.state = dict(frames=0, partial_frames=0, preview_drops=0, recoveries=0,
                          geometry_changes=0, silence_samples=0, source_audio_samples=0,
                          height=576, rate='25/1', error='', waiting=True, native_result=None)
        self.state['preview_queue_resets'] = 0
        self.state['manual_changes'] = 0
        self.state.update(complete_frames=0, full_streak=0, last_complete_usb_us=None, last_complete_monotonic=0.)
        self.state['last_frame_monotonic'] = 0.
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
        if self.closing.is_set() or not self.enable_preview:
            return
        try:
            self.input.put_nowait(item)
        except queue.Full:
            # Preview pressure must never stall USB or a strict subscriber.
            self.state['preview_queue_resets'] += 1
            while True:
                try:
                    self.input.get_nowait()
                except queue.Empty:
                    break
            self.input.put_nowait(('epoch', self.native_generation))
            if self.current_profile:
                self.input.put_nowait(('profile', *self.current_profile))
            self.input.put_nowait(item)

    def subscribe(self, consumer):
        with self.subscriber_lock:
            if self.closing.is_set():
                raise RuntimeError('source is stopping')
            self.subscribers.add(consumer)
            start = max(self.last_batch.values()) + 8000 if len(self.last_batch) == 2 else None
            return self.current_profile, self.signal, start

    def unsubscribe(self, consumer):
        with self.subscriber_lock:
            self.subscribers.discard(consumer)

    def session_factory(self, **options):
        from windows_shared import SharedSession
        return SharedSession(self, **options)

    def _publish(self, item):
        with self.subscriber_lock:
            if item[0] == 'profile':
                self.current_profile = tuple(item[1:])
                if not self.enable_preview:
                    self.state['height'] = item[2]; self.state['rate'] = f'{item[3]}/{item[4]}'
            elif item[0] == 'batch':
                self.last_batch[item[1]] = item[4]
            elif item[0] == 'signal':
                self.signal = item[1]
            for consumer in tuple(self.subscribers):
                consumer.offer(item)
        if item[0] in ('batch', 'profile'):
            self._enqueue(item)

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
            self.state['last_frame_monotonic'] = time.monotonic()
            self.state['partial_frames'] += int(self.decoder.last_partial)
            period = 40000 if height == 576 else 1001000/30
            try:
                second_stamp = self.video_window.byte_time(self.decoder_base + second)
            except StreamError:
                second_stamp = stamp + period/2
            if self.decoder.last_partial:
                self.state['full_streak'] = 0
            else:
                previous = self.state['last_complete_usb_us']
                self.state['full_streak'] = self.state['full_streak']+1 if previous is not None and abs(stamp-previous-period)<=1000 else 1
                self.state['complete_frames'] += 1
                self.state['last_complete_usb_us'] = stamp
                self.state['last_complete_monotonic'] = time.monotonic()
            self.state['preview_drops'] += put_latest(self.frames, (frame, height, stamp, self.generation, second_stamp))
            self.state['waiting'] = False
            if self.state['native_result'] is None and self.state['error'].startswith(('USB result', 'native:')):
                self.state['error'] = ''

        return PreviewDecoder(720, height, images.append, event)

    def _reset_epoch(self, generation):
        self.generation += 1
        self.video_window = PacketWindow(); self.audio_window = PacketWindow()
        self.video_offset = self.audio_offset = self.decoder_base = self.video_stamp = 0
        self.pending_pcm.clear()
        self.decoder = self._decoder(self.state['height'])
        if self.audio:
            self.audio.reset()
        self.state['waiting'] = True
        self.state['full_streak'] = 0; self.state['last_complete_usb_us'] = None

    def _profile(self, ident, height, numerator, denominator):
        self.state['full_streak'] = 0
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
                    # Rendering/audio failure is local to this preview branch.
                    # Keep native USB and any strict subscribers running.
                    self.closing.wait(.5)
                    self._enqueue(('epoch', self.native_generation))
        finally:
            self.processed.set()

    def _capture(self):
        generation = 0
        try:
            while not self.closing.is_set():
                generation += 1
                self.native_generation = generation
                if generation > 1:
                    self._publish(('epoch', generation))
                self._enqueue(('epoch', generation))
                self.state['native_result'] = None
                source = None
                try:
                    source = NativeSession(standard=self.standard, decode_frames=False,
                        on_batch=lambda *values: self._publish(('batch', *values)),
                        on_standard=lambda *values: self._publish(('profile', *values)),
                        on_signal=lambda value: self._publish(('signal', value)))
                    with self.native_lock:
                        self.native = source
                    result = source.run()
                    self.state['native_result'] = result
                    self._publish(('end', result))
                    if not self.closing.is_set():
                        if not (result == 0 and self.manual_restart.is_set()):
                            self.state['error'] = f'USB result {result}; ожидание восстановления'
                        self._event(f'native_result={result}; logical preview remains open')
                except Exception as error:
                    result = getattr(source, 'last_result', None) or 1
                    self.state['error'] = 'native: '+str(error); self._event(f'native_error {error}')
                    self._publish(('end', result))
                finally:
                    with self.native_lock:
                        self.native = None
                        if source:
                            source.close()
                if self.closing.is_set():
                    break
                if self.manual_restart.is_set():
                    self.manual_restart.clear(); self.state['manual_changes'] += 1
                else:
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
        if self.enable_preview:
            self.process_thread.start()
        else:
            self.processed.set()
        self.capture_thread.start()

    def stop(self):
        self.closing.set()
        with self.native_lock:
            if self.native:
                self.native.stop()

    def set_standard(self, standard):
        self.standard = standard; self.manual_restart.set()
        self._event(f'manual selection={standard}; logical viewer retained')
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
