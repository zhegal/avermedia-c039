# SPDX-License-Identifier: GPL-2.0-or-later
"""Windows transport edge for the shared strict parser, cadence and FFmpeg muxer."""
from dataclasses import asdict
import json
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

from bt656 import Decoder
from capture_stream import PacketWindow, StreamError, VideoCadence, ROOT
from windows_native import NativeSession
from windows_pipe import PipeWriter
from preview_decoder import PreviewDecoder
from runtime_paths import ffmpeg_path


def run_windows(engine, output, log_path, *, allow_disconnect=False, native_factory=NativeSession):
    ffmpeg = ffmpeg_path()
    if not ffmpeg:
        raise StreamError('FFmpeg is required for Windows streaming')
    log_path = Path(log_path); log_path.parent.mkdir(parents=True, exist_ok=True)
    packet_queues = [queue.Queue(2048), queue.Queue(4096)]
    media_queues = [queue.Queue(64), queue.Queue(256)]
    windows = [PacketWindow(), PacketWindow()]
    pipes = [PipeWriter(), PipeWriter()]
    native_done, video_done = threading.Event(), threading.Event()
    aligned = threading.Event()
    first_stamp = []
    state = dict(output_frames=0, audio_sent=0, source_audio_bytes=0, trailing_audio_bytes=0,
                 native_result=None, pipe_errors=[], standard_events=[], first_video_usb_us=None,
                 last_video_usb_us=None, video_clock_drift_us=0, first_audio_usb_us=None,
                 last_audio_usb_us=None, audio_clock_drift_samples=0)
    state['preview_partial_frames'] = 0
    state['written_video_frames'] = state['written_audio_samples'] = 0
    engine.windows_status = state
    engine.latest_signal = None

    def enqueue(target, item):
        try:
            target.put_nowait(item)
        except queue.Full as error:
            raise StreamError('consumer cannot keep up; bounded Windows queue exhausted') from error

    def finish(target):
        deadline = time.monotonic() + 2
        while True:
            try:
                target.put(None, timeout=.05); return
            except queue.Full:
                if engine.errors or time.monotonic() > deadline:
                    engine.fail('Windows stream queue could not drain')
                    try:
                        target.get_nowait()
                    except queue.Empty:
                        pass

    def packet(endpoint, data, stamp):
        if engine.stopping.is_set() and (endpoint == 4 or engine.errors):
            return  # Admission closed; queued accepted data still drains.
        if endpoint not in (3, 4):
            raise StreamError('unexpected USB endpoint')
        enqueue(packet_queues[0 if endpoint == 4 else 1], (data, stamp))

    def batch(endpoint, data, descriptors, stamp):
        if engine.stopping.is_set() and (endpoint == 4 or engine.errors):
            return
        if endpoint not in (3, 4):
            raise StreamError('unexpected USB endpoint')
        enqueue(packet_queues[0 if endpoint == 4 else 1], (data, descriptors, stamp))

    def packets(target):
        while (item := target.get()) is not None:
            if len(item) == 2:
                yield item
            else:
                data, descriptors, first = item
                for n, (offset, length, status) in enumerate(descriptors):
                    if status or offset + length > len(data):
                        raise StreamError('invalid native USB batch descriptor')
                    yield data[offset:offset + length], first + n * 125

    def standard(profile_id, height, numerator, denominator):
        state['standard_events'].append(dict(id=profile_id, height=height, rate=f'{numerator}/{denominator}'))
        # Keep indefinite Auto telemetry bounded.
        del state['standard_events'][:-32]
        if height != engine.height or f'{numerator}/{denominator}' != engine.rate:
            raise StreamError('native geometry/rate family changed; ending fixed-format stream without scaling')

    def video():
        decoded = []
        offset = 0; previous_packet = None; last_frame = None
        period = 1001000 / 30 if engine.height == 480 else 40000
        cadence = VideoCadence(period, engine.conceal_gaps)

        def frame_event(index, field1, field2):
            nonlocal last_frame
            frame = decoded.pop()
            try:
                stamp = windows[0].byte_time(field1)
            except StreamError:
                if not engine.conceal_gaps or not decoder.last_partial:
                    raise
                stamp = previous_packet - period
            missing = cadence.advance(stamp, continuous_preview=engine.conceal_gaps)
            if engine.conceal_gaps:
                state['preview_partial_frames'] = decoder.partial_frames
            engine.stats.video_frames += 1
            if state['first_video_usb_us'] is None:
                state['first_video_usb_us'] = stamp
            state['last_video_usb_us'] = stamp
            state['video_clock_drift_us'] = stamp - state['first_video_usb_us'] - (engine.stats.video_frames - 1) * period
            if missing < 0:
                engine.stats.dropped_video_frames += 1; return
            if not first_stamp:
                first_stamp.append(stamp); aligned.set()
            for _ in range(missing):
                enqueue(media_queues[0], last_frame)
                state['output_frames'] += 1
            engine.stats.held_video_frames += missing
            enqueue(media_queues[0], frame); state['output_frames'] += 1
            last_frame = frame
            observer = getattr(engine, 'preview_sink', None)
            if observer:
                observer(frame, engine.height)

        decoder_class = PreviewDecoder if engine.conceal_gaps else Decoder
        decoder = decoder_class(720, engine.height, decoded.append, frame_event)
        try:
            for item in packets(packet_queues[0]):
                if engine.errors:
                    continue
                data, stamp = item
                if previous_packet is not None and stamp - previous_packet != 125:
                    raise StreamError('video USB packet timeline is discontinuous')
                previous_packet = stamp
                windows[0].add_packet(offset, len(data), stamp); offset += len(data)
                decoder.feed(data)
                if engine.conceal_gaps and last_frame is not None:
                    # Keep the preview's A/V timeline running through arbitrary
                    # signal loss. Two-frame display headroom lets a late field
                    # pair arrive before an explicitly counted held picture.
                    while stamp > cadence.epoch + (cadence.sent + 2) * period + 1000:
                        enqueue(media_queues[0], last_frame)
                        cadence.sent += 1; state['output_frames'] += 1
                        engine.stats.held_video_frames += 1
        except Exception as error:
            engine.fail(error)
            # Drain admitted raw data so the USB thread can finalize.
            while packet_queues[0].get() is not None:
                pass
        finally:
            engine.stats.video_packets = windows[0].packets
            windows[0].close(); video_done.set(); finish(media_queues[0])

    def audio():
        pending = bytearray(); offset = 0; previous_packet = None; skip = None; pcm_started = False
        numerator, denominator = map(int, engine.rate.split('/'))

        def release(final=False):
            # Keep audio aligned to admitted pictures. Hold a bounded tail until
            # the last video frame is known; never invent PCM or resample it.
            allowed = state['output_frames'] * 48000 * denominator // numerator * 4
            count = min(len(pending), max(0, allowed - state['audio_sent'])) // 4 * 4
            if count >= 4096 or (final and count):
                enqueue(media_queues[1], bytes(pending[:count])); del pending[:count]
                state['audio_sent'] += count; engine.stats.audio_bytes += count

        try:
            for item in packets(packet_queues[1]):
                if engine.errors:
                    continue
                data, stamp = item
                if not data and pcm_started and not engine.conceal_gaps:
                    raise StreamError('missing PCM USB packet after audio started; refusing archival sample loss')
                pcm_started |= bool(data)
                if len(data) % 4 or (previous_packet is not None and stamp - previous_packet != 125):
                    raise StreamError('PCM sample boundary or USB packet timeline is discontinuous')
                previous_packet = stamp
                windows[1].add_packet(offset, len(data), stamp); offset += len(data)
                state['source_audio_bytes'] += len(data)
                if state['first_audio_usb_us'] is None:
                    state['first_audio_usb_us'] = stamp
                state['last_audio_usb_us'] = stamp
                state['audio_clock_drift_samples'] = (state['source_audio_bytes'] / 4 -
                    (stamp + 125 - state['first_audio_usb_us']) * .048)
                pending.extend(data)
                if skip is None and aligned.is_set() and stamp + 125 > first_stamp[0]:
                    skip = windows[1].audio_offset(first_stamp[0])
                    engine.stats.audio_skip_samples = skip // 4
                if skip is not None:
                    count = min(skip, len(pending)); del pending[:count]; skip -= count
                    if not skip:
                        release()
                if len(pending) > 768000:
                    raise StreamError('no aligned complete video within bounded PCM history')
            if not video_done.wait(3):
                raise StreamError('video parser did not finalize before PCM trim')
            if skip is None and aligned.is_set():
                skip = windows[1].audio_offset(first_stamp[0])
                engine.stats.audio_skip_samples = skip // 4
                count = min(skip, len(pending)); del pending[:count]; skip -= count
            if skip == 0:
                release(final=True)
            state['trailing_audio_bytes'] = len(pending)
        except Exception as error:
            engine.fail(error)
            if not native_done.is_set():
                while packet_queues[1].get() is not None:
                    pass
        finally:
            engine.stats.audio_packets = windows[1].packets
            windows[1].close(); finish(media_queues[1])

    def writer(index):
        try:
            pipes[index].connect()
            while (item := media_queues[index].get()) is not None:
                pipes[index].write(item)
                if index == 0:
                    state['written_video_frames'] += 1
                else:
                    state['written_audio_samples'] += len(item) // 4
        except Exception as error:
            state['pipe_errors'].append(str(error))
            engine.fail(f'FFmpeg input pipe {index}: {error}')
            while True:
                try:
                    if media_queues[index].get(timeout=.1) is None:
                        break
                except queue.Empty:
                    if native_done.is_set() and (index == 1 or video_done.is_set()):
                        break
        finally:
            pipes[index].close()

    def capture():
        try:
            state['native_result'] = engine.native.run()
            if state['native_result']:
                engine.fail(f'Windows native capture failed ({state["native_result"]})')
        except Exception as error:
            state['native_result'] = getattr(engine.native, 'last_result', None) or 1
            engine.fail(error)
        finally:
            # Closing is safe only in this thread after run() has returned.
            engine.native.close()
            native_done.set()
            for target in packet_queues:
                finish(target)

    threads = []
    with log_path.open('w', encoding='utf-8') as log:
        try:
            engine.native = native_factory(standard=engine.standard, seconds=engine.seconds,
                attenuation=engine.attenuation, on_packet=packet, on_standard=standard,
                on_signal=lambda value: setattr(engine, 'latest_signal', value), decode_frames=False, on_batch=batch)
            command = engine.mux_command(pipes[0].path, pipes[1].path); command[0] = ffmpeg
            engine.mux = subprocess.Popen(command, stdout=output, stderr=log,
                                          creationflags=subprocess.CREATE_NO_WINDOW)
            threads = [threading.Thread(target=fn, args=args, daemon=True) for fn, args in
                       ((writer, (0,)), (writer, (1,)), (video, ()), (audio, ()), (capture, ()))]
            for thread in threads:
                thread.start()
            while not native_done.wait(.02):
                if engine.mux.poll() is not None and not engine.stopping.is_set():
                    engine.fail('FFmpeg exited before capture completed')
                if engine.stopping.is_set():
                    engine.native.stop()
        except Exception as error:
            engine.fail(error)
        finally:
            if engine.native is not None and not native_done.is_set():
                engine.native.stop()
            if threads:
                threads[-1].join(timeout=15)
                for thread in threads[:-1]:
                    thread.join(timeout=3)
                if any(thread.is_alive() for thread in threads):
                    engine.fail('Windows capture/parser/writer did not finish')
                    for pipe in pipes:
                        pipe.cancel()
            else:
                if engine.native is not None:
                    engine.native.close()
                for pipe in pipes:
                    pipe.close()
            if engine.mux is not None:
                try:
                    engine.mux.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    engine.fail('FFmpeg muxer did not finalize')
                    engine.mux.terminate()
                    try:
                        engine.mux.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        engine.mux.kill(); engine.mux.wait(timeout=3)
            engine.stats.native_exit = state['native_result']
            engine.stats.mux_exit = engine.mux.returncode if engine.mux else None
            log.flush()
            diagnostics = log_path.read_text(encoding='utf-8', errors='replace')
            closed = allow_disconnect and 'Broken pipe' in diagnostics and state['native_result'] == 0
            if closed:
                engine.errors[:] = [error for error in engine.errors
                    if not error.startswith(('FFmpeg input pipe', 'FFmpeg exited before'))]
            if not closed and engine.stats.mux_exit != 0:
                engine.errors.append('FFmpeg muxer failed')
            if not engine.requested_stop and not closed and (not state['output_frames'] or not engine.stats.audio_bytes):
                engine.errors.append('no complete video/audio output')
            if not engine.errors and not closed:
                numerator, denominator = map(int, engine.rate.split('/'))
                expected_audio = state['output_frames'] * 48000 * denominator // numerator
                if state['written_video_frames'] != state['output_frames']:
                    engine.errors.append('accepted and written video frame counts differ')
                if state['written_audio_samples'] * 4 != engine.stats.audio_bytes:
                    engine.errors.append('accepted and written PCM sample counts differ')
                if state['written_audio_samples'] != expected_audio:
                    engine.errors.append('PCM does not cover the admitted video duration')
            summary = dict(asdict(engine.stats), windows=state, signal=engine.latest_signal,
                           errors=engine.errors, stopped=engine.requested_stop, downstream_closed=closed)
            print('stream_summary ' + json.dumps(summary), file=log, flush=True)
    return 1 if engine.errors else 0
