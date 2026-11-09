# Windows personal-test installer

2026-11-10. User explicitly requested installer preparation after accepting the
single-window workflow, folder/name defaults, thirty-minute capture and bounded
rewind/Composite-loss tests. This permits a personal-test Setup; it does not
declare all original cross-platform requirements qualified.

## Artifacts and validation

Local output: `build/package-0.1.0-test02/`:

- `C039Recorder-0.1.0-win-x64-Setup.exe` (per-user Inno Setup installer).
- `C039Recorder-portable.zip` (same application without installation).
- `portable/C039Recorder/C039Recorder.exe`, build manifest, packaged notices/source.
- Setup SHA-256: `29B608E91F62164115A78CAD650839E765A350598CE8BC264BD0DEA29D332C36`.
- ZIP SHA-256: `7D328368815682EAD88FBE3DFD5AB24F55CB051772F4A96F6CD03515F4CB93B1`.

The artifact was built from the `e08e318` base plus this packaging stage's working
tree. The bundled C039 source ZIP retains the actual stage sources, not merely
the base commit. Development experiments in test01 are not the delivered artifact.

56 automated Python tests pass. Frozen EXE self-test passed from a different
working directory with empty PATH and deliberately unavailable PYTHONHOME/PYTHONPATH:
Tk/Pillow rendering, capture DLL load, native profile listing, MPEG-2/MP2 encode,
full synthetic decode, BWDIF and read-only MI_01 registry observations. This test
opens neither USB nor an audio device and is not a hardware-capture qualification.
Evidence: `build/package-self-test-frozen02.json`.

Actual Setup installation into a new workspace folder containing spaces,
installed self-test, same-version reinstall and uninstall all returned zero.
Before/after snapshots of parent/MI_00/MI_01 service/class/driver/config values,
user preferences and a retained recording hash were equal. The installed EXE
was removed; user recordings/preferences were retained. No existing C039 install
was replaced. Evidence: `build/installer-qualification-02/`. This is a reinstall
test, not qualification of every future version upgrade/downgrade.

The user's running development viewer was left open throughout. HTTP health was
200 after packaging/tests. No second USB owner was started. Physical video/audio
capture from the frozen/installed EXE remains pending a user-controlled viewer
handoff. Do not start that EXE normally alongside the current viewer.

## Distribution behavior

The bundle contains Python 3.13, Tk/Tcl, Pillow 12.3.0, C039 native binaries,
libusb 1.0.30 and the same FFmpeg/ffprobe 5.1.2 essentials build used in hardware
qualification. No system Python, FFmpeg, codec or SDK is required at runtime.
Frozen component resolution fails closed instead of using system PATH. HTTP logs,
application logs, private manifests and preferences use LOCALAPPDATA/C039Recorder;
first-use recording fallback is the user's Videos/C039 Recordings folder.

Setup installs under LOCALAPPDATA/Programs/C039 Recorder without elevation and
registers Start-menu/uninstall entries. Stable AppId supports same-product updates.
The packaged app holds a named mutex; Setup will not automatically close/restart
it. Post-install launch is unchecked and silent installs never launch capture.
Startup never automatically records. Uninstall has no user-data deletion action.

Setup reads MI_01 service registration to explain the WinUSB prerequisite. This
is not physical-presence detection or proof that an exclusive capture open will
succeed. Device-status self-test additionally checks the discovery GUID. Neither
path changes a driver. Parent, MI_00, certificates and security settings are untouched.

Universal signed driver provisioning/backup/restore is still unfinished. The
existing machine-specific maintenance utility is deliberately not shipped or
invoked by Setup. Original AVerMedia driver packages are not removed; their tested
restore procedure remains a separate explicit maintenance action. This installer
is currently suitable for this already provisioned MI_01 configuration, not an
unattended fresh-machine driver migration.

## Rebuilding

Build native components with tools/build_windows.py first. Use a separate venv:

```powershell
python -m venv build/package-venv
build/package-venv/Scripts/python.exe -m pip install pyinstaller==6.22.0 Pillow==12.3.0
build/package-venv/Scripts/python.exe tools/build_windows_package.py `
  --ffmpeg-dir ABSOLUTE_QUALIFIED_FFMPEG_ROOT `
  --libusb-source build/libusb-1.0.30-source.tar.gz `
  --libusb-license build/libusb-COPYING.txt `
  --output build/NEW_UNIQUE_OUTPUT --iscc ABSOLUTE_ISCC_EXE
```

Output must be new; the builder never recursively deletes previous builds/media.
Builder used PyInstaller 6.22.0 and official Inno Setup 6.7.4. The downloaded Inno
installer was Authenticode-valid with publisher Pyrsys B.V.; no signing settings
were changed. Build log and component hashes are retained with the artifacts.

Installed/frozen self-test (safe alongside a viewer):

```powershell
C039Recorder.exe --self-test --report ABSOLUTE_REPORT_PATH.json
```

No external download occurs during installation or self-test. Do not replace
the system FFmpeg or install drivers as part of these checks.

## Remaining release work

This is an unsigned, personal local test build, not a public release. A signing
certificate was not provided; no signature/security bypass is included. Windows
10, clean second-PC execution, physical NTSC, multi-hour capture, universal driver
provisioning/recovery and macOS regression remain unqualified. The removed external
OBS/VLC/FFmpeg client-validation stage is not reinstated.

Packaged notices include project, Python, Tcl/Tk, Pillow, PyInstaller, libusb and
the supplied FFmpeg license. C039 and libusb source archives are included. The
third-party FFmpeg build enables GPL/version3 components; its full corresponding
FFmpeg/dependency source and final distribution notices must be assembled before
public binary distribution. No public release/upload was performed here.

Build references: [PyInstaller runtime paths](https://pyinstaller.org/en/stable/runtime-information.html),
[Inno per-user installation](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm),
[Inno application closure](https://jrsoftware.org/ishelp/topic_setup_closeapplications.htm),
[official Inno downloads](https://jrsoftware.org/isdl.php),
[FFmpeg licensing/source checklist](https://ffmpeg.org/legal.html).
