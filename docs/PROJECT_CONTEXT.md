# Cross-platform development context

Updated 2026-11-09, Europe/Kyiv. Baseline: `2b8e72f`.
Working directory: `D:\AverMedia`; branch: `feature/windows-support`.

The requested goal is one macOS/Windows 10/11 x64 userspace C039 application.
Do not replace the macOS implementation or merge into main without approval.
Preserve raw interlacing, 720x576 at 25 fps for 625/50, stereo S16LE 48 kHz,
manual profiles and hardware Auto. Preserve the fixed-stream geometry guard
for 625/50 versus 525/59.94. Preview concealment is not archival continuity.

## Reuse and platform boundaries

- `av_init.c` already injects control, delay, cancellation, readiness and
  standard-change callbacks. Its bounded register journal, rollback and Auto
  monitor are reusable unchanged. Auto debounces three observations.
- `video_standard.c`, `frame_decoder.c` and `preview_audio.c` have no IOKit
  dependency. Keep hardware profiles in the shared C table.
- `capture_device.c`, `iso_probe.c`, `probe.c` and `host_probe.m` use Apple
  USB APIs. Keep them intact; a Windows transport must implement its own
  ownership, scheduling, cancellation and drain behind the existing callback
  contract. Do not duplicate AV initialization/decoder register sequences.
- `capture_stream.py` has POSIX FIFOs, select on file descriptors and process
  lifecycle assumptions; it is not yet a Windows live transport.
- `http_stream.py` uses standard Python socket/thread/queue APIs. Existing
  loopback/fanout tests can run on Windows. Live Windows encoding/USB hookup
  is still pending, even though the broker tests pass.
- Swift AppKit/CoreMediaIO/AVAudioEngine code is macOS-specific. Windows GUI
  and system camera integration are outside the minimal USB backend stage.

## Current implementation boundary

The Windows prototype lists cached USB descriptors and tests open/claim/release,
with no initialization writes. A libusb control callback maps exact-length
transfers to the existing C transport contract. It is not a complete streaming
backend. There is no Windows session_run, isochronous data capture, timestamp
qualification or live HTTP source yet. See [evidence and build](WINDOWS.md).

No driver bindings, registry settings, security settings or firmware changed.
No hardware success can be inferred from compilation or mock tests. Windows 10,
physical PAL/SECAM switching, NTSC, field dominance, lip-sync and long capture
remain unqualified. Do not create Setup.exe before backend qualification.
