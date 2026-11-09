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

## Thirty-minute hardware recording checked (2026-11-09)

One strict shared-source C039 VHS recording lasted 30m20s without closing preview,
source recovery or file rollover. Full decode retained 45,500/45,500 pictures;
87,360,000 admitted PCM samples plus 768 MP2 padding samples decoded. Video/audio
PTS, 4:3/interlace flags and independent FFmpeg error-stop decode passed. All
51 Python tests pass. Audio PTS/MP2-origin checks were added to the offline verifier.
User reported no noticeable preview A/V offset near the start and end. Source
clock drift is explicitly retained, not called perfect synchronization. See
[scope and evidence](WINDOWS_LONG_CAPTURE.md). Multi-hour, physical NTSC, controlled
disturbances, Windows 10, macOS regression and portable/installer work remain open.

## Rewind and signal-loss recovery checked (2026-11-09)

One physical tape-search event and one Composite RCA disconnect/reconnect triggered
explicit timestamp-gap part failures and automatic recording continuation. Three
retained parts fully decode with exact picture/sample checks; the first two remain
classified interrupted. Manual Stop disarmed retry. Viewer stayed open, source
recoveries remained zero; user confirmed picture/audio recovery after both events.
Offline verification adds explicit interrupted-part inspection without qualifying
failed recordings as continuous. All 51 tests pass. Evidence and limits:
[WINDOWS_DISTURBANCE_CAPTURE.md](WINDOWS_DISTURBANCE_CAPTURE.md). This supersedes
only the pending status of these two disturbance scenarios, not all error recovery,
physical NTSC, multi-hour, Windows 10, portable packaging or installer validation.

## Desktop workflow and recording defaults (2026-11-10)

Latest user scope: the existing single-window video/audio/record workflow is the
accepted direction. A separate OBS/VLC/FFmpeg client-validation stage is removed
from the plan; existing HTTP code is retained. Physical NTSC is deferred until a
known tape is available, not silently qualified and not the next user task.

Recording dialog now remembers the last recording folder and TS/MPG format in
LOCALAPPDATA/C039Recorder/recording-preferences.json, independently of media output.
Every opening proposes fresh local YYYY-MM-DD_HH-MM-SS.ts or .mpg. Selection is
saved after recording is armed; cancellation does not save, start recording or
create media. Existing exclusive-output collision protection remains in force.
Unavailable saved folders fall back to the existing default without recreating
the old folder. Settings errors do not stop an already started recording.
The user's latest private session seeds K:/VHS Recordings for the first updated
launch. Future choices persist automatically. No recording/preview is started by
preferences. 54 Python tests pass; native dialog acceptance remains pending until
the user manually closes the currently running old viewer for a reload.

## Personal-test installer prepared (2026-11-10)

User confirmed the last-folder/timestamp defaults in the actual dialog and then
explicitly requested installer preparation. Autonomous x64 portable/Setup artifacts
are built and hardware-free self-tested, including actual isolated installation,
same-version reinstall and uninstall. 56 Python tests pass; driver registry values,
preferences and retained media hash were unchanged. The active viewer was preserved.
See [WINDOWS_PACKAGING.md](WINDOWS_PACKAGING.md) for artifacts, exact evidence,
rebuild procedure and remaining gates. This is an unsigned local test installer for
an already configured WinUSB MI_01. Fresh-machine universal driver provisioning,
full original-driver recovery integration, installed-EXE hardware capture, clean
Windows 10/second-PC, multi-hour/NTSC and public source/signing readiness remain open.
This user-approved test-installer stage supersedes the earlier blanket Setup gate
only within this documented scope; it does not certify a final universal release.

## Buffered retry stability (2026-11-10, 0.1.1)

User's tape-change report is confirmed by a seven-frame failed continuation part.
Auto-continuation now waits for two seconds of stable source/complete frames while
buffering original video/PCM, then replays that prefix into strict capture. Short
failed candidates create no media; their byte/time/rejection metadata remains
explicit. First manual Record, source ownership and existing recordings are
unchanged. 60 tests pass, including a fully decoded 50-picture/96,000-sample
pre-roll. Physical regression remains pending. See
[WINDOWS_RETRY_STABILITY.md](WINDOWS_RETRY_STABILITY.md). A later genuine break
still ends a part; the change never hides an admitted archival gap.

## 0.1.1 physical regression FAILED; 0.1.2 mitigation (2026-11-10)

The user reports a longer transition break and missing useful beginning with 0.1.1.
Logs confirm native result 1/recovery and gaps about 1.24/1.92 s. Retained parts
fully decode; this does not recover missing content or qualify the experiment.
Withdraw 0.1.1 for archival use. 0.1.2 restores pre-buffer continuation behavior,
removing the two-second gate/raw replay. Short fragments remain unresolved; prefer
preserving available material to cosmetic fragment suppression. A Windows-only
C-stderr logging hook fixes missing native diagnostics in frozen apps, without
opening USB or changing capture/register logic. 57 tests pass. The exact USB cause
and 0.1.2 physical regression remain pending; do not blame CPU without evidence.
See [WINDOWS_RECOVERY_REGRESSION.md](WINDOWS_RECOVERY_REGRESSION.md). No user files
were deleted/rewritten and no active viewer was terminated by the agent.

## Continuous-file reference clarified (2026-11-10)

User reports the earlier capture/force PAL/SECAM scripts and vhs-recorder-tool
kept one file through comparable transitions. Read-only source comparison confirms
the scripts do not end on timestamp gaps; the WPF path preserves positive source
PTS gaps through VHST. Our raw-pipe strict-cadence guard deliberately ends a part,
so fixing retry delay alone cannot meet that workflow. Target compatible 625/50
transitions with one timestamp-aware encoder/file, explicit gaps and no invented
pictures. This transport is not implemented yet. Reference constraints and reuse
limits: [LEGACY_CAPTURE_COMPARISON.md](LEGACY_CAPTURE_COMPARISON.md). Do not execute
those original-driver control scripts alongside the WinUSB viewer, change drivers,
or enable preview concealment for archives as a shortcut.
