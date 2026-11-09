# 0.1.1 failed physical regression and 0.1.2 rollback

2026-11-10, Europe/Kyiv. The user repeated the problematic tape transition in the
frozen 0.1.1 executable, PID 33872, while recording
`K:\VHS Recordings\2026-11-10_00-42-57.ts`. The user reports a larger interruption
than before and missing useful material at the beginning. This is a failed
physical regression; synthetic pre-roll/decode tests did not qualify the design.

## Observations

Session `c6457d714b8b4c34a2c08af15ef17523` retained three parts:

| Part | Pictures | Duration | End condition |
|---|---:|---:|---|
| 1 | 208 | 8.32 s | strict video timestamp gap |
| 2 | 57 | 2.28 s | native USB result 1 |
| 3 | 1393 | 55.72 s | user manual Stop |

A provisional candidate containing 2,614,528 raw bytes over about 112 ms was
rejected for lost frame/signal stability. No sub-second file was created, but
that narrow condition is not a successful outcome: the user lost useful material.
Explicit boundary gaps are 1.240001 s and 1.919875 s (approximately 3.16 s total).
These are retained-source boundary measurements, not proof of which missing
intervals contained useful analog content. Unrecorded content cannot be recovered
from the retained parts.

The owner recovered one native epoch while keeping the window open. The user
confirmed picture/audio returned. The session was manually stopped at 00:44:12
Kyiv time; the agent did not stop recording or the viewer. Full per-part ffprobe
verification and independent FFmpeg error-stop decodes passed for retained media
(208/57/1393 pictures, PCM/padding/PTS reconciliation). This does **not** qualify
uninterrupted recording or restore missing content. First two parts remain failed.

Evidence is retained under `build/retry011-hardware-01/`: session/status samples,
final manifests, per-part verification, decode logs and hashes. All user media
and original private diagnostics are preserved unchanged.

## Mitigation

0.1.2 restores recording_session.py, windows_shared.py and windows_recording.py
to the pre-buffered implementation from 91b3136: no two-second continuation gate,
raw pre-roll or replay burst. Automatic continuation again uses the earlier
three-complete-frame readiness guard. Short parts can recur; suppressing them
without sacrificing useful content is explicitly **unresolved**. Do not claim
the original short-fragment problem has been solved by this rollback.

The physical error's exact WinUSB cause is unknown. 0.1.1 only retained Python's
generic native_result=1; windowed Python redirection missed the DLL's C stderr.
No CPU/queue/signal hypothesis is stated as a confirmed cause. The packaged entry
point now redirects the DLL's own stderr before capture through a Windows-only
logging API. Python/C handles both append, avoiding mutual log overwrites.
This API only opens the private log, not USB; the register/ISO engine is unchanged.
Frozen self-test requires a native C marker in the resulting application log.

57 software tests pass, including a regression requiring the earlier fast
readiness and no provisional subscription. Experimental pre-roll tests are removed
with that path. The Windows DLL compiles with -Wall -Wextra -Werror. Native log
redirection is checked without opening USB. Hardware regression of 0.1.2 is still
pending a user-led viewer handoff. The currently open 0.1.1 viewer is not killed.

The 0.1.1 package is withdrawn for archival use. 0.1.2 is a mitigation/test build,
not a new final release; signing, universal driver provisioning and other release
limits continue to apply.

## 0.1.2 artifact/check record

Frozen hardware-free self-test passed with empty PATH/unavailable external Python,
including `native_c_log: true`; evidence: build/package-self-test-frozen012.json.
The three existing portable C regression executables returned zero. 57 Python
checks pass. No 0.1.2 live transition qualification is claimed. Installer
install/upgrade was not repeated while the user's frozen viewer holds AppMutex;
the earlier 0.1.0-to-0.1.1 installer validation is historical, not a new 0.1.2 pass.

Rollback Setup: build/package-0.1.2-test01/C039Recorder-0.1.2-win-x64-Setup.exe.
SHA-256: C2B6B388336D07F52FF66AD3E8E7DDFCD20F8F6872A3F48A6C9DBEA4479E08B0.
Portable: build/package-0.1.2-test01/C039Recorder-portable.zip.
SHA-256: 27951004DE8271DDEB771F6FAA5B3F12D2047BC297A3866264CD956C4723E253.
The legacy continuous-file comparison is in LEGACY_CAPTURE_COMPARISON.md; it
changes the next implementation direction, not the scope of this rollback.
