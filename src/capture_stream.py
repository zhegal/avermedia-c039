# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded C039 capture pipeline shared by CLI outputs and preview clients."""
from collections import deque
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import queue
import select
import shutil
import subprocess
import tempfile
import threading
import time

from bt656 import Decoder

ROOT = Path(__file__).resolve().parents[1]


class StreamError(RuntimeError):
    pass


class PacketWindow:
    """Recent nonempty packets; no disk growth during indefinite capture."""
    def __init__(self, limit=32768):
        self.rows = deque(maxlen=limit)
        self.changed = threading.Condition()
        self.finished = False
        self.packets = 0

    def add(self, line):
        if line.startswith(b'bus_frame,') or not line:
            return
        values = line.split(b',')
        if len(values) != 6:
            raise StreamError('malformed packet telemetry')
        bus, micro, transfer, status, length, offset = values
        if int(status, 16) not in (0, 0xe00002e7) or int(transfer, 16) not in (0, 0xe00002e7):
            raise StreamError('USB packet or transfer error; stream is discontinuous')
        row = (int(offset), int(length), int(bus) * 1000 + int(micro) * 125)
        with self.changed:
            self.packets += 1
            if row[1]:
                self.rows.append(row)
            self.changed.notify_all()

    def close(self):
        with self.changed:
            self.finished = True
            self.changed.notify_all()

    def lookup(self, target, by_time=False):
        deadline = time.monotonic() + .5
        with self.changed:
            while True:
                if self.rows:
                    first, last = self.rows[0], self.rows[-1]
                    earliest = first[2] if by_time else first[0]
                    if target < earliest:
                        raise StreamError('required timestamp fell outside bounded telemetry window')
                    latest = last[2] + 125 if by_time else last[0] + last[1]
                    if target < latest:
                        for row in reversed(self.rows):
                            if (row[2] if by_time else row[0]) <= target:
                                return row
                left = deadline - time.monotonic()
                if self.finished or left <= 0:
                    raise StreamError('packet timestamp unavailable')
                self.changed.wait(min(left, .05))

    def byte_time(self, offset):
        start, length, stamp = self.lookup(offset)
        if offset >= start + length:
            raise StreamError('byte falls in missing packet data')
        return stamp + (offset - start) * 125 / length

    def audio_offset(self, stamp):
        offset, length, start = self.lookup(stamp, by_time=True)
        return offset + min(length, max(0, round((stamp - start) * .048) * 4))


@dataclass
class StreamStats:
    video_frames: int = 0
    audio_bytes: int = 0
    audio_skip_samples: int = 0
    video_packets: int = 0
    audio_packets: int = 0
    native_exit: int | None = None
    mux_exit: int | None = None


