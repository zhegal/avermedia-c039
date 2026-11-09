# SPDX-License-Identifier: GPL-2.0-or-later
"""Persistent native-format A/V monitor. Only manual Close ends the viewer."""
from collections import deque
from pathlib import Path
import argparse
import queue
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from windows_audio import PcmMonitor
from windows_preview import PreviewCapture, put_latest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--standard', default='auto')
    args = parser.parse_args()
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        parser.error('FFmpeg is required for preview RGB conversion')
    root = tk.Tk(); root.title('C039 — persistent A/V preview'); root.geometry('790x735')
    root.configure(bg='#202020')
    picture = tk.Label(root, bg='black'); picture.pack(fill='both', expand=True)
    status = tk.StringVar(value='Открытие исходного видео и PCM…')
    tk.Label(root, textvariable=status, bg='#202020', fg='white', anchor='w', justify='left').pack(fill='x', padx=7, pady=5)
    closing = threading.Event()
    audio_error = ''
    try:
        audio = PcmMonitor()
    except Exception as error:
        audio = None; audio_error = str(error)
    source = PreviewCapture(audio, args.standard)
    rgb = queue.Queue(8)
    converter = dict(process=None, last_rgb=time.monotonic(), last_input=time.monotonic(), error='')
    display_drops = [0]

    def stop_converter():
        process = converter['process']; converter['process'] = None
        if process:
            try:
                process.stdin.close(); process.wait(timeout=1)
            except (OSError, subprocess.TimeoutExpired):
                process.kill(); process.wait(timeout=2)

    def read_rgb(process, metadata, width, height):
        needed = width * height * 3
        try:
            while not closing.is_set():
                data = bytearray()
                while len(data) < needed:
                    chunk = process.stdout.read(needed - len(data))
                    if not chunk:
                        return
                    data.extend(chunk)
                stamp, generation = metadata.get(timeout=2)
                display_drops[0] += put_latest(rgb, (bytes(data), width, height, stamp, generation))
                converter['last_rgb'] = time.monotonic()
        except (OSError, ValueError, queue.Empty):
            return

    def convert():
        height = None; process = None; metadata = None
        try:
            while not closing.is_set():
                try:
                    data, actual, stamp, generation = source.frames.get(timeout=.1)
                except queue.Empty:
                    continue
                if actual != height or process is None or process.poll() is not None:
                    stop_converter(); height = actual; width = height * 4 // 3
                    metadata = queue.Queue(8)
                    process = subprocess.Popen([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
                        '-f', 'rawvideo', '-pixel_format', 'uyvy422', '-video_size', f'720x{height}',
                        '-framerate', '25' if height == 576 else '30000/1001', '-i', 'pipe:0', '-an',
                        '-vf', f'scale={width}:{height}:flags=neighbor', '-vsync', '0', '-pix_fmt', 'rgb24',
                        '-f', 'rawvideo', 'pipe:1'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=None, creationflags=subprocess.CREATE_NO_WINDOW)
                    converter['process'] = process
                    threading.Thread(target=read_rgb, args=(process, metadata, width, height), daemon=True).start()
                metadata.put((stamp, generation), timeout=1)
                converter['last_input'] = time.monotonic()
                process.stdin.write(data); process.stdin.flush()
        except Exception as error:
            if not closing.is_set():
                converter['error'] = str(error)
                print(f'preview RGB worker: {error}', file=sys.stderr, flush=True)
        finally:
            stop_converter()

    source.start()
    converter_thread = [threading.Thread(target=convert, daemon=True)]
    converter_thread[0].start()
    controls = tk.Frame(root, bg='#202020'); controls.pack(fill='x', padx=7, pady=(0, 6))
    selected = tk.StringVar(value=args.standard)
    choices = ('auto', 'pal', 'secam', 'ntsc', 'ntsc-j', 'ntsc-443', 'pal-m', 'pal-n', 'pal-nc', 'pal-60')
    ttk.Combobox(controls, textvariable=selected, values=choices, state='readonly', width=13).pack(side='left')

    def apply_standard():
        source.standard = selected.get()
        source._event(f'manual selection={source.standard}; logical viewer retained')
        with source.native_lock:
            if source.native:
                source.native.stop()

    ttk.Button(controls, text='Применить', command=apply_standard).pack(side='left', padx=5)

    def close():
        closing.set(); source.stop(); status.set('Ручная остановка. Восстановление USB…')
        process = converter['process']
        if process and process.poll() is None:
            process.terminate()  # RGB conversion only; never terminates USB owner.

    ttk.Button(controls, text='Остановить и закрыть', command=close).pack(side='right')
    root.protocol('WM_DELETE_WINDOW', close)
    names = {0: 'не определён', 1: 'PAL', 2: 'SECAM', 3: 'NTSC', 5: 'NTSC-J',
             6: 'NTSC-4.43', 7: 'PAL-M', 8: 'PAL-N', 9: 'PAL-Nc', 10: 'PAL-60'}
    pending = deque(maxlen=12)
    generation = [source.generation]
    wall_epoch = [time.monotonic()]
    last_frame = [0.]
    restart_after = [0.]

    def refresh():
        now = time.monotonic()
        if source.generation != generation[0]:
            generation[0] = source.generation; pending.clear(); wall_epoch[0] = now
        try:
            while True:
                item = rgb.get_nowait()
                if item[4] == source.generation:
                    pending.append(item)
        except queue.Empty:
            pass
        if audio and not closing.is_set():
            try:
                audio.start_if_ready(); played = audio.position()
            except Exception as error:
                source.state['error'] = str(error); played = 0
        else:
            played = max(0, int((now - wall_epoch[0] - .12) * 48000))
        chosen = None
        while pending:
            candidate = pending[0]
            try:
                target = source.target_sample(candidate[3])
            except Exception:
                target = -1
            if target is None or target > played + 240:
                break
            pending.popleft()
            if target < 0:
                display_drops[0] += 1
            else:
                if chosen:
                    display_drops[0] += 1
                chosen = candidate
        if chosen:
            data, width, height, stamp, _ = chosen
            photo = tk.PhotoImage(data=f'P6\n{width} {height}\n255\n'.encode() + data, format='PPM')
            picture.configure(image=photo, width=width, height=height); picture.image = photo
            last_frame[0] = now
        signal = source.signal
        detected = names.get(signal['detected'], '?') if signal else 'ожидание'
        lock = signal and signal['present'] and signal['hlock'] and signal['vlock']
        if not closing.is_set():
            status.set(f"Режим: {source.standard.upper()}  |  Детектор: {detected}  |  H/V lock: {'да' if lock else 'нет'}"
                f"  |  {'LIVE' if now-last_frame[0] < 1 else 'Ожидание сигнала / полей'}\n"
                f"Исходник: 720×{source.state['height']} @ {source.state['rate']}, interlaced  |  Показ 4:3\n"
                f"Звук: {'PCM stereo 48 kHz; video follows audio clock' if audio else audio_error}\n"
                f"Кадров: {source.state['frames']}  |  Неполных для превью: {source.state['partial_frames']}"
                f"  |  Пропуски показа: {source.state['preview_drops']+display_drops[0]}\n"
                f"Смен формата: {source.state['geometry_changes']}  |  Восстановлений USB: {source.state['recoveries']}"
                f"  |  {source.state['error']}")
            root.title(f"C039 LIVE A/V — {detected} — {source.state['height']} / {source.state['rate']}")
            if not converter_thread[0].is_alive() and now >= restart_after[0]:
                restart_after[0] = now + 1
                converter_thread[0] = threading.Thread(target=convert, daemon=True); converter_thread[0].start()
        if closing.is_set() and source.done.is_set() and source.processed.is_set():
            source.capture_thread.join(); source.process_thread.join()
            if audio:
                audio.close()
            root.destroy(); return
        root.after(10, refresh)

    refresh(); root.mainloop()


if __name__ == '__main__':
    main()
