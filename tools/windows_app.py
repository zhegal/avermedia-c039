# SPDX-License-Identifier: GPL-2.0-or-later
"""Frozen desktop entry point and hardware-free installation self-test."""
import argparse
import ctypes
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'tools')]
from runtime_paths import binary_path, diagnostics_root, ffmpeg_path


def device_status():
    import winreg
    devices = []
    base = r'SYSTEM\CurrentControlSet\Enum\USB\VID_07CA&PID_C039&MI_01'
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as key:
            for index in range(winreg.QueryInfoKey(key)[0]):
                instance = winreg.EnumKey(key, index)
                with winreg.OpenKey(key, instance) as device:
                    try:
                        service = winreg.QueryValueEx(device, 'Service')[0]
                    except FileNotFoundError:
                        service = ''
                    try:
                        with winreg.OpenKey(device, 'Device Parameters') as parameters:
                            guids = winreg.QueryValueEx(parameters, 'DeviceInterfaceGUIDs')[0]
                    except FileNotFoundError:
                        guids = []
                    devices.append(dict(instance=instance, service=service,
                        winusb_configured=service.lower()=='winusb' and
                        '{DC5D64D5-1DDB-4B6F-80CB-3472927954AE}' in [g.upper() for g in guids]))
    except FileNotFoundError:
        pass
    return dict(registry_instances=devices, physical_presence_checked=False,
                driver_changed=False)


def self_test(folder):
    import tkinter
    from PIL import Image, ImageTk
    from video_standards import NAMES
    import windows_recording, recording_session, windows_http, windows_audio
    ctypes.CDLL(str(binary_path('c039-capture.dll'))).c039_session_create
    tk = tkinter.Tk(); tk.withdraw()
    ImageTk.PhotoImage(Image.new('RGB', (4, 4)), master=tk)
    tk.update_idletasks(); tk.destroy()
    ffmpeg, ffprobe = ffmpeg_path(), ffmpeg_path('ffprobe')
    media = folder/'self-test.ts'
    subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i',
        'testsrc2=size=720x576:rate=25', '-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=stereo',
        '-t', '0.4', '-vf', 'setfield=tff', '-c:v', 'mpeg2video', '-pix_fmt', 'yuv422p',
        '-b:v', '12M', '-flags', '+ilme+ildct', '-alternate_scan', '1', '-aspect', '4:3',
        '-c:a', 'mp2', '-b:a', '256k', '-f', 'mpegts', str(media)], check=True,
        stdout=subprocess.DEVNULL, stderr=sys.stderr, creationflags=subprocess.CREATE_NO_WINDOW)
    subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-xerror', '-i', str(media),
        '-vf', 'bwdif=mode=send_field:parity=tff:deint=all', '-f', 'null', 'NUL'],
        check=True, stdout=subprocess.DEVNULL, stderr=sys.stderr, creationflags=subprocess.CREATE_NO_WINDOW)
    result = subprocess.check_output([ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(media)],
        creationflags=subprocess.CREATE_NO_WINDOW)
    streams = json.loads(result)['streams']
    video, audio = streams
    native_log = 'native_log_redirected=yes' in (folder/'application.log').read_text(encoding='utf-8',errors='replace')
    if not native_log:
        raise RuntimeError('Native C diagnostics are missing from application log')
    if (video['codec_name'],video['width'],video['height'],video['display_aspect_ratio']) != ('mpeg2video',720,576,'4:3'):
        raise RuntimeError('Bundled video profile self-test failed')
    if (audio['codec_name'],audio['sample_rate'],audio['channels']) != ('mp2','48000',2):
        raise RuntimeError('Bundled audio profile self-test failed')
    from windows_timed import transport_header,packet_header,mux_command
    from capture_stream import CaptureStream
    timed=folder/'self-test-timed.vhst'
    with timed.open('xb') as stream:
        stream.write(transport_header(576,25,1,'tff',0))
        for pts in (0,10000000):
            picture=b'\x80\x20\x80\x20'*(720*576//2)
            pcm=b'\0'*(1920*4)
            for index,data in ((0,picture),(1,pcm)):
                stream.write(packet_header(index,pts,400000,len(data))); stream.write(data)
    timed_media=folder/'self-test-timed.ts'
    with timed_media.open('xb') as target:
        subprocess.run(mux_command(CaptureStream(container='mpegts',field_order='tff'),str(timed)),
            stdout=target,stderr=sys.stderr,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    timed_probe=json.loads(subprocess.check_output([ffprobe,'-v','error','-select_streams','v:0',
        '-show_frames','-show_entries','frame=best_effort_timestamp_time','-of','json',str(timed_media)],
        creationflags=subprocess.CREATE_NO_WINDOW))
    frames=timed_probe['frames']
    if len(frames)!=2 or abs(float(frames[1]['best_effort_timestamp_time'])-float(frames[0]['best_effort_timestamp_time'])-1)>1/90000:
        raise RuntimeError('Bundled timestamp encoder changed frame count or gap')
    return dict(passed=True, usb_opened=False, audio_device_opened=False,
                tk_pillow=True, native_dll=True, native_c_log=True, standards=list(NAMES),
                bundled_encode_decode=True, original_pts_gap=True, bwdif=True, device=device_status())


def main():
    folder = diagnostics_root()/'Application'/str(time.time_ns())
    folder.mkdir(parents=True)
    log_path = folder/'application.log'
    log = log_path.open('a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = log
    # Python redirection alone misses fprintf(stderr) from a windowed C DLL.
    # Keep both handles append-only so neither overwrites the other's diagnostics.
    native = ctypes.CDLL(str(binary_path('c039-capture.dll')))
    native.c039_windows_set_log_path.argtypes = [ctypes.c_wchar_p]
    native.c039_windows_set_log_path.restype = ctypes.c_int
    if native.c039_windows_set_log_path(str(log_path)):
        print('Native diagnostic redirection failed',file=log,flush=True)
    if '--self-test' in sys.argv or '--device-status' in sys.argv:
        parser = argparse.ArgumentParser()
        parser.add_argument('--self-test', action='store_true')
        parser.add_argument('--device-status', action='store_true')
        parser.add_argument('--report', type=Path, required=True)
        args = parser.parse_args()
        try:
            result = self_test(folder) if args.self_test else device_status()
            code = 0
        except Exception as error:
            import traceback
            traceback.print_exc()
            result = dict(passed=False,error=str(error),diagnostics=str(folder)); code = 1
        args.report.write_text(json.dumps(result,indent=2),encoding='utf-8')
        return code
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]
    kernel.CreateMutexW.restype = ctypes.c_void_p
    mutex = kernel.CreateMutexW(None, False, r'Local\C039Recorder.App')
    if not mutex or ctypes.get_last_error()==183:
        ctypes.windll.user32.MessageBoxW(None,'C039 Recorder уже запущен.','C039 Recorder',0x40)
        return 1
    try:
        from preview_windows_direct import main as preview
        sys.argv = [sys.argv[0],'--standard','auto','--http','--field-order','tff','--video-bitrate','12']
        preview()
        return 0
    except Exception as error:
        import traceback
        traceback.print_exc()
        ctypes.windll.user32.MessageBoxW(None,str(error)+'\n\nДиагностика: '+str(folder),'C039 Recorder',0x10)
        return 1
    finally:
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    raise SystemExit(main())
