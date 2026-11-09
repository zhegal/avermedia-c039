# Windows support roadmap

Updated 2026-11-09. Work only on `feature/windows-support`; no main merge.

1. Architecture review, read-only device/driver diagnostics and minimal control
   transport: implemented; see [evidence](WINDOWS.md). This is groundwork, not
   completion of the requested Windows USB capture backend.
2. Signed USB access and restore round trip verified (2026-11-09), following
   explicit user approval: MI_01 uses Microsoft inbox WinUSB, interfaces 1-6
   open/claim; restoring AVerPola recovers DirectShow A/V and a 75-frame short
   capture. Parent and MI_00 unchanged. This is an explicit machine-specific
   maintenance experiment, not an installer or automatic binding in capture.
3. Implement Windows ISO scheduling for both EP84 video and EP83 PCM, bounded
   queues, per-packet errors, common bus timestamps, cancellation and drain.
   Descriptor layout on Windows must be checked rather than copied from IOKit.
   libusb completion time is insufficient evidence of USB packet time. Evaluate
   direct WinUSB scheduled ISO APIs before choosing the final timing contract.
4. Connect unchanged AV initialization and Auto. Validate same-family PAL/SECAM
   changes without restart. Publish events and fail or split explicit native
   parts across geometry/rate families. Never silently scale or change CFR.
5. Replace the POSIX transport edge in the Python pipeline; reuse the frame
   decoder, strict timing rules, MPEG-2/MP2 command construction and HTTP broker.
   Verify 8-12 Mbit/s MPEG-2, MP2 256 kbit/s, multiple clients, /status and /health.
6. Short physical captures first: packet errors, admitted/decoded frames, PCM
   samples, timestamps, fields and controlled A/V sync. Then disk-budgeted long
   captures and error injection. Retain all user/test media.
7. Only after Windows capture is confirmed, prepare signed-driver-aware x64
   Setup.exe with device/driver detection, app-local dependencies, update,
   uninstall and original-driver restoration. No security bypasses.

Each completed stage gets focused changes, documented evidence and its own
commit. macOS hardware regression requires a Mac and remains a separate check.
