# Windows groundwork: evidence and limits

Date: 2026-11-09 (Europe/Kyiv). Baseline `2b8e72f`.
Branch `feature/windows-support`. No merge or push to main.

## Status

This stage implements a Windows x64 diagnostic executable and a minimal
libusb control-transfer adapter for `c039_transport`. It does **not** implement
Windows ISO capture. There is no tested Windows live video/audio/HTTP source.
The existing macOS transport, register sequencing and hardware Auto are intact.
Windows live capture fails explicitly rather than attempting the POSIX pipeline.

## Observed device and original drivers

Safe PnP inspection found the connected `07CA:C039`, revision `4001`, with:

| Windows function | Service | Installed package | Version |
|---|---|---|---|
| Composite parent | usbccgp | usb.inf (Microsoft) | 10.0.26100.9711 |
| MI_00 Dummy IR | no function service reported | oem50.inf / avpolfir_c039.inf | 10.2.64.126 |
| MI_01 Capture Card | AVerPola | oem13.inf / averpola_c039.inf | 10.2.64.126 |

The two vendor packages were exported successfully with `pnputil /export-driver`
to `D:\AverMedia\build\driver-backup`. Original INF, catalogs, SYS, DLL/AX and ROM
remain local and excluded from Git. This is a backup, not a tested restoration.
No driver package was installed/deleted, no binding changed and no register or
security setting changed. Local evidence: `build/pnp-before.json`.

The vendor INF registers DirectShow/KS video/audio/crossbar/tuner interfaces,
48 kHz stereo audio format and private property-set GUIDs. It contains
`EnableReportDetectedStandard`, `EnableVideoStdAutoDetect` and
`EnableICVideoStdAutoDetect` settings; **their names alone do not prove a usable
runtime Auto API**. No public raw-USB passthrough API was established by this
inspection. No private IOCTLs or registry modifications were attempted.
Existing vendor-driver capture is a possible compatibility route; it does not
meet the goal of independence from that driver without further work.

## Physical USB preflight

Built `build/c039-probe.exe --check` reported high speed (libusb speed enum 3),
one configuration and interfaces 0 through 6. Relevant descriptor entries:

| Data | Interface / alternate | Endpoint | Type | wMaxPacketSize | Bytes/service interval | bInterval |
|---|---|---|---|---|---|---|
| Video | 4 / 3 | 0x84 IN | ISO | 5060 (0x13c4) | 2892 | 1 |
| PCM | 3 / 1 | 0x83 IN | ISO | 28 | 28 | 1 |

These match the macOS transport's requested capacities; 2892 includes the
high-bandwidth multiplier. They establish descriptors, **not successful ISO
transfers or actual decoded media**. The tool does not select these alternates.

`libusb_open` returned `LIBUSB_ERROR_NOT_FOUND`; diagnostic exit code 3.
No handle was obtained, so no interface claims, control transfers or capture
were attempted. Full local descriptor output: `build/usb-preflight.txt`.
This is consistent with the current vendor binding, rather than evidence that
the physical device is absent. Do not automatically detach or replace drivers.

WinUSB is a viable candidate because Microsoft supports ISO APIs since Windows
8.1, requiring Winusb.sys. Direct scheduled WinUSB reads also expose a starting
bus frame; assess these before adopting a timestamp contract. libusb documents
WinUSB ISO support but does not supply the macOS callback's bus timestamp API.
Do not invent packet timestamps from callback arrival time.

Primary references consulted:

