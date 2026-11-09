# Continuous original-timestamp recording (0.2.0)

2026-11-10. Explicit user task: one file through compatible PAL/SECAM transitions,
original A/V timing and no software loss of the useful recovered beginning. Keep
the current preview open. The user also found and is playing an NTSC cassette.

## Implemented path

The Windows viewer's RecordingSession now selects original-USB-PTS recording.
First Record subscribes as soon as a native profile is known, including while
lock is absent. Same-raster PAL/SECAM observations, temporary signal loss, positive
timestamp gaps and recoverable native epochs do not close the file or encoder.
There is no three-frame readiness gate at a recovered transition, no two-second
raw pre-roll and no replay burst. The same bounded source subscription remains
attached throughout. No second USB owner is opened.

```text
existing WinUSB owner -> bounded immutable-batch subscription
 -> strict original-field decoder + original PCM blocks + USB-derived PTS
 -> one bounded timestamp-packet pipe -> one timestamp-aware MPEG-2/MP2 encoder
 -> one TS or MPG file
```

`windows_timed.py` reuses the platform-independent BT.656 Decoder and PacketWindow.
It emits only full observed field pairs, preserves their byte order and selected
interlace flags, and retains original PCM without async resampling or per-stream
rebasing. Missing/invalid source packets, incomplete pairs and signal/epoch events
are explicit metadata, not fabricated pictures, held archival frames or monitor
silence. Field-phase jitter is retained; pairs spanning more than a whole nominal
frame are rejected as incomplete/mismatched source, with an explicit event.

Compatible 625/50 PAL/SECAM stays in one encoder/file. A true native geometry/rate
change (576/25 <-> 480/(30000/1001)) explicitly ends the old part and automatically
continues a new native-format file in the same user session/folder. There is no
scaling or hidden format conversion. Backwards/reset source PTS, output/disk
failure or queue exhaustion still fail explicitly. A native restart can continue
the file only while the observed common source clock remains monotonic; no clock
reset is concealed with a made-up time mapping.

Manual Stop closes this consumer's admission under the publication lock, drains
the offered prefix, finishes the encoder at EOF and checks admitted/written counts.
It does not stop preview/audio/USB. Input/output/finalization waits are bounded;
only this recording's encoder may be terminated on its own timeout. Already
accepted PCM is not truncated to a generated video-frame-count duration. Partial
MP2 blocks reach the encoder for normal codec padding.

## Timestamp and codec contract

The device does not supply DirectShow sample timestamps in this backend. Source
PTS are derived from the existing scheduled USB bus/microframe times and the
observed field-marker offsets; callback-arrival/wall time is not used. Representation
is signed 100 ns ticks, not a claim of 100 ns physical measurement accuracy.
One shared origin is carried for video and PCM, then the container/codec may apply
one common translation. Video output uses a 90 kHz encoder/mux clock and preserves
each admitted picture's source PTS rather than reconstructing a CFR timeline.
Nominal raster/rate metadata remains 720x576/25 or 720x480/(30000/1001), 4:3.

Transport is a backwards-compatible VHST0002 extension of the donor project's
VHST0001: native UYVY, both rasters/rates, and explicit TFF/BFF. The app-local
FFmpeg 5.1.2 build reuses the donor's MPEG-2 precision and MPEG-PS per-picture PTS
fixes and adds MPEG-TS support. It is built separately under build/timestamp-ffmpeg;
neither system FFmpeg nor D:/vhs-recorder-tool was modified.

Encoder flags retain 8–12 Mbit/s target MPEG-2 4:2:2, interlaced DCT/ME,
alternate scan and no B frames; low_delay avoids retaining early pictures through
a long source gap. TS includes video PES lengths; PS uses the reference vhs_pts
access-unit patch. There is no deinterlacing, spatial resizing or color enhancement
in the archive path. Existing preview rendering/HTTP encoding are separate.

PCM remains stereo 16-bit 48 kHz; encoding is MP2 256 kbit/s. MP2 uses 1152-sample
(24 ms) codec blocks, initial encoder delay and final padding. A gap falling inside
a codec block cannot be represented with independent timestamps for every sample
inside that block. The verifier reconciles all samples and the original timestamp
of each block's first contributing sample; this is not a claim of analog sample-
accurate lip-sync across a cut. PTS tolerances account for 48 kHz sample and 90 kHz
mux quantization, not arbitrary drift, gap compression or inserted silence.

## Diagnostics and full verification

