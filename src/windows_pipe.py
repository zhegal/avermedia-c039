# SPDX-License-Identifier: GPL-2.0-or-later
"""Deadline-bound overlapped Windows named-pipe writer for FFmpeg inputs."""
import ctypes as C
from ctypes import wintypes as W
import time
import uuid


class Overlapped(C.Structure):
    _fields_ = [('Internal', C.c_size_t), ('InternalHigh', C.c_size_t),
                ('Offset', W.DWORD), ('OffsetHigh', W.DWORD), ('hEvent', W.HANDLE)]


class PipeWriter:
    def __init__(self):
        self.api = C.WinDLL('kernel32', use_last_error=True)
        for name, args, result in (
            ('CreateNamedPipeW', [W.LPCWSTR, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, W.DWORD, C.c_void_p], W.HANDLE),
            ('CreateEventW', [C.c_void_p, W.BOOL, W.BOOL, W.LPCWSTR], W.HANDLE),
            ('ConnectNamedPipe', [W.HANDLE, C.POINTER(Overlapped)], W.BOOL),
            ('WriteFile', [W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.POINTER(Overlapped)], W.BOOL),
            ('GetOverlappedResult', [W.HANDLE, C.POINTER(Overlapped), C.POINTER(W.DWORD), W.BOOL], W.BOOL),
            ('CancelIoEx', [W.HANDLE, C.POINTER(Overlapped)], W.BOOL),
            ('WaitForSingleObject', [W.HANDLE, W.DWORD], W.DWORD),
            ('ResetEvent', [W.HANDLE], W.BOOL), ('CloseHandle', [W.HANDLE], W.BOOL),
        ):
            fn = getattr(self.api, name); fn.argtypes = args; fn.restype = result
        self.path = '\\\\.\\pipe\\c039-' + uuid.uuid4().hex
        # Outbound byte stream, overlapped, first-instance-only, local clients.
        self.handle = self.api.CreateNamedPipeW(self.path, 0x40080002, 0x8, 1, 1048576, 0, 0, None)
        if self.handle == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        self.operation = Overlapped()
        self.operation.hEvent = self.api.CreateEventW(None, True, False, None)
        if not self.operation.hEvent:
            self.api.CloseHandle(self.handle); self.handle = None
            raise C.WinError(C.get_last_error())
        self.pending = False
        self.buffer = None

    def _wait(self, timeout):
        if self.api.WaitForSingleObject(self.operation.hEvent, int(timeout * 1000)) != 0:
            self.cancel()
            if self.api.WaitForSingleObject(self.operation.hEvent, 2000) == 0:
                transferred = W.DWORD()
                self.api.GetOverlappedResult(self.handle, C.byref(self.operation), C.byref(transferred), False)
                self.pending = False; self.buffer = None
            raise TimeoutError('FFmpeg input pipe stalled')
        transferred = W.DWORD()
        ok = self.api.GetOverlappedResult(self.handle, C.byref(self.operation), C.byref(transferred), False)
        self.pending = False; self.buffer = None
        if not ok:
            raise C.WinError(C.get_last_error())
        return transferred.value

    def connect(self, timeout=10):
        self.api.ResetEvent(self.operation.hEvent)
        if self.api.ConnectNamedPipe(self.handle, C.byref(self.operation)):
            return
        code = C.get_last_error()
        if code == 535:  # ERROR_PIPE_CONNECTED
            return
        if code != 997:  # ERROR_IO_PENDING
            raise C.WinError(code)
        self.pending = True
        self._wait(timeout)

    def write(self, data, timeout=2):
        deadline = time.monotonic() + timeout
        offset = 0
        while offset < len(data):
            self.api.ResetEvent(self.operation.hEvent)
            self.buffer = C.create_string_buffer(data[offset:])
            transferred = W.DWORD()
            if self.api.WriteFile(self.handle, self.buffer, len(data) - offset,
                                  C.byref(transferred), C.byref(self.operation)):
                count = transferred.value; self.buffer = None
            else:
                code = C.get_last_error()
                if code != 997:
                    self.buffer = None; raise C.WinError(code)
                self.pending = True
                count = self._wait(max(0, deadline - time.monotonic()))
            if not count:
                raise OSError('zero-length pipe write')
            offset += count

    def cancel(self):
        if self.handle:
            self.api.CancelIoEx(self.handle, C.byref(self.operation))

    def close(self):
        if self.pending:
            self.cancel()
            if self.api.WaitForSingleObject(self.operation.hEvent, 2000) != 0:
                # Keep this instance alive: Windows may still hold its buffer.
                _retained.append(self)
                return
            self.pending = False; self.buffer = None
        if self.handle:
            self.api.CloseHandle(self.handle); self.handle = None
        if self.operation.hEvent:
            self.api.CloseHandle(self.operation.hEvent); self.operation.hEvent = None


_retained = []
