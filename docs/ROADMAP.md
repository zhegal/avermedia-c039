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

## Continuous source-PTS recording implemented (2026-11-10, 0.2.0)

GUI recording now uses one timestamp-aware encoder/TS or MPG file through compatible
PAL/SECAM transitions, positive gaps and monotonic-clock native recovery. There is
no recovered-frame gate/raw pre-roll, no CFR repair or independent audio rebase.
Original USB-derived picture/PCM timing is transported through VHST0002; the donor
FFmpeg timing/PS patches are reused in a separate app-local build. 525/59.94 native
formats and explicit cross-family rollover are implemented. Source warnings remain
visible after Stop; full trace/decode verification distinguishes valid media from
unbroken source continuity. 69 software tests pass, including first recovered
picture pixel content, long gaps, variable PCM and 480/29.97 TFF/BFF.
See [WINDOWS_CONTINUOUS_RECORDING.md](WINDOWS_CONTINUOUS_RECORDING.md).
The user has an NTSC cassette and confirms it is playing; the old viewer reports
stable PAL-60 output with H/V/chroma lock. Do not keep deferring for lack of tape,
but do not call this genuine NTSC 3.58 or a new recording qualification. The active
old viewer was left open. Physical regression of 0.2.0 awaits manual user handoff.


## 0.2.0 physical PAL-60 short recording (2026-11-10)

User manually recorded/stopped and closed preview. Full offline verification of
54.69 seconds/1,639 pictures passed: every admitted picture and PCM sample retained,
source PTS preserved within mux quantization, MP2 priming/padding accounted for.
One incomplete source field pair has no location in aggregate diagnostics, so this
is not an unqualified source-continuity pass or calibrated analog sync/field order.
No internal video PTS gap/native error; PAL-60 output is not genuine NTSC3.58 proof.
See [WINDOWS_PAL60_QUALIFICATION.md](WINDOWS_PAL60_QUALIFICATION.md).
PAL/SECAM transitions and longer physical 0.2.0 checks remain pending.


## Working snapshot publication (2026-11-10)

0.2.0 source and local standalone Setup/portable snapshot: see
[WINDOWS_SNAPSHOT_020.md](WINDOWS_SNAPSHOT_020.md). User authorized publishing
feature/windows-support; no main merge and no public binary release.
