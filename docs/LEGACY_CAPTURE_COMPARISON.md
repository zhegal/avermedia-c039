# Legacy continuous capture comparison

2026-11-10. User supplied six local reference scripts under `K:/VHS Recordings`:
capture.ps1, capture_laptop.ps1, capture-pal.ps1, capture-secam.ps1,
force-pal.ps1 and force-secam.ps1. They were read, not executed. The reference
`D:/vhs-recorder-tool` repository was inspected read-only; it was not modified.

## What the source actually establishes

- capture.ps1 opens the original AVerMedia DirectShow video/audio inputs and
  runs one FFmpeg process writing one MPEG-PS file through tee until manual exit.
  capture_laptop.ps1 uses a combined video/audio DirectShow input. Neither script
  contains application logic that ends the archive on a picture timestamp gap.
- The PAL/SECAM wrappers start the corresponding control script, then the same
  capture command. The control script polls decoder readback approximately every
  100 ms and reapplies PAL_B/SECAM_D if it differs. These are original-driver
  IAMAnalogVideoDecoder calls, not WinUSB access and not source-standard detection.
- The scripts alone do not establish whether AVerPola or FFmpeg repairs/repeats
  pictures at a transition. Do not invent such behavior from the fact the file
  stayed whole. The user's report of successful uninterrupted use remains evidence
  of the experienced workflow, not an independently measured per-picture trace.
- The later WPF implementation explicitly transports original shared A/V PTS
  through VHST v1 and a patched app-local FFmpeg. TimestampCaptureHub rejects
  backwards timestamps, not ordinary positive gaps. VhsArchiveCommandBuilder uses
  copyts, fps_mode passthrough, a 90 kHz encoder clock and vhs_pts for MPEG-PS.
  Same-family PAL/SECAM retains the recording task/file. See that repository's
  REPORT_STANDARD_TRANSITIONS.md and CAPTURE_TIMESTAMPS.md for dated evidence.

## Difference in this WinUSB prototype

windows_stream.py currently writes raw video and S16LE to separate pipes. The
encoder assigns frame/sample-counter time; there is no source-PTS input channel.
VideoCadence therefore deliberately throws on a picture gap to prevent silently
compressing missing time in an apparently continuous CFR archive. RecordingSession
responds by ending a part and restarting. That explains the designed file cuts;
it does not explain the separate native USB result 1 in the failed 0.1.1 test.

Changing the recovery delay cannot provide the desired uninterrupted archive.
Nor is enabling the lossy preview concealment path a valid archive fix.

## Required next implementation direction (not implemented yet)

For compatible 625/50 transitions, retain a single encoder/file, transmit each
complete original picture and PCM block with common-source timestamps, preserve
positive gaps explicitly, and keep monitoring/source ownership independent.
Backward/reset timestamps, queue overflow, disk errors and incompatible geometry
still require explicit handling, not silent success. No invented pictures,
independent audio rebasing, resampling or suppressed missing-content accounting.

The working WPF timing transport/FFmpeg patches are relevant reusable evidence.
They cannot be copied as a drop-in executable: its VHST header is restricted to
720x576 YUY2/TFF, while the WinUSB decoder produces UYVY and supports additional
profiles; that minimal FFmpeg build currently lacks MPEG-TS muxing. Pixel packing,
container support, source-epoch recovery, stop/drain and full positive-gap A/V
verification must be addressed before wiring a new continuous path into the UI.
Keep the original-driver-free WinUSB goal unless the user explicitly changes it.

0.1.2 is only rollback of the failed buffer plus native diagnostics. It does not
claim to implement the continuous timestamp path or solve short-part creation.
The user's latest clarification makes whole-file compatible transitions the
target; fragment suppression is not a substitute for that requirement.
