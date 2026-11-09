# SPDX-License-Identifier: GPL-2.0-or-later
"""Explicitly lossy trick-mode display; strict archival Decoder is unchanged."""
from bt656 import Decoder


class PreviewDecoder(Decoder):
    def __init__(self, width, height, emit, frame_event=None):
        super().__init__(width, height, emit, frame_event)
        self.last_image = bytes([128, 16, 128, 16]) * (width * height // 2)
        self.partial_frames = 0
        self.last_partial = False

    def _line(self, field, payload):
        # A damaged source may repeat a field indefinitely. Keep bounded rows.
        if field == self.field and len(self.lines[field]) > self.height // 2:
            self.bad[field] = True
            return
        super()._line(field, payload)

    def _boundary(self, marker):
        if self.field != 1 or marker & 0x40:
            return
        half = self.height // 2
        complete = self.first_complete and not any(self.bad) and len(self.lines[1]) == half
        if not complete and min(map(len, self.lines)) < max(1, self.height // 8):
            return
        frame = bytearray(self.last_image)
        for field in (0, 1):
            for line, data in enumerate(self.lines[field][:half]):
                offset = (line * 2 + field) * self.stride
                frame[offset:offset + self.stride] = data
        self.last_partial = not complete
        self.partial_frames += int(self.last_partial)
        self.last_image = bytes(frame)
        self.emit(self.last_image)
        if self.frame_event:
            self.frame_event(self.frames, *self.starts)
        self.frames += 1
        self.lines = [[], []]; self.bad = [False, False]
        self.first_complete = False; self.field = None
