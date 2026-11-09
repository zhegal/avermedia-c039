# Physical PAL-60 recording verification, 2026-11-10

User confirmed an NTSC cassette was playing. Decoder selected PAL-60; this is
not qualification of genuine NTSC 3.58. Version 0.2.0, package test03. User
manually started/stopped recording and closed preview. Verification was offline;
no viewer restart, USB open, driver change or media modification.

File: `K:\VHS Recordings\2026-11-10_01-48-35.ts`
Size: 75,736,928 bytes. SHA-256:
`f6405bb91a1a35a882cbbc99ebe9a36f0a19d48c7fca5a47cf3d6391b1c67b75`.
One file, no session breaks, source errors, native recoveries, packet gaps,
missing PCM packets, invalid field pairs or signal loss events.

Full ffprobe frame decode/reconciliation and independent FFmpeg full A/V decode
with -xerror -err_detect explode both passed (exit 0). All 1,639 admitted pictures
were written and decoded: 720x480, 30000/1001, 4:3, interlaced TFF flags. Nominal
picture duration 54.687967 seconds. Physical field dominance remains uncalibrated.
No inserted/held cadence-repair pictures.

All 2,626,591 source PCM stereo sample frames retained (54.720646 seconds).
MP2 stereo 48 kHz 256 kbit/s decodes 2,627,712 samples, including 1,121 final
padding samples (23.354 ms), within one MP2 frame. Verification accounts for
481 samples of encoder priming and one common mux translation (10.0249 ms).
Every video PTS matches source timing within 8.5 microseconds; every audio
codec-block PTS within 7.067 microseconds, below sample/mux quantization tolerance.
No evidence of independent audio rebase or accumulated encoder/mux sync drift.
Source video elapsed differs from nominal cadence by -5.475 ms over this short
run; source PCM clock/count by -0.646 ms. These are preserved source measurements,
not evidence of an analog lip-sync calibration or multi-hour stability.

Caveat: decoder counts one incomplete source field pair (without its location),
zero short lines, and a partial first field at manual Stop (118 lines). Admitted
picture PTS show no missing cadence interval. An initial partial pair is plausible,
but the aggregate counter cannot prove its location. Do not call the whole source
uninterrupted: verifier reports full_source_continuity=false. All complete admitted
pictures and samples were retained. No content-level speech/impact sync calibration
was performed; timestamp preservation does not establish absolute analog lip sync.

Evidence: build/continuous020-physical-verification.json,
build/continuous020-physical-source-summary.json; original private diagnostics
session d575cec1f9e54aaf91a76cb0c0fa99d7. The user recordings folder contains only
media. PAL/SECAM transition regression, true NTSC3.58 and longer new-path capture
remain pending. Existing 69 software tests were not repeated for this docs-only stage.
