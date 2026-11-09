#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build a local AppKit/AVAudioEngine viewer; no paid signing or installation."""
from pathlib import Path
import plistlib
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def main():
    app = ROOT / 'build/C039Preview.app'
    binary = app / 'Contents/MacOS/C039Preview'
    binary.parent.mkdir(parents=True, exist_ok=True)
    objects = ROOT / 'build/preview-objects'
    objects.mkdir(exist_ok=True)
    files = []
    for name in ('capture_device', 'av_init', 'iso_probe', 'video_standard', 'frame_decoder', 'preview_audio'):
        target = objects / (name + '.o')
        subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Wno-deprecated-declarations',
                        '-mmacosx-version-min=12.3', '-I', str(ROOT / 'src'), '-c',
                        str(ROOT / 'src' / (name + '.c')), '-o', str(target)], check=True)
        files.append(str(target))
    subprocess.run(['swiftc', '-swift-version', '5', '-O', '-target', 'arm64-apple-macos12.3',
        '-parse-as-library', '-import-objc-header', str(ROOT / 'preview/Bridge.h'), '-I', str(ROOT / 'src'),
        str(ROOT / 'preview/Preview.swift'), *files, '-framework', 'IOKit', '-framework', 'CoreFoundation',
        '-framework', 'AppKit', '-framework', 'AVFoundation', '-framework', 'CoreImage',
        '-framework', 'CoreVideo', '-o', str(binary)], check=True)
    info = dict(CFBundleExecutable='C039Preview', CFBundleIdentifier='io.github.zhegal.C039.Preview',
        CFBundleName='AVerMedia C039 Preview', CFBundlePackageType='APPL',
        CFBundleShortVersionString='0.2.0', CFBundleVersion='1', NSPrincipalClass='NSApplication',
        LSMinimumSystemVersion='12.3', NSHighResolutionCapable=True)
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps(info))
    subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True)
    print(binary)


if __name__ == '__main__':
    main()
