# Open issue: unstable VHS transitions without external time-base correction

Recorded 2026-11-10 at the user's request. Status: future investigation/fix,
not implemented or hardware-qualified by this documentation stage.

## Problem and existing evidence

The user's Panasonic NV-HV60 playback chain can produce unstable signal at tape
recording boundaries, including PAL/SECAM changes and temporary loss of lock.
Earlier 0.1.1 tests caused short fragments and loss of useful recovered beginning;
see WINDOWS_RECOVERY_REGRESSION.md. The 0.2.0 continuous source-PTS path removes
software readiness delays and keeps compatible PAL/SECAM in one file, but its
physical regression at the reported transition remains pending. The short PAL-60
check is not a transition qualification (WINDOWS_PAL60_QUALIFICATION.md).

Objective: retain all recoverable picture fields and PCM through disturbances,
keep the viewer/session alive, and avoid unnecessary archive interruption or
additional loss of the useful recovered beginning. Do not promise full software
TBC: the application receives decoded C039 video/PCM, not the original analog/RF
waveform, and cannot reconstruct image data never delivered by the device.

## Future investigation

- Reproduce the same problematic transition with user-controlled playback.
- Correlate lock/standard observations, native transfer results, USB packet timing,
  decoder line/field boundaries and archive admission/written PTS. Distinguish
  analog decoder lock loss, USB failure and application field-assembly rejection.
- Localize incomplete pairs and the first complete recovered picture; aggregate
  dropped-pair counters alone cannot establish where source information was lost.
- Investigate documented CX23102 synchronization/Auto settings only if evidence
  identifies a concrete benefit. No speculative register changes or invented TBC.
- Improve recovery/field assembly only where delivered data supports it. Preserve
  original timestamps, field order, samples and independent audio/video timing.

## Acceptance and limits

Repeat a known PAL/SECAM transition and temporary signal loss in a physical capture.
For compatible geometry/rate, the viewer stays open and archive remains one file;
first complete recoverable picture is retained without a software stabilization
wait. All admitted pictures/samples reconcile with full offline decode and original
PTS; real missing data and recovery intervals remain explicit. No repeated/fake
archive frames, inserted silence, hidden resampling, scaling or timestamp flattening.
True 625/50 versus 525/59.94 changes still require explicit native-format rollover.
If hardware cannot supply complete data, document the residual limitation and the
potential need for upstream hardware correction rather than declaring it fixed.
Do not equate timestamp preservation with calibrated analog lip sync.

This entry authorizes tracking the issue, not starting hardware tests, changing
drivers/device settings or implementing additional processing. Current build stays
unchanged; any future implementation follows a separate user task.
