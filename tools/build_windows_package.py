# SPDX-License-Identifier: GPL-2.0-or-later
"""Build an offline personal-test bundle/Setup without touching USB or drivers."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ffmpeg-dir', type=Path, required=True, help='qualified FFmpeg root with bin and LICENSE')
    parser.add_argument('--output', type=Path, required=True, help='new, nonexistent output directory')
    parser.add_argument('--iscc', type=Path)
    parser.add_argument('--version', default='0.1.0')
    parser.add_argument('--timestamp-ffmpeg',type=Path,default=ROOT/'build/timestamp-ffmpeg')
    parser.add_argument('--libusb-source', type=Path, required=True, help='official libusb v1.0.30 source archive')
    parser.add_argument('--libusb-license', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'\d+\.\d+\.\d+',args.version):
        parser.error('version must be MAJOR.MINOR.PATCH')
    output = args.output.resolve()
    if output.exists():
        parser.error('output already exists; use a new path (build never deletes existing output)')
    ffmpeg = args.ffmpeg_dir.resolve()
    binaries = [ROOT/'build'/name for name in ('c039-capture.dll','c039-probe.exe','libusb-1.0.dll')]
    binaries += [ffmpeg/'bin'/name for name in ('ffmpeg.exe','ffprobe.exe')]
    timed=args.timestamp_ffmpeg.resolve()
    for binary in binaries+[ffmpeg/'LICENSE',args.libusb_source,args.libusb_license,
                            timed/'bin/ffmpeg.exe',timed/'LICENSE',timed/'ffmpeg-5.1.2.tar.xz',timed/'provenance.json']:
        if not binary.is_file():
            parser.error('missing component: '+str(binary))
    output.mkdir(parents=True)
    licenses = output/'licenses'; licenses.mkdir()
    (output/'components').mkdir()
    shutil.copy2(timed/'bin/ffmpeg.exe',output/'components/ffmpeg-timestamps.exe')
    binaries.append(output/'components/ffmpeg-timestamps.exe')
    for name in ('LICENSE','NOTICE'):
        shutil.copy2(ROOT/name, licenses/name)
    shutil.copy2(ffmpeg/'LICENSE',licenses/'FFmpeg-LICENSE.txt')
    shutil.copy2(args.libusb_source,licenses/'libusb-1.0.30-source.tar.gz')
    shutil.copy2(args.libusb_license,licenses/'libusb-COPYING.txt')
    shutil.copy2(timed/'LICENSE',licenses/'FFmpeg-timestamps-LICENSE.txt')
    shutil.copy2(timed/'ffmpeg-5.1.2.tar.xz',licenses/'ffmpeg-timestamps-source.tar.xz')
    shutil.copy2(timed/'provenance.json',licenses/'ffmpeg-timestamps-provenance.json')
    shutil.copy2(Path(sys.base_prefix)/'LICENSE.txt',licenses/'Python-LICENSE.txt')
    for package in ('Pillow','PyInstaller'):
        distribution = importlib.metadata.distribution(package)
        for file in distribution.files or []:
            if ('license' in file.name.lower() or file.name.lower().startswith('copying')) and not str(file).endswith('.py'):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    shutil.copy2(source, licenses/(package+'-'+file.name))
    for name in ('tcl8.6','tk8.6'):
        source = Path(sys.base_prefix)/'tcl'/name/'license.terms'
        if source.exists(): shutil.copy2(source,licenses/(name+'-license.txt'))
    with zipfile.ZipFile(licenses/'C039-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        sources = list((ROOT/'src').glob('*'))+list((ROOT/'tools').glob('*.py'))+list((ROOT/'tools').glob('*.iss'))+list((ROOT/'tests').glob('*'))
        sources += list((ROOT/'docs').glob('*.md'))
        sources += list((ROOT/'references/ffmpeg').glob('*'))
        sources += [ROOT/'LICENSE',ROOT/'NOTICE',ROOT/'README.md',ROOT/'Makefile',
                    ROOT/'LICENSES/MIT.txt',ROOT/'references/linux-sources.json']
        for source in sources:
            if source.is_file() and (source.suffix in ('.py','.c','.h','.m','.md','.json','.iss','.txt','.patch') or source.name in ('LICENSE','NOTICE','Makefile')):
                archive.write(source,str(source.relative_to(ROOT)))
    readme = output/'TEST-BUILD.txt'
    readme.write_text(f'C039 Recorder {args.version} test build, Windows x64.\n'
        'Personal local evaluation; not a public release. Windows 10 and physical NTSC remain unqualified.\n'
        'No drivers/security settings are installed or changed. MI_01 must already use WinUSB\n'
        'with the application discovery GUID. Composite parent and MI_00 stay unchanged.\n'
        'Original AVerMedia packages are never removed. Driver recovery is an explicit separate\n'
        'maintenance operation; the existing machine-specific helper is not distributed here.\n'
        'Uninstall preserves recordings and LOCALAPPDATA/C039Recorder preferences/diagnostics.\n'
        'This executable/Setup is unsigned. No security bypass is required or provided.\n'
        'FFmpeg provenance is recorded in build-manifest.json; corresponding FFmpeg/dependency\n'
        'source and final notices must be completed before any public binary distribution.\n',encoding='utf8')
    command = [sys.executable,'-m','PyInstaller','--noconfirm','--onedir','--windowed','--noupx',
        '--name','C039Recorder','--distpath',str(output/'portable'),'--workpath',str(output/'work'),
        '--specpath',str(output),'--paths',str(ROOT/'src'),'--paths',str(ROOT/'tools')]
    for binary in binaries:
        command += ['--add-binary',str(binary)+os.pathsep+'bin']
    command += ['--add-data',str(licenses)+os.pathsep+'licenses',
                '--add-data',str(readme)+os.pathsep+'.',str(ROOT/'tools/windows_app.py')]
    with (output/'pyinstaller.log').open('w',encoding='utf8') as log:
        subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    app = output/'portable/C039Recorder'
    manifest = dict(version=args.version,qualification='personal-test',
        source_revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        source_worktree_dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),
        source_archive_sha256=hashlib.sha256((licenses/'C039-source.zip').read_bytes()).hexdigest(),
        python=sys.version, pyinstaller=importlib.metadata.version('PyInstaller'),
        pillow=importlib.metadata.version('Pillow'),driver_mutation=False,
        components=[dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in binaries],
        ffmpeg_version=subprocess.check_output([str(ffmpeg/'bin/ffmpeg.exe'),'-version'],text=True).splitlines()[0])
    (app/'build-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    with zipfile.ZipFile(output/'C039Recorder-portable.zip','w',zipfile.ZIP_DEFLATED) as archive:
        for file in app.rglob('*'):
            if file.is_file(): archive.write(file,str(file.relative_to(app.parent)))
    if args.iscc:
        subprocess.run([str(args.iscc.resolve()),'/DAppSource='+str(app),'/DPackageOutput='+str(output),
                        '/DPackageVersion='+args.version,
                        str(ROOT/'tools/windows_setup.iss')],check=True)
    print(str(output))


if __name__=='__main__':
    main()
