# Timestamp encoder sources

`vhsts.c` and `mpeg_pts.patch` are adapted/copied from the user's existing
`vhs-recorder-tool/tools/ffmpeg` implementation. The transport C file retains
its LGPL-2.1-or-later notice. The corresponding FFmpeg sources are LGPL-2.1-or-later.

The original VHST0001 header/reader remains supported. VHST0002 adds native UYVY,
720x576/25 and 720x480/(30000/1001), and explicit TFF/BFF. Both streams carry signed
100 ns timestamps with one shared origin; audio remains stereo S16LE 48 kHz.
No USB, driver or device-control code is present in these patches.

`tools/build_timestamp_ffmpeg.py` downloads/verifies the fixed FFmpeg 5.1.2 source
archive SHA-256, applies the MPEG-2 nominal-rate precision change and the reference
MPEG-PS per-picture PTS patch, registers this transport, and builds a separate
minimal Windows executable. MPEG-TS mux/demux support is included. The resulting
source archive, license, build provenance and application patch sources accompany
the package; no system or donor-repository FFmpeg is replaced.
