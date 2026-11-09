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

Windows now has a native WinUSB `c039_session_run` implementation with scheduled
video/PCM reads on one bus-frame timeline, per-packet error checks, bounded
admission/stop/drain and alternate/register restoration. It reuses shared AV/Auto.
A 30-second raw check produced 749 complete 576-line frames with no internal
timing gaps and 240,000 successful packets per endpoint. Cancellation and injected
consumer failure restore controls; failed/partial raw results cannot be audited
as successful. See [evidence and build](WINDOWS.md).

The user additionally requested live preview. `tools/preview_windows.py` owns one
native session and uses bounded display queues, native field weaving and a Tk
window with decoder/lock status. RGB conversion and horizontal 4:3 display
correction are preview-only; no deinterlacing or raw capture modification.
Observed PAL/SECAM profile transitions retained the same USB session/window.
This is a diagnostic viewer, with no audio playback/archival recording controls.
Windows live HTTP/encoding integration is still pending; keep the explicit
CaptureStream Windows refusal until that separate transport edge is implemented.

The initial stage changed no bindings. On 2026-11-09 the user explicitly approved
a temporary signed WinUSB binding on MI_01 only. That binding and an AVerPola
restore/rebind round trip are now verified; see WINDOWS.md. Current MI_01 uses
the unmodified Microsoft inbox winusb.inf/WinUSB service. The tool adds its
application discovery GUID only to MI_01 Device Parameters. Parent and MI_00
PnP properties remain identical; no security settings/certificates changed.
No hardware success can be inferred from compilation or mock tests. Windows 10,
physical PAL/SECAM switching, NTSC, field dominance, lip-sync and long capture
remain unqualified. Do not create Setup.exe before backend qualification.
