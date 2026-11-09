# SPDX-License-Identifier: GPL-2.0-or-later
"""Fully decode a strict recording and reconcile frames, fields, PCM and timestamps."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from runtime_paths import ffmpeg_path


def verify(manifest, *, inspect_interrupted=False):
    manifest = Path(manifest)
    state = json.loads(manifest.read_text(encoding='utf-8'))
    interrupted = state.get('state') != 'captured-unverified' or state.get('return_code') != 0 or bool(state.get('errors'))
    if interrupted and not (inspect_interrupted and state.get('state') == 'failed'):
        raise ValueError('recording is incomplete/failed; refusing successful archival qualification')
    if state.get('time_policy')=='original-usb-pts-v2':
        from verify_timed_recording import verify_timed
        result=verify_timed(state)
        result.update(verified=not interrupted,retained_media_checks_passed=True,
                      continuity='interrupted' if interrupted else ('continuous' if result['full_source_continuity'] else 'gapped'),
                      source_errors=state.get('errors',[]))
        return result
    ffprobe = ffmpeg_path('ffprobe')
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
    audio_frames = [frame for frame in report['frames'] if frame['media_type'] == 'audio']
    samples = sum(frame['nb_samples'] for frame in audio_frames)
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
    audio_stamps = [float(frame['best_effort_timestamp_time']) for frame in audio_frames]
    if not stamps or not audio_stamps:
        raise ValueError('missing decoded audio/video timestamps')
    audio_elapsed = 0
    max_audio_pts_error = 0
    for frame, stamp in zip(audio_frames, audio_stamps):
        error = abs(stamp - audio_stamps[0] - audio_elapsed / 48000)
        max_audio_pts_error = max(max_audio_pts_error, error)
        if error > 1/90000 + 1e-6:
            raise ValueError('decoded audio timestamps do not preserve sample cadence')
        audio_elapsed += frame['nb_samples']
    # The qualified command/FFmpeg build produces 481 samples of MP2 delay.
    # The muxer translates both streams together; check that measured origin.
    priming_samples = (stamps[0] - audio_stamps[0]) * 48000
    if abs(priming_samples - 481) > 48000/90000 + .05:
        raise ValueError('encoded A/V origin differs from expected MP2 priming')
    return dict(verified=not interrupted, retained_media_checks_passed=True,
        continuity='interrupted' if interrupted else 'continuous', source_errors=state.get('errors', []),
        file=state['file'], full_decode=True, video_frames=len(frames),
        source_pcm_samples=expected_samples, decoded_audio_samples=samples, mp2_padding_samples=samples-expected_samples,
        native_geometry=f"720x{state['height']}", rate=state['rate'], field_order=state['field_order'],
        analog_lip_sync_calibrated=False, physical_field_dominance_calibrated=False,
        source_audio_samples=counters['source_audio_bytes']//4,
        video_clock_drift_us=counters['video_clock_drift_us'], audio_clock_drift_samples=counters['audio_clock_drift_samples'],
        video_duration_seconds=len(frames)*period, audio_pts_max_error_seconds=max_audio_pts_error,
        mp2_priming_samples=priming_samples, audio_pts_checked=True,
        video_pts_start=stamps[0], video_pts_last=stamps[-1],
        audio_pts_start=audio_stamps[0], audio_pts_last=audio_stamps[-1])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('--inspect-interrupted', action='store_true',
        help='check retained media of a failed part without qualifying it as an uninterrupted archive')
    args=parser.parse_args()
    print(json.dumps(verify(args.manifest, inspect_interrupted=args.inspect_interrupted),indent=2))


if __name__=='__main__':
    main()
