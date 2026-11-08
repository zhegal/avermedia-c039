#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""PAL/SECAM preview controls with decoder signal status and safe mode switching."""
import argparse
from pathlib import Path
import signal
import subprocess
import sys
import tkinter as tk
from tkinter import ttk
import time

ROOT = Path(__file__).resolve().parents[1]


class Controls:
    def __init__(self, window, standard, prefix):
        self.window, self.prefix = window, prefix
        self.process = None
        self.player_log = None
        self.active_mode = None
        self.wanted = True
        self.closing = False
        self.counter = 0
        self.next_start = 0
        self.mode = tk.StringVar(value=standard)
        self.status = tk.StringVar(value='Ожидание изображения…')
        window.title('AVerMedia C039 — PAL / SECAM')
        window.geometry('470x210')
        frame = ttk.Frame(window, padding=16); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='Вход Composite', font=('', 14, 'bold')).pack(anchor='w')
        choices = ttk.Frame(frame); choices.pack(anchor='w', pady=12)
        for text, value in [('Auto PAL/SECAM', 'auto'), ('PAL', 'pal'), ('SECAM', 'secam')]:
            ttk.Radiobutton(choices, text=text, value=value, variable=self.mode,
                            command=self.change_mode).pack(side='left', padx=(0, 12))
        ttk.Label(frame, textvariable=self.status, wraplength=430).pack(anchor='w', pady=6)
        buttons = ttk.Frame(frame); buttons.pack(anchor='w', pady=8)
        ttk.Button(buttons, text='Запустить', command=self.start).pack(side='left', padx=(0, 8))
        ttk.Button(buttons, text='Остановить', command=self.stop).pack(side='left')
        ttk.Label(frame, text='Composite + RCA: видео и стереозвук 48 кГц.').pack(anchor='w')
        window.protocol('WM_DELETE_WINDOW', self.close)
        signal.signal(signal.SIGTERM, lambda *_: self.close())
        signal.signal(signal.SIGINT, lambda *_: self.close())
        window.after(100, self.poll)

    def change_mode(self):
        self.wanted = True
        self.status.set('Переключение режима…')
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()

    def start(self):
        self.wanted = True
        self.next_start = 0

    def stop(self):
        self.wanted = False
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()

    def close(self):
        self.closing = True
        self.status.set('Завершение захвата…')
        self.stop()

    def poll(self):
        alive = self.process is not None and self.process.poll() is None
        if self.process is not None and not alive:
            if self.player_log:
                self.player_log.close(); self.player_log = None
            self.process = None
            self.next_start = time.monotonic() + .5
        if self.closing and not alive:
            self.window.destroy(); return
        if self.wanted and not alive and time.monotonic() >= self.next_start:
            self.counter += 1
            self.active_mode = self.mode.get()
            self.log = Path(str(self.prefix) + f'-{self.counter}.log')
            self.log.parent.mkdir(parents=True, exist_ok=True)
            self.player_log = Path(str(self.prefix) + f'-{self.counter}.wrapper.log').open('w')
            self.process = subprocess.Popen([sys.executable, str(ROOT / 'tools/preview_av.py'),
                '--standard', self.active_mode, '--seconds', '0', '--log', str(self.log)],
                stdout=self.player_log, stderr=self.player_log)
            self.status.set(f'Режим {self.active_mode.upper()}: ожидание сигнала…')
        elif alive:
            try:
                with self.log.open('rb') as source:
                    source.seek(max(0, self.log.stat().st_size - 16000))
                    lines = source.read().decode(errors='replace').splitlines()
                rows = [row for row in lines if row.startswith('signal ')]
                if rows:
                    values = dict(part.split('=', 1) for part in rows[-1].split()[1:])
                    stable = values['present'] == values['hlock'] == values['vlock'] == '1'
                    detected = values['detected'].upper()
                    selected = values['selected'].upper()
                    message = f'Сигнал есть; настройка {selected}' if stable else 'Нет устойчивой синхронизации'
                    if stable and self.active_mode == 'auto' and detected != selected:
                        message = f'Переход {selected} → {detected}…' if detected in ('PAL', 'SECAM') else 'Auto поддерживает только PAL/SECAM'
                    self.status.set(f'Режим: {self.active_mode.upper()}   Декодер: {detected}\n' + message)
            except (OSError, KeyError, ValueError):
                pass
        elif not self.wanted and not self.closing:
            self.status.set('Захват остановлен')
        self.window.after(200, self.poll)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--standard', choices=['auto', 'pal', 'secam'], default='auto')
    p.add_argument('--log-prefix', type=Path, default=ROOT / 'build/preview-control')
    args = p.parse_args()
    window = tk.Tk()
    Controls(window, args.standard, args.log_prefix)
    window.mainloop()


if __name__ == '__main__':
    main()
