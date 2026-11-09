# SPDX-License-Identifier: GPL-2.0-or-later
"""Live Windows preview: one USB owner, bounded display queues, raw interlaced input."""
import argparse
from pathlib import Path
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
from windows_native import NativeSession


def latest(target, item):
    dropped = 0
    while True:
        try:
            target.put_nowait(item); return dropped
        except queue.Full:
            try:
                target.get_nowait(); dropped += 1
            except queue.Empty:
                pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--standard', default='auto')
    args = parser.parse_args()
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        parser.error('FFmpeg is required for preview RGB conversion')
    root = tk.Tk(); root.title('AVerMedia C039 — Live Auto')
    root.geometry('780x660')
    root.configure(bg='#202020')
    image = tk.Label(root, bg='black')
    image.pack(fill='both', expand=True)
    status = tk.StringVar(value='Открытие C039…')
    tk.Label(root, textvariable=status, bg='#202020', fg='white', anchor='w', justify='left').pack(fill='x', padx=6, pady=4)
    closing = threading.Event(); finished = threading.Event()
    frames, pictures = queue.Queue(2), queue.Queue(1)
    state = dict(signal=None, last_frame=0., drops=0, display_drops=0, frames=0, error='', result=None)
    converter = [None]
    converter_lock = threading.Lock()

    def on_frame(data, height):
        state['frames'] += 1; state['last_frame'] = time.monotonic()
        state['drops'] += latest(frames, (data, height))

    session = NativeSession(standard=args.standard, on_frame=on_frame,
        on_signal=lambda value: state.update(signal=value))

    def usb():
        try:
            state['result'] = session.run()
            if state['result']:
                state['error'] = f"USB capture error {state['result']}; see preview log"
        except Exception as error:
            state['error'] = str(error)
        finally:
            finished.set()

    def read_pictures(process, width, height):
        needed = width * height * 3
        try:
            while True:
                data = bytearray()
                while len(data) < needed:
                    chunk = process.stdout.read(needed - len(data))
                    if not chunk:
                        return
                    data.extend(chunk)
                state['display_drops'] += latest(pictures, (bytes(data), width, height))
        except (OSError, ValueError):
            pass

    def stop_converter():
        process = converter[0]; converter[0] = None
        if process:
            try:
                process.stdin.close()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                process.kill(); process.wait(timeout=2)

    def convert():
        process = None; height = None
        try:
            while not closing.is_set():
                try:
                    data, actual = frames.get(timeout=.1)
                except queue.Empty:
                    if finished.is_set():
                        break
                    continue
                if actual != height:
                    stop_converter(); height = actual; width = height * 4 // 3
                    # RGB and horizontal PAR correction are display-only.
                    # No deinterlacing, no recording files, no USB restart.
                    process = subprocess.Popen([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
                        '-f', 'rawvideo', '-pixel_format', 'uyvy422', '-video_size', f'720x{height}',
                        '-framerate', '25' if height == 576 else '30000/1001', '-i', 'pipe:0',
                        '-an', '-vf', f'scale={width}:{height}:flags=neighbor', '-pix_fmt', 'rgb24',
                        '-f', 'rawvideo', 'pipe:1'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=None, creationflags=subprocess.CREATE_NO_WINDOW)
                    with converter_lock:
                        converter[0] = process
                    threading.Thread(target=read_pictures, args=(process, width, height), daemon=True).start()
                process.stdin.write(data); process.stdin.flush()
        except Exception as error:
            if not closing.is_set():
                state['error'] = f'Preview conversion: {error}'
                session.stop()
        finally:
            stop_converter()

    capture_thread = threading.Thread(target=usb, daemon=True)
    conversion_thread = threading.Thread(target=convert, daemon=True)
    capture_thread.start(); conversion_thread.start()
    names = {0: 'не определён', 1: 'PAL', 2: 'SECAM', 3: 'NTSC', 5: 'NTSC-J',
             6: 'NTSC-4.43', 7: 'PAL-M', 8: 'PAL-N', 9: 'PAL-Nc', 10: 'PAL-60'}

    def close():
        closing.set(); session.stop()
        status.set('Остановка USB и восстановление регистров…')

    ttk.Button(root, text='Закрыть', command=close).pack(anchor='e', padx=6, pady=(0, 4))
    root.protocol('WM_DELETE_WINDOW', close)

    def refresh():
        try:
            data, width, height = pictures.get_nowait()
            photo = tk.PhotoImage(data=f'P6\n{width} {height}\n255\n'.encode() + data, format='PPM')
            image.configure(image=photo, width=width, height=height); image.image = photo
        except queue.Empty:
            pass
        signal = state['signal']
        if not closing.is_set():
            detected = names.get(signal['detected'], '?') if signal else 'ожидание'
            lock = bool(signal and signal['present'] and signal['hlock'] and signal['vlock'])
            waiting = time.monotonic() - state['last_frame'] > 1
            status.set(f"Режим: {args.standard.upper()}  |  Детектор: {detected}  |  H/V lock: {'да' if lock else 'нет'}"
                f"  |  Цвет: {'lock' if signal and signal['chroma'] else 'нет lock'}"
                f"  |  {'Ожидание полных полей' if waiting else 'LIVE'}\n"
                f"Исходник: 720×{session.height}, interlaced; показ 4:3  |  Кадров: {state['frames']}"
                f"  |  Пропуски только превью: {state['drops'] + state['display_drops']}  |  {state['error']}")
            root.title(f"C039 LIVE — {detected} — {'сигнал' if lock else 'нет lock'}")
        if closing.is_set() and finished.is_set():
            capture_thread.join(); session.close()
            # Converter is independent of USB. Unblock it if its pipe stalled.
            with converter_lock:
                if converter[0] and converter[0].poll() is None:
                    converter[0].terminate()
            root.destroy(); return
        root.after(40, refresh)

    refresh(); root.mainloop()


if __name__ == '__main__':
    main()
