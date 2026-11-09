# SPDX-License-Identifier: GPL-2.0-or-later
"""Build an app-local LGPL FFmpeg with the reference original-PTS transport."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
SOURCE_SHA='619e706d662c8420859832ddc259cd4d4096a48a2ce1eefd052db9e440eef3dc'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--toolchain',type=Path,required=True)
    parser.add_argument('--source-archive',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'build/timestamp-ffmpeg')
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args(); output=args.output.resolve(); toolchain=args.toolchain.resolve()
    if output.exists() and not args.resume: parser.error('output exists; use --resume explicitly or choose a new directory')
    output.mkdir(parents=True,exist_ok=args.resume)
    archive=output/'ffmpeg-5.1.2.tar.xz'
    if args.source_archive and not archive.exists():
        shutil.copy2(args.source_archive,archive)
    elif not archive.exists():
        urllib.request.urlretrieve('https://ffmpeg.org/releases/ffmpeg-5.1.2.tar.xz',archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=SOURCE_SHA:
        raise RuntimeError('FFmpeg source hash mismatch')
    if not (output/'ffmpeg-5.1.2/configure').exists():
        with tarfile.open(archive) as source: source.extractall(output,filter='data')
    source=output/'ffmpeg-5.1.2'
    encoder=source/'libavcodec/mpeg12enc.c'
    text=encoder.read_text()
    old='AVRational target = av_inv_q(s->avctx->time_base);'
    if old not in text and 'FFMAX(s->avctx->ticks_per_frame, 1)' not in text: raise RuntimeError('Unexpected MPEG-2 source')
    encoder.write_text(text.replace(old,'AVRational target = av_inv_q(av_mul_q(s->avctx->time_base, (AVRational){ FFMAX(s->avctx->ticks_per_frame, 1), 1 }));'))
    shutil.copy2(ROOT/'references/ffmpeg/vhsts.c',source/'libavformat/vhsts.c')
    registry=source/'libavformat/allformats.c'
    if 'ff_vhsts_muxer' not in registry.read_text():
        registry.write_text(registry.read_text().replace('#include "libavformat/muxer_list.c"',
            'extern const AVInputFormat ff_vhsts_demuxer;\nextern const AVOutputFormat ff_vhsts_muxer;\n#include "libavformat/muxer_list.c"'))
    if 'CONFIG_VHSTS_DEMUXER' not in (source/'libavformat/Makefile').read_text():
        with (source/'libavformat/Makefile').open('a') as target:
            target.write('\nOBJS-$(CONFIG_VHSTS_DEMUXER) += vhsts.o\nOBJS-$(CONFIG_VHSTS_MUXER) += vhsts.o\n')
    (output/'tmp').mkdir(exist_ok=True)
    env=dict(os.environ,PATH=str(toolchain)+os.pathsep+os.environ.get('PATH',''),TMPDIR=(output/'tmp').as_posix())
    flags=['--target-os=mingw32','--arch=x86_64','--disable-autodetect','--disable-everything',
        '--disable-doc','--disable-debug','--disable-network','--disable-asm','--enable-ffmpeg','--enable-ffprobe',
        '--enable-indev=lavfi','--enable-encoder=mpeg2video,mp2,rawvideo,pcm_s16le',
        '--enable-decoder=mpeg2video,mp2,rawvideo,pcm_s16le',
        '--enable-muxer=vhsts,mpeg1system,mpegts,rawvideo,pcm_s16le,null,framehash',
        '--enable-demuxer=vhsts,mpegts,mpegps,mpegvideo,rawvideo,pcm_s16le',
        '--enable-parser=mpegvideo,mpegaudio','--enable-protocol=file,pipe',
        '--enable-filter=scale,format,setfield,bwdif,setpts,setsar,aresample,aformat,null,anull,anullsrc,testsrc2,sine',
        '--enable-swscale','--enable-swresample','--extra-version=c039-timestamps-v2',
        '--extra-cflags=-Wno-error=incompatible-pointer-types']
    with (output/'build.log').open('a') as log:
        commands=[]
        if 'vhs_pts' not in (source/'libavformat/mpegenc.c').read_text():
            commands.append([str(toolchain/'patch.exe'),'-p1','-i',str(ROOT/'references/ffmpeg/mpeg_pts.patch')])
        commands += [[str(toolchain/'sh.exe'),'./configure',*flags],[str(toolchain/'make.exe'),'-j2','V=1']]
        for command in commands:
            subprocess.run(command,cwd=source,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    (output/'bin').mkdir(exist_ok=True)
    for name in ('ffmpeg.exe','ffprobe.exe'): shutil.copy2(source/name,output/'bin'/name)
    shutil.copy2(source/'COPYING.LGPLv2.1',output/'LICENSE')
    (output/'provenance.json').write_text(json.dumps(dict(source_sha256=SOURCE_SHA,configure=flags,
        vhsts_sha256=hashlib.sha256((ROOT/'references/ffmpeg/vhsts.c').read_bytes()).hexdigest(),
        binaries={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (output/'bin').iterdir()}),indent=2))
    print(output)


if __name__=='__main__': main()