class CaptureStream:
    def __init__(self, *, standard='pal', seconds=0, attenuation=6,
                 container='nut', field_order=None):
        if standard not in ('pal', 'secam', 'ntsc') or not 0 <= seconds <= 3600:
            raise ValueError('invalid standard or duration')
        if not 0 <= attenuation <= 48 or container not in ('nut', 'mpegts'):
            raise ValueError('invalid attenuation or container')
        if field_order not in (None, 'tff', 'bff') or (container == 'mpegts' and field_order is None):
            raise ValueError('MPEG-TS requires explicit tff/bff field order')
        self.standard, self.seconds, self.attenuation = standard, seconds, attenuation
        self.container, self.field_order = container, field_order
        self.stopping = threading.Event()
        self.requested_stop = False
        self.errors = []
        self.stats = StreamStats()
        self.native = self.mux = None

    def stop(self):
        self.requested_stop = True
        self.stopping.set()

    def fail(self, error):
        self.errors.append(str(error))
        self.stopping.set()

    def mux_command(self, video_fd, audio_fd):
        height, rate = (480, '30000/1001') if self.standard == 'ntsc' else (576, '25')
        cmd = ['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'warning',
               '-thread_queue_size', '32', '-f', 'rawvideo', '-pixel_format', 'uyvy422',
               '-video_size', f'720x{height}', '-framerate', rate, '-probesize', '32',
               '-analyzeduration', '0', '-i', f'pipe:{video_fd}',
               '-thread_queue_size', '128', '-f', 's16le', '-ar', '48000', '-ac', '2',
               '-probesize', '32', '-analyzeduration', '0', '-i', f'pipe:{audio_fd}',
               '-map', '0:v:0', '-map', '1:a:0']
        if self.field_order:
            cmd += ['-vf', f'setfield={self.field_order}']
        if self.container == 'nut':
            cmd += ['-c:v', 'rawvideo', '-threads:v', '1', '-c:a', 'pcm_s16le']
        else:
            cmd += ['-c:v', 'mpeg2video', '-pix_fmt', 'yuv422p', '-b:v', '12M',
                    '-flags', '+ilme+ildct', '-alternate_scan', '1', '-g', '12', '-bf', '0',
                    '-c:a', 'mp2', '-b:a', '256k', '-mpegts_flags', '+pat_pmt_at_frames',
                    '-muxdelay', '0', '-muxpreload', '0']
        return cmd + ['-flush_packets', '1', '-f', self.container, 'pipe:1']

    def run(self, output, log_path, *, allow_disconnect=False):
        if not shutil.which('ffmpeg') or not (ROOT / 'build/c039-probe').is_file():
            raise StreamError('build/c039-probe and ffmpeg are required; run make first')
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        threads, fds, pipe_fds = [], [], []
        windows = [PacketWindow(), PacketWindow()]
        # Allow format probing/encoder startup without blocking the USB reader.
        # Still bounded: at most 64 raw frames (~53 MB) and 256 PCM chunks.
        queues = [queue.Queue(maxsize=64), queue.Queue(maxsize=256)]
        aligned = threading.Event()
        first_stamp = []

        with tempfile.TemporaryDirectory(prefix='c039-stream-') as temp, log_path.open('w') as log:
            prefix = Path(temp) / 'capture'
            paths = [str(prefix) + '.video.bin', str(prefix) + '.audio.s16le']
            # Metadata FIFOs are drained continuously, independently of media consumers.
            for path in paths + [p + '.packets.csv' for p in paths]:
                os.mkfifo(path)
                fds.append(os.open(path, os.O_RDONLY | os.O_NONBLOCK))

            def chunks(fd):
                while True:
                    ready, _, _ = select.select([fd], [], [], .05)
                    if ready or self.native.poll() is not None:
                        try:
                            data = os.read(fd, 65536)
                        except BlockingIOError:
                            if self.native.poll() is not None:
                                return
                            continue
                        if data:
                            yield data
                        elif self.native.poll() is not None:
                            return
                        else:
                            time.sleep(.002)

            def enqueue(target, data):
                if self.stopping.is_set():
                    return
                try:
                    target.put_nowait(data)
                except queue.Full:
                    self.fail('consumer cannot keep up; bounded output queue exhausted')

            def finish(target):
                while True:
                    try:
                        target.put(None, timeout=.05)
                        return
                    except queue.Full:
                        if self.stopping.is_set():
                            try:
                                target.get_nowait()
                            except queue.Empty:
                                pass

            def metadata_worker(index):
                pending = bytearray()
                broken = False
                try:
                    for data in chunks(fds[index + 2]):
                        if broken:
                            continue
                        pending.extend(data)
                        while (end := pending.find(b'\n')) >= 0:
                            line = bytes(pending[:end]); del pending[:end + 1]
                            try:
                                windows[index].add(line)
                            except (ValueError, StreamError) as error:
                                self.fail(error); broken = True; break
                    if pending and not broken:
                        self.fail('truncated packet telemetry')
                except Exception as error:
                    self.fail(error)
                finally:
                    windows[index].close()

            def video_worker():
                frames = []
                previous = None
                period = 1001000 / 30 if self.standard == 'ntsc' else 40000

                def event(index, field1, field2):
                    nonlocal previous
                    stamp = windows[0].byte_time(field1)
                    if previous is not None and abs(stamp - previous - period) > 1000:
                        raise StreamError('video timestamp gap; refusing silent CFR frame loss')
                    previous = stamp
                    if not first_stamp:
                        first_stamp.append(stamp); aligned.set()
                    enqueue(queues[0], frames.pop())
                    self.stats.video_frames += 1

                decoder = Decoder(720, 480 if self.standard == 'ntsc' else 576, frames.append, event)
                broken = False
                try:
                    for data in chunks(fds[0]):
                        if not broken and not self.stopping.is_set():
                            try:
                                decoder.feed(data)
                            except Exception as error:
                                self.fail(error); broken = True
                except Exception as error:
                    self.fail(error)
                finally:
                    finish(queues[0])

            def audio_worker():
                pending = bytearray()
                skip = None
                broken = False
                try:
                    for data in chunks(fds[1]):
                        if broken or self.stopping.is_set():
                            continue
                        pending.extend(data)
                        try:
                            if skip is None and aligned.is_set():
                                skip = windows[1].audio_offset(first_stamp[0])
                                self.stats.audio_skip_samples = skip // 4
                            if skip is None:
                                if len(pending) > 768000:
                                    raise StreamError('no complete video frame after four seconds of PCM')
                                continue
                            drop = min(skip, len(pending)); del pending[:drop]; skip -= drop
                            if not skip and pending:
                                enqueue(queues[1], bytes(pending))
                                self.stats.audio_bytes += len(pending); pending.clear()
                        except Exception as error:
                            self.fail(error); broken = True
                except Exception as error:
                    self.fail(error)
                finally:
                    finish(queues[1])

            def writer(index, fd):
                os.set_blocking(fd, False)
                try:
                    while (item := queues[index].get()) is not None:
                        view = memoryview(item)
                        deadline = time.monotonic() + 2
                        while view and (not self.stopping.is_set() or len(view) != len(item)):
                            if time.monotonic() > deadline:
                                raise StreamError(f'output pipe {index} stalled')
                            _, ready, _ = select.select([], [fd], [], .05)
                            if ready:
                                try:
                                    count = os.write(fd, view)
                                except BlockingIOError:
                                    continue
                                view = view[count:]
                except BrokenPipeError:
                    # Main loop classifies the muxer's exit and tears down USB.
                    self.stopping.set()
                except Exception as error:
                    self.fail(error)
                finally:
                    os.close(fd)

            try:
                vr, vw = os.pipe(); ar, aw = os.pipe()
                pipe_fds = [vr, vw, ar, aw]
                self.mux = subprocess.Popen(self.mux_command(vr, ar), pass_fds=(vr, ar),
                                            stdout=output, stderr=log)
                os.close(vr); os.close(ar); pipe_fds = [vw, aw]
                self.native = subprocess.Popen([str(ROOT / 'build/c039-probe'), '--seconds', str(self.seconds),
                    '--audio-attenuation-db', str(self.attenuation), '--log-fifo-packets',
                    '--capture', self.standard, str(prefix), str(prefix) + '.configuration.bin'],
                    stdout=log, stderr=log)
                calls = [(metadata_worker, (0,)), (metadata_worker, (1,)),
                         (writer, (0, vw)), (writer, (1, aw)),
                         (video_worker, ()), (audio_worker, ())]
                threads = [threading.Thread(target=fn, args=args, daemon=True) for fn, args in calls]
                for thread in threads:
                    thread.start()
                pipe_fds = []  # Writer threads own these descriptors now.
                while self.native.poll() is None and self.mux.poll() is None and not self.stopping.wait(.05):
                    pass
            finally:
                if self.native is not None and self.native.poll() is None:
                    self.stopping.set(); self.native.terminate()
                if self.native is not None:
                    self.native.wait(timeout=15)
                for thread in threads:
                    thread.join(timeout=3)
                if any(thread.is_alive() for thread in threads):
                    self.fail('stream workers did not finish')
                if self.mux is not None:
                    try:
                        self.mux.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self.fail('muxer did not finish'); self.mux.terminate()
                        try:
                            self.mux.wait(timeout=3)
                        except subprocess.TimeoutExpired:
                            # USB has already been stopped/restored. A muxer
                            # blocked on a dead output may ignore SIGTERM.
                            self.mux.kill(); self.mux.wait(timeout=3)
                for fd in fds + pipe_fds:
                    os.close(fd)
            self.stats.native_exit = self.native.returncode if self.native else None
            self.stats.mux_exit = self.mux.returncode if self.mux else None
            self.stats.video_packets, self.stats.audio_packets = (w.packets for w in windows)
            log.flush()
            diagnostics = log_path.read_text(errors='replace')
            if 'rollback_verified=NO' in diagnostics or 'bridge_power_restored=NO' in diagnostics:
                self.errors.append('native USB control restoration failed')
            closed = allow_disconnect and self.stats.mux_exit in (224, -13) and 'Broken pipe' in diagnostics
            if not self.requested_stop and not closed:
                if self.stats.native_exit != 0 or self.stats.mux_exit != 0:
                    self.errors.append('capture or muxer failed')
                if not self.stats.video_frames or not self.stats.audio_bytes:
                    self.errors.append('no complete video/audio output')
            summary = dict(asdict(self.stats), errors=self.errors, stopped=self.requested_stop,
                           downstream_closed=closed)
            print('stream_summary ' + json.dumps(summary), file=log, flush=True)
            return 1 if self.errors else 0
