# AVerMedia C039 capture for macOS

Experimental userspace capture for AVerMedia USB Polaris C039 on Apple Silicon.
USB ID: `07ca:c039`. Hardware decoder ID: `0x5a3e` (Conexant CX23102).

## Implemented

- Device discovery, descriptors and fixed register diagnostics through IOKit.
- AV power, AFE calibration, Composite input and line-audio initialization.
- Asynchronous isochronous video/audio capture on a shared USB bus timeline.
- PAL/SECAM 720×576 UYVY, 25 frames/s, two fields preserved.
- Nine decoder format profiles, regional Composite aliases and full AFD Auto.
- Stereo signed 16-bit little-endian PCM at 48 kHz.
- Live NUT/MPEG-TS output to stdout or a new file; FFmpeg/ffplay preview.
- Local HTTP MPEG-TS source with independent, bounded client queues.
- Bounded queues and in-memory packet telemetry for indefinite streaming.
- Offline frame assembly, USB timestamp alignment and MPEG-2/MP2 export.
- Checked control restoration on normal completion and SIGINT/SIGTERM.

No kernel extension, DriverKit component, firmware upload or EEPROM write.
A native CoreMediaIO Camera Extension prototype is included separately.
It has not been activated: the current Personal Team cannot provision the
System Extension capability. C039 is not yet available as a system camera
or audio input on the test machine.

## Requirements

- macOS and Xcode developer tools with IOKit and IOUSBHost SDKs.
- Python 3.10 or later.
- FFmpeg and ffplay for preview and encoding.

Validated on macOS 27.0.1, Apple M4, arm64, Clang 21 and Python 3.12.
No libusb or additional Python packages are required.

## Build and test

```sh
make
make test
```

The default build produces `build/c039-probe` and an alternative IOUSBHost
register diagnostic, `build/c039-host-probe`. Tests do not access USB hardware.

## Live stream to FFmpeg

```sh
python3 tools/stream.py --seconds 60 | ffmpeg -n -f nut -i pipe:0 \
  -c:v ffv1 -c:a pcm_s16le capture.mkv
```

NUT carries uncompressed UYVY and stereo PCM. Only media is written to stdout;
diagnostics go to `build/stream.log`. `--seconds 0` streams until interrupted.
A slow or stalled output stops capture with an error instead of silently
dropping frames. Packet metadata uses bounded memory and FIFOs, not CSV files.
USB arrival alignment does not correct long-term drift or analog decoder latency.

Direct MPEG-2/MP2 recording, without intermediate payload files:

```sh
python3 tools/stream.py --seconds 60 --format mpegts --field-order tff \
  --output capture.ts
```

The field order is an explicit provisional choice. Existing output files are
refused.

## Local source for VLC, OBS and FFmpeg

Stop other capture tools, then start one shared source:

```sh
python3 tools/serve.py --standard auto --field-order tff
```

Open `http://127.0.0.1:8079/live.ts` in VLC using File → Open Network.
The same URL can be read by multiple clients. The server binds to loopback
only; at most eight clients are accepted. New clients receive the latest
keyframe with program tables. A slow client is disconnected independently.

Record the encoded video and audio without another encoding pass:

```sh
ffmpeg -n -i http://127.0.0.1:8079/live.ts -map 0:v:0 -map 0:a:0 -c copy capture.ts
```

