# SPDX-License-Identifier: GPL-2.0-or-later
"""Thin ownership-safe ctypes binding to the Windows C session (no driver changes)."""
import ctypes as C
import threading
import struct
from pathlib import Path
from runtime_paths import binary_path


class Profile(C.Structure):
    _fields_ = [('id', C.c_uint), ('name', C.c_char_p)] + [(name, C.c_uint) for name in
        ('format', 'height', 'rate_num', 'rate_den', 'burst', 'luma', 'comb', 'subcarrier')]


class Signal(C.Structure):
    _fields_ = [(name, C.c_uint) for name in ('detected', 'selected', 'present', 'hlock', 'vlock', 'chroma')]


SAMPLE = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int, C.c_void_p, C.c_size_t, C.c_uint64)
FRAME = C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_size_t, C.c_uint)
STANDARD = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(Profile))
SIGNAL = C.CFUNCTYPE(None, C.c_void_p, C.POINTER(Signal))
BATCH = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int, C.c_void_p, C.c_size_t,
                   C.c_void_p, C.c_uint, C.c_uint64)


class NativeSession:
    def __init__(self, *, standard='auto', seconds=0, attenuation=6, on_frame=None,
                 on_signal=None, on_packet=None, on_standard=None, decode_frames=True, on_batch=None):
        path = binary_path('c039-capture.dll')
        self.lib = C.CDLL(str(path))
        self.ownership_lock = threading.Lock()
        lib = self.lib
        for name, args, result in (
            ('c039_standard_parse', [C.c_char_p], C.c_uint),
            ('c039_standard', [C.c_uint], C.POINTER(Profile)),
            ('c039_session_create', [C.c_uint, C.c_int, C.c_uint], C.c_void_p),
            ('c039_session_run', [C.c_void_p, SAMPLE, C.c_void_p], C.c_int),
            ('c039_session_stop', [C.c_void_p], None),
            ('c039_session_destroy', [C.c_void_p], None),
            ('c039_session_set_attenuation', [C.c_void_p, C.c_uint], None),
            ('c039_session_set_standard_callback', [C.c_void_p, STANDARD], None),
            ('c039_session_set_signal_callback', [C.c_void_p, SIGNAL], None),
            ('c039_frame_decoder_create', [C.c_uint, FRAME, C.c_void_p], C.c_void_p),
            ('c039_frame_decoder_feed', [C.c_void_p, C.c_void_p, C.c_size_t], None),
            ('c039_frame_decoder_set_height', [C.c_void_p, C.c_uint], None),
            ('c039_frame_decoder_destroy', [C.c_void_p], None),
        ):
            fn = getattr(lib, name); fn.argtypes = args; fn.restype = result
        mode = lib.c039_standard_parse(standard.encode('ascii'))
        if not mode:
            raise ValueError('unknown video standard')
        self.height = lib.c039_standard(1 if mode == 4 else mode).contents.height
        self.on_frame, self.on_signal = on_frame, on_signal
        self.on_packet, self.on_standard = on_packet, on_standard
        self.on_batch = on_batch
        self.decode_frames = decode_frames
        self.last_result = None
        self.video_packets = self.audio_packets = self.audio_bytes = 0
        self.callback_error = None
        self.session = lib.c039_session_create(mode, 0, seconds)
        self.frame_callback = FRAME(self._frame)
        self.sample_callback = SAMPLE(self._sample)
        self.standard_callback = STANDARD(self._standard)
        self.signal_callback = SIGNAL(self._signal)
        self.batch_callback = BATCH(self._batch)
        self.decoder = lib.c039_frame_decoder_create(self.height, self.frame_callback, None)
        if not self.session or not self.decoder:
            self.close(); raise RuntimeError('native session allocation failed')
        lib.c039_session_set_standard_callback(self.session, self.standard_callback)
        lib.c039_session_set_signal_callback(self.session, self.signal_callback)
        lib.c039_session_set_attenuation(self.session, attenuation)
        if on_batch:
            lib.c039_windows_session_set_batch_callback.argtypes = [C.c_void_p, BATCH]
            lib.c039_windows_session_set_batch_callback.restype = None
            lib.c039_windows_session_set_batch_callback(self.session, self.batch_callback)

    def _batch(self, _, endpoint, data, size, descriptors, count, stamp):
        try:
            records = tuple(struct.iter_unpack('<III', C.string_at(descriptors, count * 12)))
            self.on_batch(endpoint, C.string_at(data, size), records, stamp)
            if endpoint == 4:
                self.video_packets += count
            else:
                self.audio_packets += count
                self.audio_bytes += sum(length for _, length, _ in records)
            return int(self.callback_error is not None)
        except Exception as error:
            self.callback_error = error; return 1

    def _frame(self, _, data, size, height):
        try:
            if self.on_frame:
                self.on_frame(C.string_at(data, size), height)
        except Exception as error:
            self.callback_error = error; self.stop()

    def _sample(self, _, endpoint, data, size, stamp):
        try:
            if self.on_packet:
                self.on_packet(endpoint, C.string_at(data, size), stamp)
            if endpoint == 4:
                self.video_packets += 1
                if self.decode_frames:
                    self.lib.c039_frame_decoder_feed(self.decoder, data, size)
            elif endpoint == 3:
                if size % 4:
                    raise RuntimeError('incomplete stereo PCM sample')
                self.audio_packets += 1; self.audio_bytes += size
            else:
                raise RuntimeError('unexpected endpoint')
            return int(self.callback_error is not None)
        except Exception as error:
            self.callback_error = error; return 1

    def _standard(self, _, profile):
        try:
            value = profile.contents
            if self.on_standard:
                self.on_standard(value.id, value.height, value.rate_num, value.rate_den)
            if value.height != self.height:
                self.height = value.height
                self.lib.c039_frame_decoder_set_height(self.decoder, self.height)
        except Exception as error:
            self.callback_error = error; self.stop()

    def _signal(self, _, status):
        try:
            if self.on_signal:
                self.on_signal({name: getattr(status.contents, name) for name, _ in Signal._fields_})
        except Exception as error:
            self.callback_error = error; self.stop()

    def run(self):
        result = self.lib.c039_session_run(self.session, self.sample_callback, None)
        self.last_result = result
        if self.callback_error:
            raise RuntimeError(str(self.callback_error)) from self.callback_error
        return result

    def stop(self):
        with self.ownership_lock:
            if self.session:
                self.lib.c039_session_stop(self.session)

    def close(self):
        # Caller must join run() before destruction, matching the C API contract.
        with self.ownership_lock:
            if getattr(self, 'decoder', None):
                self.lib.c039_frame_decoder_destroy(self.decoder); self.decoder = None
            if getattr(self, 'session', None):
                self.lib.c039_session_destroy(self.session); self.session = None
