# SPDX-License-Identifier: GPL-2.0-or-later
"""Fully decode a strict recording and reconcile frames, fields, PCM and timestamps."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def verify(manifest):
    manifest = Path(manifest)
    state = json.loads(manifest.read_text(encoding='utf-8'))
    if state.get('state') != 'captured-unverified' or state.get('return_code') != 0 or state.get('errors'):
        raise ValueError('recording is incomplete/failed; refusing successful archival qualification')
    ffprobe = shutil.which('ffprobe')
    if not ffprobe:
        raise RuntimeError('ffprobe is required for full offline verification')
    result = subprocess.run([ffprobe, '-v', 'error', '-err_detect', 'explode', '-show_frames', '-show_streams',
        '-show_entries', 'stream=index,codec_name,width,height,r_frame_rate,field_order,display_aspect_ratio,sample_rate,channels,bit_rate:'
        'frame=media_type,best_effort_timestamp_time,interlaced_frame,top_field_first,nb_samples',
        '-of', 'json', state['file']], capture_output=True, text=True)
    if result.returncode or result.stderr.strip():
        raise ValueError('full decode failed: ' + result.stderr)
    report = json.loads(result.stdout)
    video = next(stream for stream in report['streams'] if stream['codec_name'] == 'mpeg2video')
    audio = next(stream for stream in report['streams'] if stream['codec_name'] == 'mp2')
    frames = [frame for frame in report['frames'] if frame['media_type'] == 'video']
    samples = sum(frame['nb_samples'] for frame in report['frames'] if frame['media_type'] == 'audio')
    counters = state['windows']
    expected_frames = counters['written_video_frames']
    expected_samples = counters['written_audio_samples']
    if len(frames) != expected_frames or expected_frames != counters['output_frames'] or expected_frames != state['capture']['video_frames']:
        raise ValueError('decoded/admitted/written picture counts differ')
    if state['capture']['held_video_frames'] or state['capture']['dropped_video_frames']:
        raise ValueError('a strict archive contains viewing cadence corrections')
    if (video['width'], video['height'], video['r_frame_rate']) != (720, state['height'], state['rate']):
        raise ValueError('encoded geometry or frame rate changed')
    if video['display_aspect_ratio'] != '4:3':
        raise ValueError('VHS display aspect metadata is not 4:3')
    top = 1 if state['field_order'] == 'tff' else 0
    if any(not frame['interlaced_frame'] or frame['top_field_first'] != top for frame in frames):
        raise ValueError('encoded field flags do not match the selected field order')
    if (audio['sample_rate'], audio['channels'], audio['bit_rate']) != ('48000', 2, '256000'):
        raise ValueError('encoded audio profile differs from 48 kHz stereo MP2 256k')
    numerator, denominator = map(int, state['rate'].split('/'))
    if expected_samples != expected_frames * 48000 * denominator // numerator:
        raise ValueError('source PCM duration does not match admitted video')
    # MP2 encodes integral 1152-sample frames; expose its final codec padding.
    if not expected_samples <= samples < expected_samples + 1152:
        raise ValueError('decoded PCM sample count exceeds one MP2 padding frame')
    stamps = [float(frame['best_effort_timestamp_time']) for frame in frames]
    period = denominator / numerator
    if any(abs(b-a-period) > 1/90000 + 1e-6 for a,b in zip(stamps, stamps[1:])):
        raise ValueError('decoded video timestamps are not one uninterrupted native cadence')
    return dict(verified=True, file=state['file'], full_decode=True, video_frames=len(frames),
        source_pcm_samples=expected_samples, decoded_audio_samples=samples, mp2_padding_samples=samples-expected_samples,
        native_geometry=f"720x{state['height']}", rate=state['rate'], field_order=state['field_order'],
        analog_lip_sync_calibrated=False, physical_field_dominance_calibrated=False,
        source_audio_samples=counters['source_audio_bytes']//4,
        video_clock_drift_us=counters['video_clock_drift_us'], audio_clock_drift_samples=counters['audio_clock_drift_samples'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    args=parser.parse_args()
    print(json.dumps(verify(args.manifest),indent=2))


if __name__=='__main__':
    main()
