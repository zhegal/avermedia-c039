# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded, read-only subscriptions to the persistent viewer's single USB owner."""
import queue
import threading
import time

from capture_stream import StreamError


class SharedSession:
    """NativeSession-shaped consumer. stop()/close() never stop the USB owner."""
    def __init__(self, source, *, queue_capacity=128, **options):
        self.source = source; self.options = options
        self.queue = queue.Queue(queue_capacity)
        self.primed = None; self.buffering = False; self.buffer_bytes = 0
        self.last_buffered_us = None
        self.stopped = threading.Event()
        self.failure = None; self.last_result = None
        self.start_us = None
        self.closed_endpoints = set()
        self.stop_cutoff = None
        self.stop_deadline = None

    def offer(self, item):
        if self.stopped.is_set() or self.failure:
            return
        if self.buffering:
            if item[0] in ('epoch', 'end') or (item[0]=='signal' and
                    not all(item[1].get(key) for key in ('present','hlock','vlock'))):
                self.failure = StreamError('source became unstable during retry buffering'); return
            if item[0]=='batch':
                self.buffer_bytes += len(item[2]); self.last_buffered_us = item[4]+8000
                if self.buffer_bytes > 96*1024*1024:
                    self.failure = StreamError('retry buffer byte budget exhausted'); return
        try:
            self.queue.put_nowait(item)
        except queue.Full:
            self.failure = StreamError('shared-source consumer queue exhausted; USB owner continues')

    def prime(self):
        self.buffering = True
        self.primed = self.source.subscribe(self)
        self.start_us = self.primed[2]

    def factory(self, **options):
        self.options = options
        return self

    def admit(self):
        # Commit the buffered prefix before creating a media file. A loss after
        # this boundary belongs to normal strict capture, not a failed candidate.
        with self.source.subscriber_lock:
            if self.failure:
                return False
            self.buffering = False
            return True

    def run(self):
        profile, signal, self.start_us = self.primed if self.primed is not None else self.source.subscribe(self)
        self.buffering = False
        try:
            if profile:
                self.options['on_standard'](*profile)
            if signal and self.options.get('on_signal'):
                self.options['on_signal'](signal)
            while not self.stopped.is_set():
                if self.failure:
                    raise self.failure
                try:
                    item = self.queue.get(timeout=.1)
                except queue.Empty:
                    if self.stop_deadline and time.monotonic() >= self.stop_deadline:
                        raise StreamError('shared stop cutoff did not drain within bounded deadline')
                    if self.source.done.is_set():
                        break
                    continue
                kind, *values = item
                if kind == 'profile':
                    self.options['on_standard'](*values)
                elif kind == 'signal':
                    if self.options.get('on_signal'):
                        self.options['on_signal'](values[0])
                elif kind == 'epoch':
                    raise StreamError('USB source epoch changed; strict continuity ended, viewer remains open')
                elif kind == 'end':
                    if values[0]:
                        raise StreamError(f'USB source ended with error {values[0]}; viewer remains open')
                    break
                else:
                    endpoint, data, descriptors, stamp = values
                    if self.start_us is None:
                        self.start_us = stamp
                    if stamp < self.start_us:
                        continue
                    seconds = self.options.get('seconds', 0)
                    cutoff = self.stop_cutoff if self.stop_cutoff is not None else (
                        self.start_us + seconds * 1000000 if seconds else None)
                    if cutoff is not None and stamp >= cutoff:
                        self.closed_endpoints.add(endpoint)
                        if self.closed_endpoints == {3, 4}:
                            break
                        continue
                    callback = self.options.get('on_batch')
                    if callback:
                        callback(endpoint, data, descriptors, stamp)
                    else:
                        for n, (offset, length, status) in enumerate(descriptors):
                            if status:
                                raise StreamError('USB packet error in shared source')
                            self.options['on_packet'](endpoint, data[offset:offset + length], stamp + n * 125)
            self.last_result = 0
            return 0
        except Exception:
            self.last_result = 1
            raise
        finally:
            self.source.unsubscribe(self)

    def stop(self):
        if self.stop_cutoff is not None or self.stopped.is_set():
            return
        with self.source.subscriber_lock:
            self.stop_deadline = time.monotonic() + 2
            if len(self.source.last_batch) == 2:
                # Drain both streams to one bus-time cutoff. No USB operation.
                self.stop_cutoff = max(self.source.last_batch.values()) + 8000
            else:
                self.stopped.set()

    def close(self):
        self.stopped.set(); self.source.unsubscribe(self)
