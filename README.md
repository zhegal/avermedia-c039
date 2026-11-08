# AVerMedia C039 capture for macOS

Experimental userspace capture for AVerMedia USB Polaris C039 on Apple Silicon.
USB ID: `07ca:c039`. Hardware decoder ID: `0x5a3e` (Conexant CX23102).

## Implemented

- Device discovery, descriptors and fixed register diagnostics through IOKit.
- AV power, AFE calibration, Composite input and line-audio initialization.
- Asynchronous isochronous video/audio capture on a shared USB bus timeline.
- PAL 720×576 UYVY, 25 frames/s, two fields preserved.
- Stereo signed 16-bit little-endian PCM at 48 kHz.
- Live video/audio preview through FFmpeg and ffplay.
- Offline frame assembly, USB timestamp alignment and MPEG-2/MP2 export.
- Checked control restoration on normal completion and SIGINT/SIGTERM.

No kernel extension, DriverKit component, firmware upload or EEPROM write.
The device does not currently appear as a system camera or audio input.

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

Capture duration is 1–3600 seconds. Additional audio attenuation is 0–48 dB;
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
| Lifecycle | Finite capture, preview SIGTERM, player exit, restart and control restoration tested |
| Software tests | 8 Python tests; 1,170 injected control-transfer failures; ASan/UBSan run passed |

Initial and final incomplete fields are discarded. Packet timestamps align
USB delivery, not the unmeasured internal analog video/audio latency.

## Limitations

- SECAM and NTSC-M settings exist but have no physical signal validation.
- S-Video input selection is not implemented.
- Temporal field dominance and analog lip-sync offset need a controlled test.
- Long-term clock-drift correction is not implemented.
- Hot unplug, sleep/wake and disk-full recovery are not validated.
- System camera/audio-device integration and direct OBS/VLC integration are absent.
- SIGKILL, power loss or a process crash may prevent control restoration.

During AV power-up, an OUT transaction can fail after applying the register
write. Only the known power-transition transaction error is reconciled, using
an exact successful readback. Other initialization errors stop the sequence.
Restoration verifies modified control bits; automatic AGC and calibration
result fields are not treated as immutable state.

## Source layout and license

- `src/av_init.c`: bounded AV/AFE/video/audio initialization and rollback.
- `src/iso_probe.c`: asynchronous ISO transport and packet timestamps.
- `src/probe.c`: device access and capture CLI; `--help` lists modes.
- `src/bt656.py`: SAV-only/SAV-EAV field assembly.
- `tools/`: preview, capture preparation and encoding.
- `tests/`: parser, timestamp alignment and initialization fault injection.

GPL-2.0-or-later, with individual MIT files identified by SPDX headers.
See [LICENSE](LICENSE), [NOTICE](NOTICE) and the
[upstream source manifest](references/linux-sources.json).