Only TS/MPG media goes into the chosen recording folder. Private manifests and
timeline.jsonl retain every admitted picture's PTS, duration and second-field PTS,
every admitted PCM block's PTS/sample count, source events and final parser state.
Collection occurs on the subscription worker, outside native USB callbacks.
Writer buffering is limited to 256 messages and 64 MiB; source queue limit remains
128 batches. Overflow explicitly fails the archive while leaving the owner alive.

Source-warning counts remain visible during recording and after Stop. Full decode
success is separate from source continuity: a valid one-file archive may faithfully
contain source gaps, and its report explicitly says full_source_continuity=false.
Signal loss is reported even if the bridge keeps producing full free-running images.
Native C diagnostics are unbuffered in the windowed application's private log.

The existing offline verifier detects the new time_policy and delegates to
verify_timed_recording.py. It fully decodes, reconciles trace/admitted/written/
decoded pictures and PCM/padding, checks raster/rate/DAR/field flags, and compares
every picture PTS and audio codec-block PTS with the source trace. It rejects an
artificially flattened source timeline. Arming before the first image is supported
by probing to the first known source-picture time, while still decoding the full file.
Legacy fixed-cadence recordings retain their original verification path.

## Evidence and limits

69 automated Python tests pass, with no physical USB opened. Added scenarios:

- TS and MPG retain all pictures/samples through PAL/SECAM-style loss of video
  while USB/PCM continues, including 1.2-second and 15-second gaps.
- The first recovered picture's PTS **and decoded pixel content of both fields**
  match the first new input picture; no old-frame substitution/readiness delay.
- A recoverable native end/epoch keeps recording and retains the first complete
  new picture. An old unfinished pair without its closing boundary is explicitly
  unadmitted; no missing source data is reconstructed.
- Synthetic 720x480/(30000/1001), TS/MPG and both selected field orders.
- True cross-family source changes roll to a new native file; manual Stop leaves
  the source open and drains already offered data.
- Variable PCM packet sizes, loss of lock with complete device frames, backwards
  PTS rejection and rejection of a flattened verification fixture.

Local evidence: build/continuous-tests-verified.log, build/timed-tests-content.log,
retained build/timed-tests and build/timed-rollover-tests media/manifests/traces.
These are synthetic tests, not a new physical capture pass.

During development the old 0.1.1 viewer stayed open; the user's NTSC cassette
eventually produced stable decoder-selected/detected PAL-60, 720x480 at 30000/1001,
with H/V/chroma lock. Evidence: build/ntsc-tape-user-confirmed-old-viewer.json.
This is a source/preview observation in the old version, not new 0.2.0 recording
qualification or proof of genuine NTSC 3.58 output. Tape availability is no longer
the blocker; source output mode must be distinguished from the cassette label.

Physical PAL/SECAM transition regression, native-source error diagnosis, 0.2.0
525-line recording, multi-hour qualification, calibrated analog sync/field
dominance, Windows 10/second-PC and macOS regression remain pending. No active
viewer was killed/reloaded; the next hardware check needs a user-controlled handoff.
The default macOS implementation and shared hardware/register logic are unchanged.

## Packaged validation

Local test build: `build/package-0.2.0-test03` (Setup and portable ZIP).
Frozen self-test passed with empty PATH, invalid Python environment variables and
an unrelated working directory: bundled native logging, original-PTS gap
encode/decode and preview BWDIF succeeded without opening USB or an audio device
or changing a driver. Evidence: `build/package-self-test-frozen020-final.json`.
The native DLL also compiled with warnings treated as errors.

SHA-256:
- Setup: `DFF343FFAA3209306F772E86D88A9DB536F30A86CA71FD59F4B30E4558C71E1C`
- Portable: `9574B110A7C7B64D847C4202B8CB046B646C33F99AD664874E74D2DD62096C5E`

This is an unsigned local evaluation build. Installation/upgrade of 0.2.0 was
not exercised while the user's active 0.1.1 viewer holds the application mutex.
The running viewer was left untouched; loading the new implementation requires
the user to stop recording and close that viewer manually when ready.


## 0.2.0 physical PAL-60 short recording (2026-11-10)

User manually recorded/stopped and closed preview. Full offline verification of
54.69 seconds/1,639 pictures passed: every admitted picture and PCM sample retained,
source PTS preserved within mux quantization, MP2 priming/padding accounted for.
One incomplete source field pair has no location in aggregate diagnostics, so this
is not an unqualified source-continuity pass or calibrated analog sync/field order.
No internal video PTS gap/native error; PAL-60 output is not genuine NTSC3.58 proof.
See [WINDOWS_PAL60_QUALIFICATION.md](WINDOWS_PAL60_QUALIFICATION.md).
PAL/SECAM transitions and longer physical 0.2.0 checks remain pending.