For OBS, add a Media Source, disable Local File, enter the URL as Input and
use `mpegts` as Input Format. This uses OBS's FFmpeg source; no camera plugin
is required. See the [OBS source implementation](https://github.com/obsproject/obs-studio/blob/master/plugins/obs-ffmpeg/obs-ffmpeg-source.c).
VLC and FFmpeg were tested with the physical device; OBS itself has not been
tested on this machine.

`/status` reports JSON capture counters and errors; `/health` returns 200
when a keyframe is available and 503 otherwise. Diagnostics are written to
`build/serve.log`. Press Ctrl+C to stop and restore USB controls. Closing all
players leaves the source running. Use `--port` to change the port.

The HTTP source is intended for viewing: USB elapsed time determines viewing
cadence. Short gaps (up to 50 missing frames) repeat the last complete frame;
frames arriving before their next output slot are skipped. Both are counted
in `held_video_frames` and `dropped_video_frames`. Longer outages and USB errors
still stop capture. Add `--strict`
to reject all gaps, as the archival tools do by default. HTTP recording saves
the viewing stream, including any repeated frames. There is no deinterlacing
or scaling; field dominance and analog lip-sync remain uncalibrated.

For client testing without USB, use `--replay existing.ts`; it loops a recording
until interrupted. This mode does not open the capture device.

## Standards and VCR preview controls

The profile list follows Linux's CX25840 decoder and the standard names found
in the legacy AVerMedia C039 macOS driver. Regional RF differences do not
require different Composite/RCA decoder settings.

| Input setting | Native output | Physical validation |
|---|---|---|
| PAL-B/D/G/H/I (`pal`) | 720×576, 25 fps | PAL tested |
| PAL-N, PAL-Nc | 720×576, 25 fps | Pending |
| SECAM-B/D/G/H/K/K1/L/L1 (`secam`) | 720×576, 25 fps | SECAM tested |
| NTSC-M, NTSC-J, NTSC-4.43 | 720×480, 30000/1001 fps | Pending |
| PAL-M, PAL-60 | 720×480, 30000/1001 fps | Pending |

List exact command-line names without opening USB:

```sh
./build/c039-probe --list-standards
```

The legacy driver calls NTSC-4.43 `NTSC_433`; `ntsc-433` is an alias for
`ntsc-443`. Each manual profile is available to the capture and encoding tools.

```sh
python3 tools/preview_control.py --standard auto
```

The Tkinter panel selects Auto or any listed standard and displays the decoder's detected
format and synchronization status. A separate ffplay window shows video and
plays stereo RCA audio at 48 kHz, with an additional 6 dB attenuation.
Stop it before using another capture tool.

Auto continuously reads the decoder's AFD status and requires three stable
observations before updating chroma and native timing. It accepts all nine
reported decoder formats, including 625/50 ↔ 525/59.94 transitions. The panel
restarts its player when native height/frame rate changes. A real mixed-standard VCR tape was
confirmed by the user to display correct color in SECAM and after a running
SECAM→PAL transition. The reverse physical transition and all 525-line signals
still need validation.
The panel requires Tkinter; command-line streaming does not.

The panel's A/V preview corrects short timing disruptions for viewing and safely
restarts capture after a stream error. Strict live recording still stops on a
frame timestamp gap instead of hiding loss. `tools/preview_av.py --strict`
provides the same strict behavior in the standalone A/V preview.

Standalone NUT/MPEG-TS tools use a fixed pipe geometry per invocation. Auto
starts at 576/25 unless `--auto-geometry ntsc` is selected. These tools stop
on incompatible geometry; they do not rescale or transparently splice formats.
Native raw USB capture and the camera backend can change profiles in one run.

## System camera prototype

```sh
python3 tools/build_camera.py                 # compile only, unsigned
python3 tools/build_camera.py --team TEAM_ID --provision
```

The second command requires a suitable Apple Developer team; Xcode's Personal
Team does not support the System Extension capability. The script generates
an Xcode project under `build/` and builds `build/camera-products/C039 Camera.app`.
It does not install anything or change macOS security settings. Certificates,
team-specific project settings and provisioning profiles are not distributed.

With a valid signed build, install the app in `/Applications`, launch it and
select Activate Camera. Allow the camera extension in macOS settings when
prompted. The intended device name in capture lists is **AVerMedia C039**.
This is the [CoreMediaIO camera-extension mechanism](https://developer.apple.com/documentation/coremediaio/creating-a-camera-extension-with-core-media-i-o).

The extension links the existing C USB/initialization code directly; it does
not spawn Python, FFmpeg or other processes. USB starts with the first camera
stream and is restored after the last stream stops. UYVY buffers use IOSurface;
the native assembler preserves both fields. Auto advertises 576/25 and
480 at 30000/1001 formats and notifies clients when input geometry changes.
Client behavior during a live geometry change is not yet validated.

The native backend was tested separately against the physical PAL source:
149 full frames in 6 seconds, zero packet errors, USB controls restored.
That verifies the embedded capture path, not installation or application
compatibility. No end-to-end camera-list test has passed yet. The prototype
publishes video only; a paired CoreAudio RCA input remains to be implemented.
Camera output uses host-time cadence and may repeat frames during signal loss;
use strict raw/stream tools for auditing source continuity.

## Live preview

Connect a PAL Composite source and stereo RCA audio, then run:

```sh
python3 tools/preview_av.py --standard pal --seconds 600 --audio-attenuation-db 6
```

Close the player window or press Ctrl+C to stop. The preview uses FIFOs;
packet metadata is temporary. The default log is `build/preview-av.log`.
`tools/preview.py` provides a video-only preview.

Only one capture process may own the device. Stop preview before recording.

## Record and prepare

Use a new output prefix for each capture; existing payload files are refused.

```sh
mkdir -p captures
./build/c039-probe --seconds 60 --audio-attenuation-db 6 \
  --capture pal captures/test captures/test-configuration.bin \
  > captures/test.log 2>&1
python3 tools/prepare_capture.py --standard pal captures/test
```

Output:

- `.video.bin`, `.audio.s16le`: original USB payloads.
- `.packets.csv`: transfer status, byte offsets and USB bus timestamps.
- `.uyvy`: complete interlaced frames, without scaling or deinterlacing.
- `.aligned.s16le`: PCM trimmed to the USB arrival time of complete video frames.
- `.frames.json`, `.summary.json`: frame timestamps and continuity measurements.

Raw video needs approximately 20.8 MB/s. Frame assembly needs another copy of
the video. Use `--audit-only` to verify a capture without writing that copy:

```sh
python3 tools/prepare_capture.py --audit-only captures/test
```

Native capture duration is 0–3600 seconds; zero runs until a signal. Additional audio attenuation is 0–48 dB;
zero leaves the baseline line-input profile unchanged. Digital attenuation
does not recover clipping introduced upstream.

## MPEG-2 / MP2 export

```sh
python3 tools/encode_mpeg2.py --standard pal --field-order tff \
  --pixel-format uyvy422 captures/test.uyvy captures/test.aligned.s16le \
  captures/test.ts
```

Output is interlaced MPEG-2 4:2:2 with a 12 Mbit/s target and stereo MP2 at
256 kbit/s, 48 kHz. The target is not a CBR guarantee.
Field order must be explicit: `tff` above is provisional, not a validated
hardware result. Raw captures preserve both fields for later verification.

## Validation snapshot

Physical Composite PAL tests used a menu and moving video with RCA audio.

| Test | Result |
|---|---|
| Simultaneous capture | 10, 60 and 300 seconds completed |
| 300-second USB transport | 2,400,000 packets per endpoint; zero packet errors |
| 300-second video | 7,498 complete frames; no internal frame timestamp gaps |
| 300-second audio | 14,400,068 stereo samples; no full-scale samples at additional −6 dB |
| Video clock versus nominal 25 fps | Approximately −14.1 ms over 300 seconds |
| VCR auto mode | Correct SECAM color and continuous SECAM→PAL transition confirmed by user |
| Live pipeline | NUT→FFmpeg decode and direct MPEG-TS recording tested on hardware |
| HTTP clients | Live VLC picture; simultaneous FFmpeg decode, stream inspection and copy recording |
| Stream shutdown | SIGTERM, early reader exit and a stalled downstream tested; USB restored |
| Lifecycle | Finite capture, preview SIGTERM, player exit, restart and control restoration tested |
| Software tests | 30 Python tests; native parser tests; 4,139 injected control-transfer failures; C ASan/UBSan passed |

Initial and final incomplete fields are discarded. Packet timestamps align
USB delivery, not the unmeasured internal analog video/audio latency.

## Limitations

- NTSC variants and PAL-M/N/Nc/60 settings have no physical signal validation.
- SECAM color and SECAM→PAL auto switching were checked on a VCR; long timed
  packet/audio audits and PAL→SECAM transition validation remain outstanding.
- S-Video input selection is not implemented.
- Temporal field dominance and analog lip-sync offset need a controlled test.
- Long-term clock-drift correction is not implemented.
- Hot unplug, sleep/wake and disk-full recovery are not validated.
- Camera Extension compiles but activation is blocked by Personal Team provisioning;
  system enumeration, client capture and live geometry-change behavior remain unvalidated.
- A system RCA audio input is not implemented.
- OBS Media Source configuration is documented but not physically validated here.
- SIGKILL, power loss or a process crash may prevent control restoration.

During AV power-up, an OUT transaction can fail after applying the register
write. Only the known power-transition transaction error is reconciled, using
an exact successful readback. Other initialization errors stop the sequence.
Restoration verifies modified control bits; automatic AGC and calibration
result fields are not treated as immutable state.

## Source layout and license

- `src/av_init.c`: bounded AV/AFE/video/audio initialization and rollback.
- `src/capture_stream.py`: shared bounded streaming engine.
- `src/http_stream.py`, `tools/serve.py`: local MPEG-TS fanout service.
- `src/video_standard.c`: decoder profiles and regional Composite aliases.
- `src/capture_device.c`, `src/frame_decoder.c`: embeddable native camera backend.
- `camera/`, `tools/build_camera.py`: camera extension and activation app prototype.
- `src/iso_probe.c`: asynchronous ISO transport and packet timestamps.
- `src/probe.c`: device access and capture CLI; `--help` lists modes.
- `src/bt656.py`: SAV-only/SAV-EAV field assembly.
- `tools/`: preview, capture preparation and encoding.
- `tests/`: parser, timestamp alignment and initialization fault injection.

GPL-2.0-or-later, with individual MIT files identified by SPDX headers.
See [LICENSE](LICENSE), [NOTICE](NOTICE) and the
[upstream source manifest](references/linux-sources.json).
