# Windows support roadmap

Updated 2026-11-09. Work only on `feature/windows-support`; no main merge.

1. Architecture review, read-only device/driver diagnostics and minimal control
   transport: implemented; see [evidence](WINDOWS.md). This is groundwork, not
   completion of the requested Windows USB capture backend.
2. Signed USB access and restore round trip verified (2026-11-09), following
   explicit user approval: MI_01 uses Microsoft inbox WinUSB, interfaces 1-6
   open/claim; restoring AVerPola recovers DirectShow A/V and a 75-frame short
   capture. Parent and MI_00 unchanged. This is an explicit machine-specific
   maintenance experiment, not an installer or automatic binding in capture.
3. Native WinUSB ISO scheduling, common packet times, finite capture, cancellation
   and consumer-error drain implemented and short hardware-tested. Thirty-second
   raw audit: 749 complete frames, zero packet errors/internal frame gaps. See
   WINDOWS.md. Fault-injection/larger disturbance and multi-hour limits remain.
4. Shared AV/Auto connected, including an explicit already-powered-idle handoff
   from AVerPola. Default macOS power guard unchanged; 882 additional injected
   handoff errors tested. PAL/SECAM transitions observed in one live Windows
   preview session, as requested by the user. Raw diagnostics reject geometry
   family changes; native viewer accepts both heights. Physical 525-line inputs,
   field dominance, analog A/V sync and archival transition tests remain pending.
5. Replace the POSIX transport edge in the Python pipeline; reuse the frame
   decoder, strict timing rules, MPEG-2/MP2 command construction and HTTP broker.
   Verify 8-12 Mbit/s MPEG-2, MP2 256 kbit/s, multiple clients, /status and /health.
   Windows named-pipe/mux transport is now implemented and software-tested.
   Persistent native-format video+PCM preview is separate, by explicit user
   requirement. NEXT: subscribe HTTP/recording consumers to that single source;
   encoder/geometry/gap failures must not close the viewer or reopen USB.
6. Short physical captures first: packet errors, admitted/decoded frames, PCM
   samples, timestamps, fields and controlled A/V sync. Then disk-budgeted long
   captures and error injection. Retain all user/test media.
7. Only after Windows capture is confirmed, prepare signed-driver-aware x64
   Setup.exe with device/driver detection, app-local dependencies, update,
   uninstall and original-driver restoration. No security bypasses.

Each completed stage gets focused changes, documented evidence and its own
commit. macOS hardware regression requires a Mac and remains a separate check.

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
