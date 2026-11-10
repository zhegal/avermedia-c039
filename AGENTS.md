# C039 cross-platform development

Read `docs/PROJECT_CONTEXT.md`, `docs/ROADMAP.md` and `docs/WINDOWS.md` before
changes. Work in `D:\AverMedia` on `feature/windows-support`. Preserve macOS,
reuse shared C hardware logic and do not merge/push to main without permission.
Update dated evidence/context after a stage, run appropriate checks and commit
that stage only. Preserve user recordings and retained test media.

## Current user constraints (2026-11-09)

- A temporary signed WinUSB binding on C039 **MI_01 only** was explicitly approved
  and a restore/rebind round trip was tested. Do not change the composite parent,
  MI_00, trust stores, signature/security policy or install custom kernel drivers.
  `c039-driver.exe` is an explicit, machine-specific maintenance tool, not an
  installer; never invoke it from capture or automatic tests.
- The **logical preview session/window ends only when the user manually stops
  or closes it**. Micro-transitions, missing lock, rewind and changes between all
  supported 625/50 and 525/59.94 profiles must not close the viewer. Show actual
  native geometry/rate. Keep sound and restore image when source returns.
- Keep preview damage repair, repeated images and inserted monitor silence
  explicitly counted and isolated from strict archival data. Archive failures
  must not stop the shared source or viewer. Do not silently change an archive's
  geometry/frame rate or mask frame/PCM loss.
- The user wants visible **video plus sound** and no “ChatGPT is using your
  computer” overlay. Use normal local application windows and logs; do not use
  desktop automation/screenshots to inspect or operate their desktop.
- Do not terminate the running preview to rebuild/reload. The user ends that
  logical session manually. Never open a second USB owner while it is active.
- Do not create Setup.exe before the backend is qualified. Never pretend that
  software mocks, readback, a short capture or a roadmap proves hardware quality.

Build: `python tools/build_windows.py --cc <x64-compiler> --libusb <extracted-archive>`.
The hardware smoke tool runs only with explicit `--hardware`; automated tests
must not open USB. Windows 10, physical NTSC/regional formats, controlled A/V/field
calibration and long archival capture remain pending unless dated evidence says
otherwise. Source playback observed by the user is not an independent sync test.

Windows shared HTTP/strict recording now subscribe to the persistent native owner.
Keep diagnostics private (LOCALAPPDATA/C039Recorder/Diagnostics), media folders clean,
and numbered retries explicit; manual recording Stop disarms retry. Preview-only
BWDIF/scaling must never enter archive/HTTP encoding. See dated stage notes.

Thirty-minute physical recording evidence: docs/WINDOWS_LONG_CAPTURE.md.
Retain the user file and private evidence. Do not generalize this single 625/50
run to multi-hour/NTSC/recovery/Windows 10 acceptance or calibrated analog sync.

Bounded rewind/Composite-loss recovery evidence: docs/WINDOWS_DISTURBANCE_CAPTURE.md.
Interrupted-part inspection must preserve verified=false and original errors;
retained media decoding is not uninterrupted archival qualification.

Latest scope (2026-11-10): single-window preview/audio/record is accepted; do not
reinstate an OBS/VLC/FFmpeg validation stage. Physical NTSC is deferred for lack
of a known tape. Preserve last-folder/container preferences and fresh local
YYYY-MM-DD_HH-MM-SS recording defaults; no automatic recording on startup.

2026-11-10: user approved preparation of a personal-test installer after capture
checks and accepted dialog defaults. See docs/WINDOWS_PACKAGING.md. Test Setup
for already provisioned WinUSB is allowed; universal driver provisioning and
public/signing/source readiness remain pending. Never start installed capture
alongside the active development viewer. Frozen component paths must fail closed;
uninstall preserves recordings/preferences and never changes drivers.

0.1.1 retry admission: docs/WINDOWS_RETRY_STABILITY.md. Preserve the bounded
original-video/PCM pre-roll and the same subscription at admission. No hidden
trimming, frame repair or discarded stable validation interval in strict output.
Seven-frame tape-change recovery is software-tested; physical regression pending.

0.1.1 buffered recovery FAILED physical regression: docs/WINDOWS_RECOVERY_REGRESSION.md.
0.1.2 rolls back the 2-second gate/raw replay; this supersedes the preceding
pre-roll preservation instruction. Short fragments remain unresolved. Preserve
useful content and all failure evidence; do not call retained-media decode a
successful transition. Native C diagnostics must reach the windowed app log.

User clarified continuous same-family recordings from legacy scripts/WPF are
the target: docs/LEGACY_CAPTURE_COMPARISON.md. Retry delay is not the solution.
A future timestamp-aware path must preserve positive A/V gaps without concealment;
0.1.2 is only rollback/diagnostics, not that implementation.

0.2.0 continuous recording: docs/WINDOWS_CONTINUOUS_RECORDING.md. GUI archives
use original USB-derived PTS and one file through compatible PAL/SECAM, not
fixed-cadence failure/restart. Preserve positive gaps, all admitted samples,
no frame repair/raw pre-roll. Geometry changes still require a native new part.
User has an NTSC cassette; current old-viewer output is PAL-60. Physical 0.2.0
checks are pending a manual handoff, not lack of tape. Do not close the viewer.

0.2.0 short physical PAL-60 evidence: docs/WINDOWS_PAL60_QUALIFICATION.md.
Full media/source-PTS reconciliation passed; one unlocated incomplete source pair
prevents unconditional continuity qualification. Analog lip sync/field dominance
remain uncalibrated. User stopped recording and closed preview manually.

2026-11-10 user authorized publishing feature/windows-support and a working
local 0.2.0 snapshot: docs/WINDOWS_SNAPSHOT_020.md. No main merge. Source branch
publication is separate from public binary distribution readiness.

Open future VHS transition/recovery issue: docs/WINDOWS_VHS_TRANSITIONS.md.
User requested tracking only; do not implement from roadmap alone or promise
software TBC/reconstruction of data not delivered by C039.
