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
from tkinter import filedialog
from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from windows_audio import PcmMonitor
from windows_preview import PreviewCapture, put_latest
from preview_display import fit_4x3, rgb_filter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--standard', default='auto')
    parser.add_argument('--http', action='store_true')
    parser.add_argument('--port', type=int, default=8079)
    parser.add_argument('--field-order', choices=('tff', 'bff'))
    parser.add_argument('--video-bitrate', type=int, choices=range(8,13), default=12)
    parser.add_argument('--strict-http', action='store_true')
    parser.add_argument('--record', type=Path, help='explicit new strict recording path; never enabled by default')
    parser.add_argument('--record-seconds', type=int, default=0)
    args = parser.parse_args()
    if args.http and not args.field_order:
        parser.error('--http requires explicit --field-order tff or bff')
    if args.record and not args.field_order:
        parser.error('--record requires explicit --field-order tff or bff')
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        parser.error('FFmpeg is required for preview RGB conversion')
    root = tk.Tk(); root.title('C039 — persistent A/V preview'); root.geometry('790x790')
    root.configure(bg='#202020')
    picture = tk.Canvas(root, bg='black', highlightthickness=0); picture.pack(fill='both', expand=True)
    picture_id = picture.create_image(0,0,anchor='center')
    hint_id = picture.create_text(10,10,anchor='sw',fill='white',font=('Segoe UI',9))
    status = tk.StringVar(value='Открытие исходного видео и PCM…')
    status_label=tk.Label(root, textvariable=status, bg='#202020', fg='white', anchor='w', justify='left')
    status_label.pack(fill='x', padx=7, pady=5)
    normal_widgets=[status_label]
    closing = threading.Event()
    audio_error = ''
    try:
        audio = PcmMonitor()
    except Exception as error:
        audio = None; audio_error = str(error)
    source = PreviewCapture(audio, args.standard)
    http_service = [None]
    http_error = ['']
    recording = [None]
    explicit_record_started = [False]
    rgb = queue.Queue(16)
    render_settings={'mode':(True,args.field_order or 'tff')}
    fullscreen=[False]
    last_pil=[None]; last_size=[None]
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
                stamp, generation, mode = metadata.get(timeout=2)
                display_drops[0] += put_latest(rgb, (bytes(data), width, height, stamp, generation, mode))
                converter['last_rgb'] = time.monotonic()
        except (OSError, ValueError, queue.Empty):
            return

    def convert():
        height = None; process = None; metadata = None; active_mode=None; active_generation=None
        try:
            while not closing.is_set():
                try:
                    data, actual, stamp, generation, second_stamp = source.frames.get(timeout=.1)
                except queue.Empty:
                    continue
                mode=render_settings['mode']
                if (actual != height or mode!=active_mode or generation!=active_generation
                        or process is None or process.poll() is not None):
                    stop_converter(); height = actual; width = 720
                    active_mode=mode; active_generation=generation
                    metadata = queue.Queue(32)
                    process = subprocess.Popen([ffmpeg, '-nostdin', '-hide_banner', '-loglevel', 'error',
                        '-f', 'rawvideo', '-pixel_format', 'uyvy422', '-video_size', f'720x{height}',
                        '-framerate', '25' if height == 576 else '30000/1001', '-i', 'pipe:0', '-an',
                        '-vf', rgb_filter(*mode), '-vsync', '0', '-pix_fmt', 'rgb24',
                        '-f', 'rawvideo', 'pipe:1'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=None, creationflags=subprocess.CREATE_NO_WINDOW)
                    converter['process'] = process
                    threading.Thread(target=read_rgb, args=(process, metadata, width, height), daemon=True).start()
                metadata.put((stamp, generation, mode), timeout=1)
                if mode[0]:
                    metadata.put((second_stamp, generation, mode),timeout=1)
                converter['last_input'] = time.monotonic()
                process.stdin.write(data); process.stdin.flush()
        except Exception as error:
            if not closing.is_set():
                converter['error'] = str(error)
                print(f'preview RGB worker: {error}', file=sys.stderr, flush=True)
        finally:
            stop_converter()

    source.start()
    if args.http:
        from windows_http import LiveHttpSource
        try:
            http_service[0] = LiveHttpSource(source, port=args.port, field_order=args.field_order,
                                           video_bitrate=args.video_bitrate, strict=args.strict_http)
            http_service[0].start()
        except Exception as error:
            http_error[0] = f'HTTP: {error}'
            print(f'HTTP startup failed: {error}', file=sys.stderr, flush=True)
    converter_thread = [threading.Thread(target=convert, daemon=True)]
    converter_thread[0].start()
    controls = tk.Frame(root, bg='#202020'); controls.pack(fill='x', padx=7, pady=(0, 6))
    normal_widgets.append(controls)
    selected = tk.StringVar(value=args.standard)
    choices = ('auto', 'pal', 'secam', 'ntsc', 'ntsc-j', 'ntsc-443', 'pal-m', 'pal-n', 'pal-nc', 'pal-60')
    ttk.Combobox(controls, textvariable=selected, values=choices, state='readonly', width=13).pack(side='left')

    def apply_standard():
        source.set_standard(selected.get())

    ttk.Button(controls, text='Применить', command=apply_standard).pack(side='left', padx=5)
    settings = tk.Frame(root, bg='#202020'); settings.pack(fill='x', padx=7, pady=(0, 5))
    normal_widgets.append(settings)
    order = tk.StringVar(value=args.field_order or 'tff')
    bitrate = tk.StringVar(value=str(args.video_bitrate))
    tk.Label(settings, text='Запись: поля', bg='#202020', fg='white').pack(side='left')
    ttk.Combobox(settings, textvariable=order, values=('tff','bff'), state='readonly', width=4).pack(side='left', padx=4)
    tk.Label(settings, text='Mbit/s', bg='#202020', fg='white').pack(side='left')
    ttk.Combobox(settings, textvariable=bitrate, values=tuple(map(str,range(8,13))), state='readonly', width=3).pack(side='left', padx=4)
    record_status = tk.StringVar(value='Запись выключена')
    record_label = tk.Label(settings, textvariable=record_status, bg='#202020', fg='white', anchor='w')
    record_label.pack(side='left', fill='x', expand=True, padx=5)
    options=tk.Frame(root,bg='#202020'); options.pack(fill='x',padx=7,pady=(0,5)); normal_widgets.append(options)
    auto_restart=tk.BooleanVar(value=True)
    deinterlace=tk.BooleanVar(value=True)
    preview_parity=tk.StringVar(value=args.field_order or 'tff')

    def update_render(*_):
        render_settings['mode']=(deinterlace.get(),preview_parity.get())

    def update_auto():
        if recording[0] and not recording[0].done.is_set():
            recording[0].auto_restart=auto_restart.get()

    ttk.Checkbutton(options,text='Автопродолжение записи после обрыва',variable=auto_restart,command=update_auto).pack(side='left')
    ttk.Checkbutton(options,text='Деинтерлейс превью',variable=deinterlace,command=update_render).pack(side='left',padx=8)
    parity_box=ttk.Combobox(options,textvariable=preview_parity,values=('tff','bff'),state='readonly',width=4)
    parity_box.pack(side='left'); parity_box.bind('<<ComboboxSelected>>',update_render)
    if http_service[0]:
        http_bar=tk.Frame(root,bg='#202020'); http_bar.pack(fill='x',padx=7,pady=(0,5)); normal_widgets.append(http_bar)
        http_url=f'http://127.0.0.1:{http_service[0].port}/live.ts'
        url_entry=ttk.Entry(http_bar,state='readonly',textvariable=tk.StringVar(value=http_url))
        url_entry.pack(side='left',fill='x',expand=True)
        def select_url(_):
            url_entry.selection_range(0,'end'); return 'break'
        url_entry.bind('<Control-a>',select_url)
        def copy_url():
            root.clipboard_clear(); root.clipboard_append(http_url)
        ttk.Button(http_bar,text='Копировать',command=copy_url).pack(side='right',padx=(5,0))

    def begin_record(path=None, seconds=0):
        if recording[0] and not recording[0].done.is_set():
            return
        if path is None:
            folder = ROOT/'build/recordings'; folder.mkdir(exist_ok=True)
            path = filedialog.asksaveasfilename(parent=root, title='Новая строгая запись',
                initialdir=str(folder), defaultextension='.ts', filetypes=[('MPEG-TS','*.ts'),('MPEG-PS','*.mpg')])
            if not path:
                return
        try:
            from recording_session import RecordingSession
            recording[0] = RecordingSession(source, path, field_order=order.get(), video_bitrate=int(bitrate.get()),
                                            seconds=seconds,auto_restart=auto_restart.get())
            recording[0].start()
        except Exception as error:
            record_status.set(str(error)); record_label.configure(fg='#ffaaaa')

    def end_record():
        if recording[0]:
            recording[0].stop()

    ttk.Button(controls, text='Строгая запись…', command=begin_record).pack(side='left', padx=4)
    ttk.Button(controls, text='Стоп записи', command=end_record).pack(side='left')

    def toggle_fullscreen(_=None):
        fullscreen[0]=not fullscreen[0]; root.attributes('-fullscreen',fullscreen[0])
        if fullscreen[0]:
            for widget in normal_widgets: widget.pack_forget()
        else:
            for widget in normal_widgets: widget.pack(fill='x',padx=7,pady=(0,5))
        return 'break'
    def escape(_):
        if fullscreen[0]: toggle_fullscreen()
        return 'break'
    ttk.Button(controls,text='Полный экран',command=toggle_fullscreen).pack(side='left',padx=4)
    picture.bind('<Double-Button-1>',toggle_fullscreen); root.bind('<F11>',toggle_fullscreen); root.bind('<Escape>',escape)

    def close():
        closing.set()
        if http_service[0]:
            http_service[0].stop()
        end_record()
        source.stop(); status.set('Ручная остановка. Восстановление USB…')
        process = converter['process']
        if process and process.poll() is None:
            process.terminate()  # RGB conversion only; never terminates USB owner.

    ttk.Button(controls, text='Остановить и закрыть', command=close).pack(side='right')
    root.protocol('WM_DELETE_WINDOW', close)
    names = {0: 'не определён', 1: 'PAL', 2: 'SECAM', 3: 'NTSC', 5: 'NTSC-J',
             6: 'NTSC-4.43', 7: 'PAL-M', 8: 'PAL-N', 9: 'PAL-Nc', 10: 'PAL-60'}
    pending = deque(maxlen=24)
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
                if item[4] == source.generation and item[5]==render_settings['mode']:
                    pending.append(item)
        except queue.Empty:
            pass
        if audio and not closing.is_set():
            try:
                audio.start_if_ready(); played = audio.position()
            except Exception as error:
                source.state['error'] = str(error); played = 0
        else:
            played = max(0, int((now - wall_epoch[0] - .2) * 48000))
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
            data, width, height, stamp, _, mode = chosen
            last_pil[0]=Image.frombytes('RGB',(width,height),data)
            last_frame[0] = now
        display_size=fit_4x3(picture.winfo_width(),picture.winfo_height())
        if last_pil[0] and (chosen is not None or display_size!=last_size[0]):
            scaled=last_pil[0].resize(display_size,Image.Resampling.BILINEAR)
            photo=ImageTk.PhotoImage(scaled)
            picture.itemconfigure(picture_id,image=photo); picture.image=photo
            last_size[0]=display_size
        picture.coords(picture_id,picture.winfo_width()/2,picture.winfo_height()/2)
        signal = source.signal
        detected = names.get(signal['detected'], '?') if signal else 'ожидание'
        lock = signal and signal['present'] and signal['hlock'] and signal['vlock']
        if not closing.is_set():
            if args.record and not explicit_record_started[0] and source.current_profile and signal:
                ready = signal['present'] and signal['hlock'] and signal['vlock']
                if source.standard == 'auto':
                    ready = ready and signal['detected'] == signal['selected']
                if ready:
                    explicit_record_started[0] = True
                    begin_record(args.record, args.record_seconds)
            if recording[0]:
                current = recording[0]
                if not current.done.is_set():
                    if current.state['phase']=='waiting':
                        record_status.set('Ожидание устойчивого сигнала · запись включена')
                    else:
                        count=current.engine.stats.video_frames if current.engine else 0
                        record_status.set(f"Часть {len(current.state['parts'])}: {count} кадров")
                    record_label.configure(fg='white')
                elif current.state['phase']=='failed':
                    record_status.set('Запись приостановлена: '+'; '.join(current.state['errors'][-1:]))
                    record_label.configure(fg='#ffaaaa')
                else:
                    record_status.set(f"Запись остановлена · частей: {len(current.state['parts'])}")
                    record_label.configure(fg='white')
            status.set(f"Режим: {source.standard.upper()}  |  Детектор: {detected}  |  H/V lock: {'да' if lock else 'нет'}"
                f"  |  {'LIVE' if now-last_frame[0] < 1 else 'Ожидание сигнала / полей'}\n"
                f"Исходник: 720×{source.state['height']} @ {source.state['rate']}, interlaced  |  Показ 4:3"
                f" · {'BWDIF 50p/59.94p' if deinterlace.get() else 'без деинтерлейса'}\n"
                f"Звук: {'PCM stereo 48 kHz; video follows audio clock' if audio else audio_error}\n"
                f"Кадров: {source.state['frames']}  |  Неполных для превью: {source.state['partial_frames']}"
                f"  |  Пропуски показа: {source.state['preview_drops']+display_drops[0]}\n"
                f"Смен формата: {source.state['geometry_changes']}  |  Восстановлений USB: {source.state['recoveries']}"
                f"  |  {source.state['error']}"
                + (f" | HTTP-клиентов: {http_service[0].broker.status()['clients']}"
                   f" | MPEG-TS частей: {http_service[0].parts}" if http_service[0] else http_error[0]))
            root.title(f"C039 LIVE A/V — {detected} — {source.state['height']} / {source.state['rate']}")
            picture.coords(hint_id,10,picture.winfo_height()-10)
            picture.itemconfigure(hint_id,text=(f"{detected} · 720×{source.state['height']} · {source.state['rate']}"
                f" · {'BWDIF' if deinterlace.get() else 'interlaced'} · Esc / F11" if fullscreen[0] else ''))
            picture.tag_raise(hint_id)
            if not converter_thread[0].is_alive() and now >= restart_after[0]:
                restart_after[0] = now + 1
                converter_thread[0] = threading.Thread(target=convert, daemon=True); converter_thread[0].start()
        if (closing.is_set() and source.done.is_set() and source.processed.is_set()
                and (not http_service[0] or http_service[0].done.is_set())
                and (not recording[0] or recording[0].done.is_set())):
            source.capture_thread.join(); source.process_thread.join()
            if audio:
                audio.close()
            root.destroy(); return
        root.after(10, refresh)

    refresh(); root.mainloop()


if __name__ == '__main__':
    main()
