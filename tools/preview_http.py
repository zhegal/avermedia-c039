# SPDX-License-Identifier: GPL-2.0-or-later
"""Optional local viewer for the existing HTTP source; never opens USB itself."""
from pathlib import Path
import os
import shutil
import subprocess
import tkinter as tk
from tkinter import ttk


def show_preview(port, engine, stop, producer_thread):
    ffplay = shutil.which('ffplay')
    if not ffplay:
        raise RuntimeError('ffplay is required for --preview')
    root = tk.Tk(); root.title('C039 — Shared A/V source'); root.geometry('750x185')
    root.configure(bg='#202020')
    text = tk.StringVar(value='Открытие общего A/V-источника…')
    tk.Label(root, textvariable=text, bg='#202020', fg='white', anchor='w', justify='left').pack(fill='both', expand=True, padx=8, pady=6)
    path = Path(__file__).resolve().parents[1] / 'build/http-preview-player.log'
    log = path.open('w')
    url = f'http://127.0.0.1:{port}/live.ts'
    player = subprocess.Popen([ffplay, '-hide_banner', '-loglevel', 'warning', '-autoexit',
        '-window_title', 'C039 LIVE — shared MPEG-TS Video + Audio', '-sync', 'audio',
        '-vf', 'setdar=4/3', '-i', url], stdout=subprocess.DEVNULL, stderr=log,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    closing = [False]

    def close():
        closing[0] = True; stop(); text.set('Остановка общего источника и восстановление USB…')

    ttk.Button(root, text='Закрыть источник и превью', command=close).pack(anchor='e', padx=8, pady=(0, 6))
    root.protocol('WM_DELETE_WINDOW', close)
    names = {0: 'не определён', 1: 'PAL', 2: 'SECAM', 3: 'NTSC', 5: 'NTSC-J',
             6: 'NTSC-4.43', 7: 'PAL-M', 8: 'PAL-N', 9: 'PAL-Nc', 10: 'PAL-60'}

    def refresh():
        signal = getattr(engine, 'latest_signal', None)
        detected = names.get(signal['detected'], '?') if signal else 'ожидание'
        lock = signal and signal['present'] and signal['hlock'] and signal['vlock']
        if not closing[0] and engine:
            text.set(f"{url}\nРежим: {engine.standard.upper()}  |  Детектор: {detected}"
                f"  |  H/V lock: {'да' if lock else 'нет'}\n"
                f"MPEG-2 {engine.video_bitrate} Mbit/s, interlaced  |  MP2 stereo 48 kHz / 256 kbit/s\n"
                f"Кадров: {engine.stats.video_frames}  |  Повторы превью: {engine.stats.held_video_frames}"
                f"  |  Пропуски превью: {engine.stats.dropped_video_frames}\n"
                + ('; '.join(engine.errors[-2:]) if engine.errors else 'Один USB-сеанс для всех HTTP-клиентов'))
        if closing[0] and not producer_thread.is_alive():
            if player.poll() is None:
                player.terminate()  # Player only; the source has already drained.
            log.close(); root.destroy(); return
        # Closing the video window only detaches this client. The source/status
        # window stays alive for VLC/OBS/FFmpeg and can be closed explicitly.
        root.after(100, refresh)

    refresh(); root.mainloop()
