# SPDX-License-Identifier: GPL-2.0-or-later
"""Reconcile every decoded picture/audio PTS against admitted source metadata."""
import bisect
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from runtime_paths import ffmpeg_path


def verify_timed(state):
    windows=state['windows']
    records=[json.loads(line) for line in Path(windows['timeline_path']).read_text(encoding='utf8').splitlines()]
    video=[row for row in records if row.get('stream')==0]
    audio=[row for row in records if row.get('stream')==1]
    if not video or not audio: raise ValueError('empty timed source trace')
    initial_video_delay=max(0,(video[0]['pts']-windows['origin_100ns'])/10000000)
    # Arming before playback can legitimately produce audio before the first
    # image. Probe far enough to discover that image; still decode the full file.
    analyze_us=str(max(5000000,round((initial_video_delay+2)*1000000)))
    probe_bytes=str(min(Path(state['file']).stat().st_size,max(5000000,round(initial_video_delay*48000)+2000000)))
    result=subprocess.run([ffmpeg_path('ffprobe'),'-v','error','-err_detect','explode',
        '-analyzeduration',analyze_us,'-probesize',probe_bytes,'-show_frames','-show_streams',
        '-show_entries','stream=codec_name,width,height,r_frame_rate,field_order,display_aspect_ratio,sample_rate,channels,bit_rate:'
        'frame=media_type,best_effort_timestamp_time,interlaced_frame,top_field_first,nb_samples',
        '-of','json',state['file']],capture_output=True,text=True)
    if result.returncode or result.stderr.strip(): raise ValueError('full decode failed: '+result.stderr)
    decoded=json.loads(result.stdout)
    vf=[row for row in decoded['frames'] if row['media_type']=='video']
    af=[row for row in decoded['frames'] if row['media_type']=='audio']
    vs=next(row for row in decoded['streams'] if row['codec_name']=='mpeg2video')
    aus=next(row for row in decoded['streams'] if row['codec_name']=='mp2')
    if not video or not audio or not vf or not af: raise ValueError('empty timed recording')
    if len(video)!=len(vf) or len(vf)!=windows['written_video_frames'] or len(vf)!=state['capture']['video_frames']:
        raise ValueError('timed admitted/written/decoded picture count mismatch')
    samples=sum(row['samples'] for row in audio)
    decoded_samples=sum(row['nb_samples'] for row in af)
    if samples!=windows['written_audio_samples'] or samples*4!=state['capture']['audio_bytes']:
        raise ValueError('timed admitted/written PCM mismatch')
    if not samples<=decoded_samples<samples+1152: raise ValueError('timed decoded PCM/padding mismatch')
    if (vs.get('width'),vs.get('height'),vs.get('r_frame_rate'),vs.get('display_aspect_ratio'))!=(720,state['height'],state['rate'],'4:3'):
        raise ValueError('timed native geometry/rate/aspect mismatch')
    top=1 if state['field_order']=='tff' else 0
    if any(not row['interlaced_frame'] or row['top_field_first']!=top for row in vf):
        raise ValueError('timed field flags mismatch')
    if (aus['sample_rate'],aus['channels'],aus['bit_rate'])!=('48000',2,'256000'):
        raise ValueError('timed audio profile mismatch')
    if state['capture']['held_video_frames'] or state['capture']['dropped_video_frames']:
        raise ValueError('timed archive contains viewing cadence repair')
    origin=windows['origin_100ns']
    shift=float(vf[0]['best_effort_timestamp_time'])-(video[0]['pts']-origin)/10000000
    tolerance=1/90000+2e-6
    video_error=max(abs(float(frame['best_effort_timestamp_time'])-(packet['pts']-origin)/10000000-shift)
                    for frame,packet in zip(vf,video))
    if video_error>tolerance: raise ValueError(f'original picture PTS were changed: max {video_error}')
    positions=[]; cursor=0
    for row in audio: positions.append(cursor); cursor+=row['samples']
    cursor=0; audio_error=0
    for frame in af:
        index=bisect.bisect_right(positions,min(cursor,samples-1))-1
        source=(audio[index]['pts']-origin)/10000000+(cursor-positions[index])/48000
        error=abs(float(frame['best_effort_timestamp_time'])-(source-481/48000+shift))
        audio_error=max(audio_error,error); cursor+=frame['nb_samples']
    # PCM/encoder timestamps quantize to individual 48 kHz samples before the
    # common 90 kHz mux clock. Allow that quantization, never codec-frame gaps.
    audio_tolerance=tolerance+1/48000
    if audio_error>audio_tolerance: raise ValueError(f'original audio PTS were changed: max {audio_error}')
    gaps=[row for row in records if row.get('event') in ('video_gap','usb_packet_gap','pcm_missing','native_end','epoch','invalid_field_pair')]
    final=next((row.get('decoder',{}) for row in reversed(records) if row.get('event')=='final'),{})
    incomplete=windows.get('source_incomplete_pairs',0)+final.get('dropped_pairs',0)
    short_lines=windows.get('source_short_lines',0)+final.get('short_lines',0)
    return dict(verified=True,timeline_preserved=True,full_decode=True,file=state['file'],
        video_frames=len(vf),source_pcm_samples=samples,decoded_audio_samples=decoded_samples,
        mp2_padding_samples=decoded_samples-samples,source_gap_events=windows['source_gap_events'],
        full_source_continuity=not bool(gaps or incomplete or short_lines or windows.get('signal_loss_events',0)),source_events=len(gaps),
        signal_loss_events=windows.get('signal_loss_events',0),native_errors=windows.get('native_errors',0),
        source_incomplete_pairs=incomplete,source_short_lines=short_lines,
        video_pts_max_error_seconds=video_error,audio_pts_max_error_seconds=audio_error,
        audio_pts_tolerance_seconds=audio_tolerance,
        common_output_translation_seconds=shift,analog_lip_sync_calibrated=False,
        physical_field_dominance_calibrated=False,native_geometry=f"720x{state['height']}",rate=state['rate'])
