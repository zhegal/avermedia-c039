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
The user clarified that the logical viewer must end **only on manual Stop**, and
must keep audio/window alive through rewind and every supported native geometry
change. The default viewer is now `preview_windows_direct.py`: persistent Tk
window, preview-only incomplete-field rendering, WinMM PCM buffers and video
scheduled against the PCM playback sample clock. It accepts all nine shared
profiles and restarts only RGB conversion on 576/25 <-> 480/29.97 changes. Source
errors are shown; confirmed-clean source errors may reopen a native epoch inside
the same logical viewer. Unconfirmed cleanup suspends reopen instead of hiding
the failure. There is no archival recording control in this diagnostic viewer.

Do not use desktop automation/screenshots: the user rejected the “using your
computer” banner. Do not terminate their active viewer to rebuild/reload; they
stop it manually. See root AGENTS.md for these standing constraints.

The Windows fixed-geometry encoding edge now uses bounded local named pipes,
shared parser/cadence, PCM alignment and FFmpeg MPEG-2/MP2 or NUT. Software tests
pass, including strict-gap rejection versus explicitly lossy viewing. Live HTTP
hardware integration with the persistent shared viewer is the next work: do not
start a second USB owner or equate these software tests with physical MPEG-TS
qualification. Geometry changes still explicitly end fixed-format encoder parts,
**not** the logical viewer. Do not reconnect the viewer through that muxer.

The initial stage changed no bindings. On 2026-11-09 the user explicitly approved
a temporary signed WinUSB binding on MI_01 only. That binding and an AVerPola
restore/rebind round trip are now verified; see WINDOWS.md. Current MI_01 uses
the unmodified Microsoft inbox winusb.inf/WinUSB service. The tool adds its
application discovery GUID only to MI_01 Device Parameters. Parent and MI_00
PnP properties remain identical; no security settings/certificates changed.
No hardware success can be inferred from compilation or mock tests. Windows 10,
physical PAL/SECAM switching, NTSC, field dominance, lip-sync and long capture
remain unqualified. Do not create Setup.exe before backend qualification.

## Shared Windows HTTP and recording stage (2026-11-09)

Implemented one persistent native source with bounded subscriptions for preview,
HTTP and strict recording. HTTP reuses the existing broker and loopback endpoints;
encoder parts mark geometry/epoch discontinuities without closing the viewer.
Recording can remain armed across source breaks and resume in separate numbered
media files; manual Stop disarms it. Failed parts and gap diagnostics are retained.
Only media is written to the chosen output folder; private logs/manifests are under
LOCALAPPDATA/C039Recorder/Diagnostics. Existing user sidecars are not deleted.
The viewer adds a selectable/copyable URL, resizable 4:3/fullscreen display and
optional preview-only BWDIF. MPEG-2 output signals DAR 4:3 without pixel resizing.
Pillow is now required for this developer viewer; portable packaging is pending.

Validation: 51 Python tests pass, including synthetic two-client HTTP, PAL/NTSC
encoder-part transitions, full strict-file decode, media-only success/failure
folders and auto-retry/manual-disarm control. No USB is opened by these tests.
A prior physical 3-second shared recording retained 74 pictures and passed the
then-current timing/count checks; its old DAR was 5:4, so it does not qualify the
new aspect fix. Updated viewer PID 23368 was launched only after user manual Close;
HTTP reported ready with native SECAM 720x576/25, one encoder part and no reported
encoder errors at the check. Visual/audio acceptance of this latest version,
physical multi-client/NTSC, long strict recording and Windows 10 remain pending.
No installer, driver/security change, second USB owner or desktop automation.
This section supersedes earlier statements that shared HTTP/recording were pending
implementation; earlier evidence retains its original limited scope.
