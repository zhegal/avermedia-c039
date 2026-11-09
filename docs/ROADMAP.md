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
3. Native WinUSB ISO scheduling, common packet times, finite capture, cancellation
   and consumer-error drain implemented and short hardware-tested. Thirty-second
   raw audit: 749 complete frames, zero packet errors/internal frame gaps. See
   WINDOWS.md. Fault-injection/larger disturbance and multi-hour limits remain.
4. Shared AV/Auto connected, including an explicit already-powered-idle handoff
   from AVerPola. Default macOS power guard unchanged; 882 additional injected
   handoff errors tested. PAL/SECAM transitions observed in one live Windows
   preview session, as requested by the user. Raw diagnostics reject geometry
   family changes; native viewer accepts both heights. Physical 525-line inputs,
   field dominance, analog A/V sync and archival transition tests remain pending.
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
