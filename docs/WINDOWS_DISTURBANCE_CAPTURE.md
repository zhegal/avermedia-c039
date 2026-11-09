# Rewind and Composite signal-loss qualification

2026-11-09, Europe/Kyiv. Capture revision `24f8cac`, existing Windows 11 C039
WinUSB viewer, same USB owner PID 23368. No viewer restart, desktop automation,
second USB owner, driver/security changes or deletion of recordings.

## User-operated sequence

The user enabled automatic continuation and started
`K:\VHS Recordings\rewind-loss-01.ts` at 23:52:14.812 Kyiv time. After baseline
file growth and the armed state were confirmed, the user performed approximately
10–15 seconds of tape search/rewind and returned to playback. The user confirmed
the window stayed open and picture/audio returned. A strict timestamp-gap error
ended part 1; part 2 started automatically without another Record click.

The user then disconnected only the yellow Composite RCA for approximately
10–15 seconds and reconnected it. Two-second HTTP samples observed present/H-lock/
V-lock all zero from 23:53:42.919 through 23:53:52.959, then all one at 23:53:54.963.
Part 2 ended with a strict timestamp-gap error; part 3 started automatically.
The user confirmed picture/audio recovery, manually stopped recording at
23:54:27.073 and confirmed picture/audio still normal. The arm became false;
only three parts exist in this session. Preview/HTTP remained open and ready,
with zero source recoveries throughout the recorded samples and after stopping.

## Retained media and full verification

| File suffix | State | Pictures | Written PCM stereo samples | Decoded PCM | MP2 padding | Bytes |
|---|---|---:|---:|---:|---:|---:|
| `.ts` | Interrupted | 1201 | 2,305,920 | 2,306,304 | 384 | 76,245,468 |
| `.part0002.ts` | Interrupted | 1170 | 2,246,400 | 2,246,400 | 0 | 55,460,940 |
| `.part0003.ts` | Clean manual stop | 825 | 1,584,000 | 1,584,000 | 0 | 52,269,828 |

Every part passed full ffprobe frame decode, exact admitted/output/written/decoded
picture reconciliation, audio sample/padding and PTS checks, selected interlace
flags and native MPEG-2 720x576/25, 4:3, TFF / MP2 stereo 48 kHz 256 kbit/s profile.
All held/dropped archival-picture counters are zero. Independent full FFmpeg
decodes with `-xerror -err_detect explode` returned zero for all three files;
all three error logs are empty. No files or original manifests were rewritten.

The first two manifests retain return 1 and the original timestamp-gap error.
Their retained-media checks passed; they are **not** qualified as uninterrupted
archives. The third passes normal continuous-part verification. Explicit USB-time
gaps before parts 2 and 3 are approximately 3.685625 s and 0.349 s. These measure
the boundaries of retained parts, not the duration of missing physical input:
the bridge can continue delivering complete noise/free-running frames while
input lock is absent. Such source frames are distinct from application-inserted
held pictures. No claim is made that these files preserve unavailable signal.

Reported video USB-relative drift per part is -3.375 ms, +50.250 ms and -0.625 ms;
PCM drift is +29, +27 and +19 samples. In particular, the disturbed second part
is not evidence of exact source-clock preservation or calibrated analog sync.
The user's normal-picture/audio observation is qualitative, not a calibration.

## Evidence, verifier and limits

Local evidence remains in `build/disturbance-01/`: two-second session/HTTP/file-size
samples, final manifests, per-part decode logs, verification and SHA-256 results.
Private session directory is
`%LOCALAPPDATA%\C039Recorder\Diagnostics\Recordings\0196a1b513284157b6a5d3aae5aa581f`.
Only media files were created in the user's recording folder.

Offline verifier now accepts explicit `--inspect-interrupted` to check retained
media while returning `verified: false`, `continuity: interrupted` and original
source errors. Default verification still refuses failed recordings. A synthetic
regression verifies this distinction; all 51 Python tests pass without USB access.

Scope: one tape-search event and one Composite cable-loss event in a 625/50
session. This does not qualify every disturbance, USB unplug/replug, disk/encoder
failure, repeated stress, cross-family NTSC transitions, Windows 10, multi-hour
reliability or a future installer. The viewer was left open for the user.
