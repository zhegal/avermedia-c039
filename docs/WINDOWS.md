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
