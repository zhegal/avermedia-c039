# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded stereo PCM monitor using Windows waveOut and its playback position."""
import ctypes as C
from ctypes import wintypes as W
import threading
import time


class Format(C.Structure):
    _pack_ = 1
    _fields_ = [('tag', W.WORD), ('channels', W.WORD), ('rate', W.DWORD),
                ('bytes_per_second', W.DWORD), ('align', W.WORD), ('bits', W.WORD), ('extra', W.WORD)]


class Header(C.Structure):
    _fields_ = [('data', C.c_void_p), ('length', W.DWORD), ('recorded', W.DWORD),
                ('user', C.c_size_t), ('flags', W.DWORD), ('loops', W.DWORD),
                ('next', C.c_void_p), ('reserved', C.c_size_t)]


class Position(C.Structure):
    _fields_ = [('kind', W.UINT), ('value', W.DWORD), ('padding', W.DWORD)]


class PcmMonitor:
    block_bytes = 3840  # 20 ms, 960 complete stereo samples.

    def __init__(self):
        self.api = C.WinDLL('winmm', use_last_error=True)
        for name, args in (
            ('waveOutOpen', [C.POINTER(W.HANDLE), W.UINT, C.POINTER(Format), C.c_size_t, C.c_size_t, W.DWORD]),
            ('waveOutPrepareHeader', [W.HANDLE, C.POINTER(Header), W.UINT]),
            ('waveOutUnprepareHeader', [W.HANDLE, C.POINTER(Header), W.UINT]),
            ('waveOutWrite', [W.HANDLE, C.POINTER(Header), W.UINT]),
            ('waveOutGetPosition', [W.HANDLE, C.POINTER(Position), W.UINT]),
            ('waveOutPause', [W.HANDLE]), ('waveOutRestart', [W.HANDLE]),
            ('waveOutReset', [W.HANDLE]), ('waveOutClose', [W.HANDLE]),
        ):
            fn = getattr(self.api, name); fn.argtypes = args; fn.restype = W.UINT
        self.lock = threading.Lock(); self.handle = W.HANDLE()
        fmt = Format(1, 2, 48000, 192000, 4, 16, 0)
        self.check(self.api.waveOutOpen(C.byref(self.handle), 0xffffffff, C.byref(fmt), 0, 0, 0), 'open PCM monitor')
        self.buffers = [C.create_string_buffer(self.block_bytes) for _ in range(16)]
        self.headers = []
        for data in self.buffers:
            header = Header(); header.data = C.addressof(data); header.length = self.block_bytes
            self.check(self.api.waveOutPrepareHeader(self.handle, C.byref(header), C.sizeof(header)), 'prepare PCM buffer')
            self.headers.append(header)
        self.index = self.submitted = 0; self.playing = False
        self.last_position = self.wrap = 0
        self.check(self.api.waveOutPause(self.handle), 'pause initial PCM')

    @staticmethod
    def check(code, operation):
        if code:
            raise OSError(f'{operation}: waveOut code {code}')

    def write(self, block, stopping):
        if len(block) != self.block_bytes:
            raise ValueError('PCM monitor requires a complete 20 ms block')
        deadline = time.monotonic() + 1
        while not stopping.is_set():
            with self.lock:
                header = self.headers[self.index]
                if not header.flags & 0x10:  # WHDR_INQUEUE
                    C.memmove(header.data, block, len(block))
                    self.check(self.api.waveOutWrite(self.handle, C.byref(header), C.sizeof(header)), 'queue PCM')
                    self.index = (self.index + 1) % len(self.headers)
                    self.submitted += len(block) // 4
                    return
            if time.monotonic() > deadline:
                raise TimeoutError('PCM playback device stalled')
            stopping.wait(.002)

    def start_if_ready(self):
        with self.lock:
            if not self.playing and self.submitted >= 9600:  # 200 ms includes preview deinterlacer latency.
                self.check(self.api.waveOutRestart(self.handle), 'start PCM monitor')
                self.playing = True

    def position(self):
        with self.lock:
            value = Position(2, 0, 0)  # TIME_SAMPLES; inspect returned kind.
            self.check(self.api.waveOutGetPosition(self.handle, C.byref(value), C.sizeof(value)), 'PCM position')
            if value.kind == 2:
                position = value.value
            elif value.kind == 1:  # TIME_MS fallback
                position = value.value * 48
            elif value.kind == 4:  # TIME_BYTES fallback
                position = value.value // 4
            else:
                raise OSError('PCM device supplied no supported playback clock')
            if position < self.last_position:
                self.wrap += 1 << 32
            self.last_position = position
            return self.wrap + position

    def reset(self):
        with self.lock:
            self.check(self.api.waveOutReset(self.handle), 'reset PCM monitor')
            self.check(self.api.waveOutPause(self.handle), 'pause PCM monitor')
            self.index = self.submitted = self.last_position = self.wrap = 0
            self.playing = False

    def close(self):
        with self.lock:
            if not self.handle:
                return
            self.api.waveOutReset(self.handle)
            for header in self.headers:
                self.check(self.api.waveOutUnprepareHeader(self.handle, C.byref(header), C.sizeof(header)), 'release PCM buffer')
            self.check(self.api.waveOutClose(self.handle), 'close PCM monitor')
            self.handle = W.HANDLE()
