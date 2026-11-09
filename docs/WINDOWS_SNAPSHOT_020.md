# Windows 0.2.0 working snapshot — 2026-11-10

This snapshot freezes the current working implementation, not completion of all
hardware/platform qualification. Branch: feature/windows-support; main untouched.

The single-window application provides resizable/fullscreen 4:3 video with
preview-only deinterlacing and sound, manual/Auto standards, media-only recording
folders, remembered folder/container, timestamp filenames and manual Record/Stop.
A shared native WinUSB owner feeds preview, archives and existing HTTP endpoints.
Compatible PAL/SECAM transitions retain one timestamp-aware TS/MPG encoder/file;
true native raster/rate changes explicitly roll to a new part. Archives preserve
source timing/interlacing and report missing/incomplete source data.

Current evidence: 69 software tests; frozen no-USB component/PTS self-test; full
physical PAL-60 decode and source-PTS/sample reconciliation (1,639 pictures,
54.69 seconds). One unlocated incomplete pair prevents an unconditional source
continuity pass. See WINDOWS_PAL60_QUALIFICATION.md. Earlier 30-minute/recovery
checks belong to earlier recording implementations, not long-run 0.2.0 proof.

Rebuild output: build/package-0.2.0-snapshot01. This new build is made from a clean
committed source revision, recorded in its build-manifest.json, and includes
Setup.exe, a portable ZIP and source/license/provenance materials. SHA256SUMS.txt
and validation evidence accompany local artifacts. Do not include private device
logs or recordings in git. Publish the source branch; binary release upload is
separate and remains gated on full corresponding stock-FFmpeg/dependency source
and notices. No binary release is created by this stage.

Setup remains an unsigned per-user offline evaluation installer. It installs
components/shortcuts, supports upgrade/uninstall, preserves user media/preferences,
and never auto-records or mutates drivers/security. Already provisioned MI_01
WinUSB is required; no universal driver provisioning or automatic original-driver
restore is claimed. The existing original-driver maintenance experiment is local.

Pending: physical 0.2.0 PAL/SECAM transition/recovery regression, genuine NTSC3.58,
long 0.2.0 capture, calibrated analog lip-sync/field dominance, Windows 10 and clean
second PC, macOS runtime regression, distribution source completeness/signing and
universal signed driver provisioning. External OBS/VLC qualification stays removed.


## Final local artifacts and checks

Built from clean source commit `530d83dd05de07817a7d567a493d7b1f3f1f1038`.
69 Python tests passed; native AV/frame/control tests passed; portable ZIP CRC
passed. Frozen self-test with empty PATH/unavailable Python passed. Isolated
Setup installation, installed self-test and uninstall each returned zero; no
USB/audio device was opened, no capture auto-started. Test uninstall removed the
isolated executable; the retained user media SHA-256 remained unchanged.

Local artifacts under `build/package-0.2.0-snapshot01/`:
- `C039Recorder-0.2.0-win-x64-Setup.exe`, SHA-256
  `9c19318dea5dcedc961b1c2d56d987d40d2b5d4235b263c9b4f0fafa49810901`
- `C039Recorder-portable.zip`, SHA-256
  `86df2eb2115a26c08c8b5e5796763e87fbb8004585867d948c3c2592bc2c55b4`

Private build evidence: snapshot020-tests.log, package-0.2.0-snapshot01-build.log,
portable-self-test.json, installed-self-test.json, install-test.log,
uninstall-test.log, SHA256SUMS.txt and VALIDATION.txt. Source branch published at
https://github.com/zhegal/avermedia-c039/tree/feature/windows-support .
No binary assets, private recordings/diagnostics or driver packages uploaded.
No main merge, tag or GitHub Release created. The application remains closed.
