# Thirty-minute shared-source qualification

Date: 2026-11-09, Europe/Kyiv. Capture code: `5a35ad2`, Windows 11 x64,
MI_01 WinUSB, physical C039 and playing VHS. No driver/security changes.

## Procedure and retained evidence

The user started strict recording from the existing viewer and manually stopped
only recording after thirty minutes. The viewer was never closed or restarted;
no second USB owner was opened. Source monitoring ran every approximately ten
seconds, outside USB callbacks. Recording was armed for source-break continuation,
but no break occurred, so this run does not qualify automatic recovery.

- Start: 23:14:58; finalized: 23:45:18 Kyiv time. Media duration: 1820 seconds.
- File: `K:\VHS Recordings\test111.ts`, 2,873,103,044 bytes. Initial K: free space
  exceeded 1.17 TB, well above the approximately 3.2 GB bounded-test budget.
- SHA-256: `ECAA9E3382839697479F0ACCE7768A0830A10C0CE2F01C7D7B05104EA81AC668`.
- Private session: `%LOCALAPPDATA%\C039Recorder\Diagnostics\Recordings\8e7b859d7422432b8d9e8888206cba89`.
- Local evidence: `build/qualification-30min-01/`: final session/part manifests,
  169 resource/status samples, verification JSON, independent decode result/log,
  FFmpeg version and SHA-256. No diagnostics were written beside the user's media.
- Development FFmpeg: 5.1.2 essentials build, gyan.dev. Portable distribution is
  still pending; this test does not validate a future bundled build.

## Results

The final strict manifest reports native and mux exit 0, no errors/pipe errors,
one recording part, 45,500 admitted/output/written pictures, zero held/dropped
archival pictures and 14,560,192 USB packets per endpoint. The strict parser's
packet and picture cadence checks remained active throughout. Encoded video is
MPEG-2 720x576, 25/1, 4:3, interlaced TFF; target bitrate 12 Mbit/s. Preview BWDIF
and display scaling are separate from this encoded media.

Full `ffprobe -show_frames -err_detect explode` decode retained exactly 45,500
pictures and verified every picture's interlace/order flags and timestamp cadence.
Audio is MP2 stereo 48 kHz, 256 kbit/s. Written PCM: 87,360,000 stereo samples;
decoded: 87,360,768, with 768 samples of final MP2 padding. Every audio block's PTS
matches cumulative sample time. Measured initial MP2 delay: 481.056 samples,
within 90 kHz mux quantization of the qualified 481-sample delay.

An independent full FFmpeg decode of both streams with `-xerror -err_detect
explode`, two decoder threads and null output returned 0; its error log is empty.
No source media was modified or deleted. The verifier now checks audio PTS and
priming as well as the existing picture/sample reconciliation; an injected audio
PTS error is rejected. All 51 Python tests pass without USB access.

Clock measurements are retained, not described as perfect clock lock: final video
USB-relative drift is -33,625 us; PCM USB-relative drift is +1,048 samples
(21.833 ms). These are separate source-clock observations, not calibrated analog
lip-sync measurements. The user reported no noticeable preview A/V offset near
both the beginning and end. Subjective playback of the completed file remains
separate from these numerical checks.

The monitored Python owner used 164.8–188.0 MiB working set and 104.0–130.5 MiB
private memory, with 966–1035 handles. These figures cover the owner process only,
not total encoder/process-tree resources. Post-recording HTTP status remained
ready with the logical viewer open and zero native-source recoveries.

## Limits

This is one approximately thirty-minute 625/50 tape run. It qualifies neither
multi-hour operation, physical NTSC/regional standards, deliberate disruptions,
disk/USB failure recovery, Windows 10, macOS regressions nor an installer.
Decoder PAL/SECAM observations do not independently establish tape color standard.
Encoded TFF flags do not calibrate physical temporal field dominance. No automatic
repeat recording or broader roadmap stage is authorized by this report.
