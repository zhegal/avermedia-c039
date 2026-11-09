# SPDX-License-Identifier: GPL-2.0-or-later
"""Build the experimental x64 USB preflight and portable tests; never install drivers."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cc', required=True, help='path to x64 MinGW GCC, Clang or Zig')
    parser.add_argument('--libusb', required=True, type=Path, help='extracted official libusb Windows archive')
    args = parser.parse_args()
    usb = args.libusb.resolve()
    library = usb / 'MinGW64/static/libusb-1.0.dll.a'
    dll = usb / 'MinGW64/dll/libusb-1.0.dll'
    header = usb / 'include/libusb.h'
    for path in (library, dll, header):
        if not path.is_file():
            parser.error(f'missing dependency: {path}')
    compiler = [str(Path(args.cc).resolve())]
    if Path(args.cc).stem.lower() == 'zig':
        compiler += ['cc', '-target', 'x86_64-windows-gnu']
    # Zig's optimized C mode defines NDEBUG; keep assertion-based tests active.
    flags = ['-std=c11', '-O2', '-UNDEBUG', '-Wall', '-Wextra', '-Werror', '-Isrc', '-I' + str(usb / 'include')]
    (ROOT / 'build').mkdir(exist_ok=True)

    def build(output, sources, extra=()):
        subprocess.run(compiler + flags + list(sources) + list(extra) + ['-o', 'build/' + output], cwd=ROOT, check=True)

    build('c039-probe.exe', ['src/windows_probe.c', 'src/usb_libusb.c', 'src/av_init.c', 'src/video_standard.c'], [str(library)])
    build('c039-driver.exe', ['src/windows_driver.c'], ['-lsetupapi'])
    shutil.copy2(dll, ROOT / 'build/libusb-1.0.dll')
    build('c039-frame.dll', ['src/frame_decoder.c'], ['-shared'])
    for name, sources in (
        ('test-av-init', ['tests/test_av_init.c', 'src/av_init.c', 'src/video_standard.c']),
        ('test-native-frame', ['tests/test_frame_decoder.c', 'src/frame_decoder.c']),
        ('test-usb-libusb', ['tests/test_usb_libusb.c', 'src/usb_libusb.c']),
    ):
        build(name + '.exe', sources)
        subprocess.run([str(ROOT / 'build' / (name + '.exe'))], cwd=ROOT, check=True)
    subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'], cwd=ROOT, check=True)


if __name__ == '__main__':
    main()