- [Microsoft: WinUSB ISO APIs and driver prerequisite](https://learn.microsoft.com/en-us/windows-hardware/drivers/usbcon/getting-set-up-to-use-windows-devices-usb)
- [libusb: supported Windows backends and limitations](https://github.com/libusb/libusb/wiki/Windows)
- [libusb 1.0.30 release](https://github.com/libusb/libusb/releases/tag/v1.0.30)

## Reproduce the build/tests

Development prerequisites only: Python 3.10+, an x64 MinGW-compatible C compiler
and an extracted official libusb Windows binary archive. No SDK/runtime or
compiler requirement has been imposed on eventual end users. This stage is
not a redistributable application or installer.

Validated here with portable Zig 0.15.2 and libusb 1.0.30, both under ignored
`build/`; no toolchain installation or PATH changes:

```powershell
python tools/build_windows.py --cc build/zig/zig-x86_64-windows-0.15.2/zig.exe --libusb build/libusb
.\build\c039-probe.exe --list-standards
.\build\c039-probe.exe --check
```

The build copies the x64 libusb DLL beside the executable and compiles the
shared frame decoder DLL. `--list-standards` reads the existing C profiles and
does not initialize libusb/open USB. `--check` reads descriptors and attempts
open/claim/release only. It cannot reset/detach/install drivers, select a
configuration/alternate or initialize AV. Other arguments exit 64.

Validation on this Windows 11 x64 host:

- Strict-warning x64 build passed. Assertions explicitly remain enabled under
  Zig optimization (`-UNDEBUG`); a first attempt caught its NDEBUG default.
- Existing C AV initialization fault-injection/rollback suite passed, including
  all nine manual profiles, Auto/audio and 4,139 injected transfer failures.
- Existing C frame decoder test passed.
- New mock control-adapter test passed: exact setup fields and byte count,
  short reads/writes, transport errors and rejected invalid buffers/sizes.
  Ambiguous libusb failures fail closed; they are not mapped to IOKit's special
  power-transaction reconciliation status.
- All 30 existing Python tests passed: BT.656/native fields, damaged fields,
  geometry families, strict timestamp gaps, audio alignment and HTTP queues,
  loopback media/status/health/slow-client behavior. No USB capture in tests.
- Local test transcript: `build/windows-tests.txt`. Existing pthread-based
  preview PCM concurrency test was not included in this Windows build.
- macOS hardware/build regression and Windows 10 execution were not available.

Downloaded archive SHA-256 (local development provenance, not a signature check):

- libusb-1.0.30.7z: `7fb1dfec805b97983763d7d0ae244320da12add1003d4249c96cc4d586398c79`
- zig-x86_64-windows-0.15.2.zip: `3a0ed1e8799a2f8ce2a6e6290a9ff22e6906f8227865911fb7ddedc3cc14cb0c`

## Approval boundary and recovery plan

The next hardware step needs explicit permission for a temporary WinUSB binding
experiment on the C039 capture function **MI_01**. Preserve the composite parent
and MI_00. First establish a Windows-accepted signed driver-package route and
review its actual affected function/associated-interface set. Do not install an
unsigned INF, disable signature enforcement, add a trust certificate or use a
filter driver as an implicit workaround. No binding command/package is included
in this stage, and approval is not assumed.

Before any approved experiment, verify the exported original package/catalogs,
stop all capture consumers and record current bindings again. After binding,
rerun descriptor/access diagnostics before AV writes. If grouped interfaces
3/4 or shared controls cannot be accessed, stop; do not replace the whole USB
parent silently. Restore the capture function to the exported signed original
AVerPola package using Windows driver selection and verify the PnP service,
version, DirectShow video/audio enumeration and a short original-driver capture.
Do not delete the original package from the driver store. Restoration remains
untested until an authorized binding experiment actually happens.

No Setup.exe or long capture has been created. See [remaining work](ROADMAP.md).

## Approved signed-driver experiment (2026-11-09)

The user subsequently authorized a temporary signed WinUSB transition for MI_01,
with original-driver recovery, preserving the parent, MI_00 and Windows security.
This supersedes the pending-approval paragraph above for this experiment.

Added `src/windows_driver.c`, built as `build/c039-driver.exe`. It is a separate,
explicit maintenance tool; capture and automated tests never invoke it. It
requires exactly one present `USB\VID_07CA&PID_C039&MI_01` and accepts only the
recorded AVerPola/WinUSB starting services. It verifies both installed INFs via
`SetupVerifyInfFileW` and checks exact INF model sections/hardware IDs. This
prototype pins rollback to this machine's `oem13.inf`, so it is not a universal
installer. No custom package, self-signed certificate or security bypass is used.

The Windows inbox `C:\Windows\INF\winusb.inf` verified against Microsoft's
OS catalog; WinUSB service version is 10.0.26100.9549. The original driver and
its exported backup verified against their signed AVerPola catalog. Exported
and installed AVerPola INF SHA-256 are identical. The original MI_01 hardware
and software registry keys were exported locally before the class transition.

Commands (mutation commands require the normal UAC elevation):

```powershell
.\build\c039-driver.exe --plan
Start-Process D:\AverMedia\build\c039-driver.exe -ArgumentList '--bind-winusb' -Verb RunAs
Start-Process D:\AverMedia\build\c039-driver.exe -ArgumentList '--restore-avermedia' -Verb RunAs
```

The tool changes only MI_01's setup class (Media / USBDevice), installs the
explicit catalog-verified driver using `DiInstallDevice`, and restarts only
that function. It registers application interface
`{DC5D64D5-1DDB-4B6F-80CB-3472927954AE}` under MI_01 Device Parameters for WinUSB
discovery; restoration removes that exact value without overwriting unrelated
registrations. It attempts the prior binding again if installation fails.
Setup-class transitions can regenerate driver software settings; the exported
registry snapshots are evidence/backup, not a promise of exact preference
restoration. No driver-store packages are deleted. No automatic reboot.

Observed and bounded results:

- An initial global-driver-list attempt returned error 0x57 before installation;
  PnP remained unchanged. The implemented path builds a device-associated driver
  node after the setup-class transition. An early nested GUID key mistake was
  corrected and its exact experimental value/empty key removed.
- WinUSB installation succeeded without reboot, problem code 0. Registration
  of the app interface and function restart made libusb open succeed.
- Interfaces 1 through 6, including PCM 3 and video 4, claim/release successfully.
  MI_00 was never rebound; preflight now explicitly skips its interface 0.
- Restoration to signed AVerPola succeeded without reboot. DirectShow video and
  onboard audio enumeration returned. A three-second, stream-copy-to-null check
  completed with 75 YUY2 frames at 720x576/25 and S16LE stereo PCM at 48 kHz.
  This is driver recovery evidence, not a lip-sync, signal-quality or long-run test.
- Rebinding to WinUSB after restoration succeeded. Current MI_01 is WinUSB.
- Parent and MI_00 service/INF/version/problem-code snapshots match exactly
  before and after. No trust-store, signature-policy, Secure Boot or other
  security-setting operations were performed.
- All 30 Python tests and the C fault-injection/frame/control tests passed again.
  Windows ISO transfers and AV initialization are still pending at this stage.

Local evidence: `driver-plan.txt`, `driver-bind.log`, `driver-restore.log`,
`usb-winusb-access.txt`, `restored-dshow-devices.txt`, `restored-dshow-short.txt`,
`pnp-pre-bind.json`, `pnp-restored.json`, `pnp-final-winusb.json` and
`windows-tests-binding.txt`, all under ignored `build/`.

API references: [DiInstallDevice](https://learn.microsoft.com/en-us/windows/win32/api/newdev/nf-newdev-diinstalldevice),
[INF catalog verification](https://learn.microsoft.com/en-us/windows/win32/api/setupapi/nf-setupapi-setupverifyinffilew),
[setup-class property changes](https://learn.microsoft.com/en-us/windows/win32/api/setupapi/nf-setupapi-setupdisetdeviceregistrypropertyw).

## Native ISO capture and requested preview (2026-11-09)

`src/capture_windows.c` implements the existing `capture_device.h` session API
against WinUSB, selected only by the Windows build. Associated-interface IDs and
idle alternates are checked before hardware writes. Video interface 4/alt 3 and
PCM interface 3/alt 1 are selected **before** registering any ISO buffers.
Thirty-two bounded 64-packet buffers per stream give 256 ms scheduling headroom.
Both endpoints start at the same future USB frame, and each read explicitly
specifies its start frame with `WinUsb_ReadIsochPipe`. The returned next frame
must match the requested 8 ms span. Packet timestamps use scheduled frame plus
microframe*125 us, not application wake-up time; a 64-bit schedule extends the
32-bit Windows frame counter. This is USB delivery alignment, not a measurement
of internal analog A/V latency.

Every packet status, length and buffer offset is checked. A USB error or rejected
consumer callback ends capture explicitly. Stop closes admission, restores the
endpoint mask and drains already scheduled reads without resubmitting. All
streams unregister before **any** associated alternate is restored. The bounded
drain retains buffers/handles on timeout rather than freeing live I/O memory.
Bridge TS-mode/endpoint readback and the shared AV register journal verify
restoration; cleanup errors return 2. No USB reset or driver operation occurs
in capture. `CancelIoEx`/`AbortPipe` were experimentally found to invalidate ISO
registrations on this host; normal stop instead waits out the bounded schedule.

AVerPola leaves the bridge fully powered (0x78) after its stop. The default
shared initialization guard still refuses that state for all existing callers.
The Windows transport opts into a new already-powered-idle path only after an
exclusive device open and zero alternate checks; the shared engine also verifies
an idle endpoint mask. It preserves the original power state instead of cycling
it. Unknown partial power states and active endpoints still fail before writes.
882 injected transfer failures exercise this path in addition to the original
4,139-case coverage. The optional signal-status callback separates decoder
detected format/lock from selected profile; existing macOS callers need not use
it, and their initialization behavior remains unchanged.

Raw diagnostic (new prefixes only, 1-60 seconds and a checked disk budget):

```powershell
.\build\c039-probe.exe --capture auto build/captures/example --seconds 3
python tools/prepare_capture.py --audit-only build/captures/example
```

The diagnostic writes payloads, per-packet CSV and `.result.json`. It refuses
overwrite. Nonzero, interrupted or malformed result metadata prevents the
offline preparation tool from qualifying a partial capture as successful.
Manual formats are accepted through the shared profile table. Auto starts at
576/25; an incompatible 625/50 to 525/59.94 geometry change ends this fixed-format
raw diagnostic explicitly. No silent resize/frame-rate change. Longer/disk-bound
archive encoding belongs to the subsequent streaming stage, not this raw CLI.

Physical Windows evidence, all bounded:

| Check | Result / scope |
|---|---|
| 3-second Auto raw run | 375 transfers and 24,000 packets per endpoint; zero packet errors; cleanup/rollback verified |
| 3-second offline audit | 74 complete 720x576 frames; zero short lines/internal timing gaps; 143,996 source stereo PCM samples |
| 30-second Auto raw run | 3,750 transfers and 240,000 packets per endpoint; zero packet errors; cleanup/rollback verified |
| 30-second offline audit | 749 complete frames; frame deltas 39.875-40.125 ms; 1,440,012 source stereo samples; estimated video-span drift -0.625 ms |
| Stop during active capture | Native API stop after 1.2 s; scheduled drain, zero packet errors, register/alternate restoration and success return |
| Injected consumer failure | Failure at the 2,000th video callback propagates as result 1; bounded drain and rollback succeed |
| Reuse after stop/failure | Later finite capture succeeds without rebinding/reopening another USB owner |
| Software | Strict-warning builds; C parser/control/AV tests, added powered-idle/signal-status cases and all 31 Python tests pass |

Initial/final incomplete fields are discarded, not filled. The 30-second run
discarded one initial pair; temporal field dominance, motion cadence and analog
lip-sync remain uncalibrated. No long-run, unplug or Windows 10 qualification is
claimed. The two failed startup/cleanup experiments were retained and are not
included as successful captures. Evidence is local under `build/captures/`:
`winusb-auto-01` through `04`, `winusb-tape-auto-30s`, `smoke-cancel-02` and
`smoke-sink-failure`, plus `build/python-tests-iso.txt` and
`build/test-av-init-iso.txt`. Test media is retained.

The user additionally requested a visible preview while changing the tape:

```powershell
python tools/preview_windows.py --standard auto
```

The Tk window owns one C session via `src/windows_native.py` and
`build/c039-capture.dll`; it does not launch another capture tool. Complete
interlaced UYVY frames are converted to RGB for display only. Horizontal display
aspect correction shows 4:3; the source is never deinterlaced or modified.
Two queued raw frames and one queued RGB image bound display memory. Replaced
images count as preview drops and do not represent or conceal archival loss.
Missing complete fields retain the last picture with a waiting status. The
window shows detected standard and H/V lock, separately from the selected Auto
mode. PCM is captured but this diagnostic viewer does not play it yet.

Observed during the ongoing physical preview: PAL->SECAM->PAL->SECAM profile
events in the same native session (one pair of ISO setup lines, no restart),
followed by visible color SECAM picture and lock. The earlier PAL observation
had severe disturbances and waiting intervals; this does not qualify general
PAL/SECAM picture quality or archived transitions. Native and Python parsers
are software-equivalent in tests; user acceptance and broader tape conditions
remain separate. The preview has no archival recording controls. Close it before
starting an independent raw diagnostic: USB remains exclusively owned.

Local preview logs: `build/preview-windows.log` and `.err.log`. Startup was checked
visually with the computer-use skill. Windows live MPEG-TS/HTTP integration
remains pending, so `CaptureStream.run` still refuses that unsupported path.

Timing API reference: [scheduled ISO read and returned frame semantics](https://learn.microsoft.com/en-us/windows/win32/api/winusb/nf-winusb-winusb_readisochpipe).

## Persistent video + sound requirement and correction (2026-11-09)

The user requested sound to inspect sync, rejected desktop-automation overlays,
then reported viewer exits during rewind and at a normal micro-transition. The
standing requirement is now explicit: **only manual Stop/Close ends the logical
viewer session; every supported standard/native family must play in that window**.

An intermediate NUT/FFplay monitor was unsuitable as the default viewer. Its
fixed-format encoder stopped after four seconds without complete fields, and
another run stopped on a hardware Auto report of 480/29.97. It also encountered
one ISO completion error 31. The failures were not concealed: diagnostics retain
those return codes. The user initially heard audio with no noticeable sync offset
in the NUT path, but this does not qualify the replacement monitor's latency.
That intermediate tool was removed; it is not the default viewer.

Current default command remains `python tools/preview_windows.py --standard auto`.
It now launches `preview_windows_direct.py` and `windows_preview.PreviewCapture`:

- One persistent Tk window and one native USB owner. No FFplay/encoder container
  sits between capture and the window. A temporary RGB converter failure or a
  decoder format change cannot automatically close the logical session.
- Hardware Auto handles all nine profiles. Native 720x576/25 and
  720x480/30000:1001 are shown explicitly; only RGB display conversion is rebuilt
  on family changes. PAL/SECAM transitions retain USB. Explicit manual profile
  Apply may restart a native epoch while retaining the logical window.
- PreviewDecoder alone can display useful rows from incomplete field pairs,
  preserving known field rows and retaining prior rows where data is missing.
  Partial pictures and display drops are counted. Strict `bt656.Decoder` and the
  native archival frame parser keep their existing complete-field rules.
- PCM is independent of complete video. The monitor uses a bounded set of twelve
  20 ms Windows waveOut buffers, stereo S16LE/48 kHz, with 120 ms startup headroom.
  Display scheduling maps video USB time into the PCM sample offset and follows
  `waveOutGetPosition`; it does not play sound in an unrelated second player.
  Empty PCM packets receive counted silence **only in the monitor**. Source audio
  sample counts remain separate. No source resampling or archived audio repair.
- Native callbacks may deliver one validated 64-packet batch per 8 ms rather
  than 16,000 Python crossings/second. The default per-packet C callback API and
  macOS transport are preserved. Batches retain every packet's length/offset and
  scheduled timestamp; they are not a lower-rate timestamp approximation.
- A completed, failed ISO request is now distinguished from failure to drain or
  restore its resources. Source errors remain errors; confirmed-clean failures
  can start a new native epoch with a visible recovery counter. An unconfirmed
  cleanup does not trigger a blind reopen. The window remains open awaiting
  user action rather than claiming uninterrupted archival capture.
- User Stop waits for the native drain before destroying decoder/audio state.
  Closing the renderer is never an implicit source Stop. The user must manually
  end an active viewer before a developer reload; no desktop automation is used.

Physical evidence for this replacement is limited: the user replayed the
previously problematic tape fragment and reported **no exit this time**. Live
logs show multiple PAL/SECAM events without another ISO setup. An actual NTSC
source and regional variants have not been qualified, despite native-format and
all-profile software coverage. Continuous image/audio quality, precise A/V
offset, display latency, unplug recovery and long-run reliability remain open.

Software checks now pass **42 Python tests**, plus the C control/frame/AV tests:
native 480/576 field equivalence; preview-only damaged fields; bounded repeated
field memory; all-profile viewer geometry events without session closure; PCM
delivery without a single complete video frame; real named-pipe exact delivery,
absent/stalled reader deadlines; synthetic MPEG-2/MP2 full decode, five retained
frames, interlace flags, 48 kHz stereo/256 kbit/s; strict gap rejection, explicitly
counted viewing concealment and geometry-family refusal for fixed encoder parts.
A silent local waveOut smoke check advanced its sample clock and released its
buffers. It did not open USB and is not an A/V calibration test.

The Windows `CaptureStream` transport edge is implemented using local overlapped
named pipes and the existing FFmpeg command construction; its target bitrate is
now selectable from 8 through 12 Mbit/s. PCM starts at the video USB epoch and is
trimmed to admitted picture duration without resampling; source counts and clock
drift remain visible in Windows status. The existing HTTP broker/server is reused,
but **physical HTTP/multiple-client and strict recording qualification are still
pending**. It must subscribe to the persistent source before being integrated
with the user's live viewer; never create a second USB owner. A fixed-geometry
encoder's deliberate failure must not become the viewer lifecycle again.

Evidence: `build/preview-av-first-failure.stream.log`,
`build/preview-av-rewind-failure.stream.log`, `build/preview-av-03.err.log`,
`build/preview-direct.err.log`, `build/python-tests-persistent-preview.txt` and
retained synthetic files in `build/windows-stream-tests/`. These failed prototype
runs do not count as successful capture qualification. No recording/test media
was deleted. No additional driver/security changes were made.

Audio APIs: [waveOut position and supported clock units](https://learn.microsoft.com/en-us/windows/win32/api/mmeapi/nf-mmeapi-waveoutgetposition),
[waveOut PCM device open](https://learn.microsoft.com/en-us/windows/win32/api/mmeapi/nf-mmeapi-waveoutopen).

## Recording output folder (2026-11-09)
New Windows strict recordings keep only media in the selected output folder. Logs and session manifests live under LOCALAPPDATA/C039Recorder/Diagnostics in unique private directories. Existing sidecars/media are retained. Success and source-gap failure regression tests assert a media-only output directory; these are synthetic, not new hardware qualification. The running preview must be closed manually before loading this change.


## Shared Windows HTTP and recording stage (2026-11-09)

Implemented one persistent native source with bounded subscriptions for preview,
HTTP and strict recording. HTTP reuses the existing broker and loopback endpoints;
encoder parts mark geometry/epoch discontinuities without closing the viewer.
Recording can remain armed across source breaks and resume in separate numbered
media files; manual Stop disarms it. Failed parts and gap diagnostics are retained.
Only media is written to the chosen output folder; private logs/manifests are under
LOCALAPPDATA/C039Recorder/Diagnostics. Existing user sidecars are not deleted.
The viewer adds a selectable/copyable URL, resizable 4:3/fullscreen display and
optional preview-only BWDIF. MPEG-2 output signals DAR 4:3 without pixel resizing.
Pillow is now required for this developer viewer; portable packaging is pending.

Validation: 51 Python tests pass, including synthetic two-client HTTP, PAL/NTSC
encoder-part transitions, full strict-file decode, media-only success/failure
folders and auto-retry/manual-disarm control. No USB is opened by these tests.
A prior physical 3-second shared recording retained 74 pictures and passed the
then-current timing/count checks; its old DAR was 5:4, so it does not qualify the
new aspect fix. Updated viewer PID 23368 was launched only after user manual Close;
HTTP reported ready with native SECAM 720x576/25, one encoder part and no reported
encoder errors at the check. Visual/audio acceptance of this latest version,
physical multi-client/NTSC, long strict recording and Windows 10 remain pending.
No installer, driver/security change, second USB owner or desktop automation.
This section supersedes earlier statements that shared HTTP/recording were pending
implementation; earlier evidence retains its original limited scope.

## Thirty-minute hardware recording checked (2026-11-09)

One strict shared-source C039 VHS recording lasted 30m20s without closing preview,
source recovery or file rollover. Full decode retained 45,500/45,500 pictures;
87,360,000 admitted PCM samples plus 768 MP2 padding samples decoded. Video/audio
PTS, 4:3/interlace flags and independent FFmpeg error-stop decode passed. All
51 Python tests pass. Audio PTS/MP2-origin checks were added to the offline verifier.
User reported no noticeable preview A/V offset near the start and end. Source
clock drift is explicitly retained, not called perfect synchronization. See
[scope and evidence](WINDOWS_LONG_CAPTURE.md). Multi-hour, physical NTSC, controlled
disturbances, Windows 10, macOS regression and portable/installer work remain open.

## Rewind and signal-loss recovery checked (2026-11-09)

One physical tape-search event and one Composite RCA disconnect/reconnect triggered
explicit timestamp-gap part failures and automatic recording continuation. Three
retained parts fully decode with exact picture/sample checks; the first two remain
classified interrupted. Manual Stop disarmed retry. Viewer stayed open, source
recoveries remained zero; user confirmed picture/audio recovery after both events.
Offline verification adds explicit interrupted-part inspection without qualifying
failed recordings as continuous. All 51 tests pass. Evidence and limits:
[WINDOWS_DISTURBANCE_CAPTURE.md](WINDOWS_DISTURBANCE_CAPTURE.md). This supersedes
only the pending status of these two disturbance scenarios, not all error recovery,
physical NTSC, multi-hour, Windows 10, portable packaging or installer validation.

## Desktop workflow and recording defaults (2026-11-10)

Latest user scope: the existing single-window video/audio/record workflow is the
accepted direction. A separate OBS/VLC/FFmpeg client-validation stage is removed
from the plan; existing HTTP code is retained. Physical NTSC is deferred until a
known tape is available, not silently qualified and not the next user task.

Recording dialog now remembers the last recording folder and TS/MPG format in
LOCALAPPDATA/C039Recorder/recording-preferences.json, independently of media output.
Every opening proposes fresh local YYYY-MM-DD_HH-MM-SS.ts or .mpg. Selection is
saved after recording is armed; cancellation does not save, start recording or
create media. Existing exclusive-output collision protection remains in force.
Unavailable saved folders fall back to the existing default without recreating
the old folder. Settings errors do not stop an already started recording.
The user's latest private session seeds K:/VHS Recordings for the first updated
launch. Future choices persist automatically. No recording/preview is started by
preferences. 54 Python tests pass; native dialog acceptance remains pending until
the user manually closes the currently running old viewer for a reload.

## Personal-test installer prepared (2026-11-10)

User confirmed the last-folder/timestamp defaults in the actual dialog and then
explicitly requested installer preparation. Autonomous x64 portable/Setup artifacts
are built and hardware-free self-tested, including actual isolated installation,
same-version reinstall and uninstall. 56 Python tests pass; driver registry values,
preferences and retained media hash were unchanged. The active viewer was preserved.
See [WINDOWS_PACKAGING.md](WINDOWS_PACKAGING.md) for artifacts, exact evidence,
rebuild procedure and remaining gates. This is an unsigned local test installer for
an already configured WinUSB MI_01. Fresh-machine universal driver provisioning,
full original-driver recovery integration, installed-EXE hardware capture, clean
Windows 10/second-PC, multi-hour/NTSC and public source/signing readiness remain open.
This user-approved test-installer stage supersedes the earlier blanket Setup gate
only within this documented scope; it does not certify a final universal release.
