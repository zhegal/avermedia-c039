# Buffered recovery admission (0.1.1)

2026-11-10. User reported two closely spaced breaks during a tape-content change,
producing an unwanted sub-second continuation part. The private session
`9e419b1cb8ff4db5a211d4856a0ca6c8` confirms part 3 contained seven pictures
(0.28 s), failed with a timestamp gap, and was followed by part 4. Existing media
and original diagnostics have been preserved.

## Change

First manual Record still uses the existing readiness guard. After a part ends
and automatic continuation is armed, the Windows viewer now requires two seconds
of stable lock, unchanged native profile/epoch, fresh complete frames and one
unbroken complete-frame sequence before creating the next media file. Both elapsed
time and the appropriate native frame count are required; NTSC uses its profile
rate, not a hard-coded PAL frame count.

During that check, a provisional subscription buffers original USB video/PCM
batches from the existing source. It does not open USB. On admission, the same
subscription hands its buffered prefix, original bytes and bus timestamps to the
ordinary strict parser/encoder, then continues live without resubscribing. The
stable validation interval is therefore included in the recording, rather than
discarding the first two stable seconds or rebasing audio independently.

A short recovery followed by another partial sequence/lock loss, an epoch/profile
change or buffer exhaustion resets the candidate without creating a media file.
Losses delivered between supervisor polls are retained as invalidations. Commit
of a candidate is serialized with source publication: a subsequent break belongs
to normal strict capture, not to an asynchronously invalidated provisional buffer.

Provisional storage is bounded by 768 messages and 96 MiB of payload. Overflow
rejects the candidate and leaves the source/viewer alive. Only this provisional
subscription uses the larger queue; ordinary subscribers retain their old limit.
Manual Stop disarms continuation and releases the waiting subscription. Rejected
candidate counts, bounded rejection reasons/byte/time ranges and eventual file
gaps are explicit in private session metadata. Rejected unstable raw candidates
are not archival admissions and are not written as media. No existing recording
or test file is deleted. Preview/HTTP concealment never enters this buffer.

This is bounded hysteresis, not a promise to eliminate every short part: a genuine
new break after the two-second admission interval can still end a valid part.
Strict errors remain visible; no files are concatenated and gaps are not filled.

## Validation and delivery

60 Python tests pass without USB access. New checks reproduce the seven-frame
recovery, a partial sequence between polls, transient lock loss, payload-budget
exhaustion, one-subscription byte/timestamp replay, and the admission boundary.
A complete two-second synthetic prefix is fed through production named pipes and
MPEG-2/MP2 encoding, then fully decoded: all 50 pictures and 96,000 stereo PCM
samples are reconciled. This does not qualify physical NTSC or a real tape change.

Windows package version is now a validated build argument; 0.1.1 artifacts are
under `build/package-0.1.1-test01/`. Build manifests additionally record working-tree
state and the exact bundled C039 source-archive SHA-256. The 0.1.0 artifacts and
their historical qualification remain retained. Signing, driver provisioning and
other limitations in WINDOWS_PACKAGING.md continue to apply.

Physical regression on the reported tape transition remains pending a user-led
viewer handoff. The running development viewer has not been terminated/reloaded.

### 0.1.1 package evidence

Frozen self-test with empty PATH/unavailable external Python passed:
`build/package-self-test-frozen011.json`. Isolated installation of 0.1.0, upgrade
to 0.1.1 (registered version checked), installed self-test, 0.1.1 reinstall and
uninstall all returned zero. Driver registry snapshots, preferences and retained
media hash were unchanged; the active viewer stayed open. Evidence:
`build/installer-qualification-03/`. No installed-EXE hardware capture is claimed.

Setup: `build/package-0.1.1-test01/C039Recorder-0.1.1-win-x64-Setup.exe`.
SHA-256: `05BDC1338BA284F083F231F69AFCD75D7CF0EC302AE51C96A7D6129E40CA8C05`.
Portable: `build/package-0.1.1-test01/C039Recorder-portable.zip`.
SHA-256: `ECC2DD28DBCE8CA9AA24B17353FEEA397158EFE2430761718104CB0AB842183D`.
The manifest records base 91b3136 plus a dirty working tree and exact bundled
source-archive hash, so it does not pretend this binary came from the base alone.
