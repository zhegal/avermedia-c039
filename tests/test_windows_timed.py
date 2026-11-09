"""Continuous timestamp transport integration; synthetic USB only."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
import uuid
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tools')]
from windows_timed import TimedParser
from capture_stream import CaptureStream,StreamError


class Packets:
    height=576; num=25; den=1; per_frame=320
    gap=0; recover=False
    audio_extra_every=0
    def __init__(self,**options):
        self.options=options; self.stopped=threading.Event(); self.last_result=None; self.audio_index=0
    def audio(self):
        self.audio_index+=1
        extra=bool(self.audio_extra_every and self.audio_index%self.audio_extra_every==0)
        return b'\x10\0\xf0\xff'*(6+extra)
    def run(self):
        self.options['on_standard'](1,self.height,self.num,self.den)
        self.options['on_signal'](dict(present=1,hlock=1,vlock=1))
        stamp=1000000
        for frame in range(12):
            if frame==4:
                if self.gap or getattr(self,'pulse',False):
                    self.options['on_signal'](dict(present=0,hlock=0,vlock=0))
                if self.recover:
                    stamp+=self.gap
                    self.options['on_discontinuity']('native_end',[1])
                    self.options['on_discontinuity']('epoch',[2])
                else:
                    # Video lock is lost while USB and onboard PCM keep running.
                    for gap_packet in range(self.gap//125):
                        self.options['on_packet'](4,b'',stamp)
                        self.options['on_packet'](3,self.audio(),stamp); stamp+=125
                        # Yield between synthetic transfer groups instead of
                        # flooding fifteen seconds of input in 0.3 seconds.
                        if gap_packet%64==63: time.sleep(.001)
                self.options['on_standard'](2 if self.height==576 else 3,self.height,self.num,self.den)
                self.options['on_signal'](dict(present=1,hlock=1,vlock=1))
            raw=b''.join(b'\xff\0\0'+bytes([0x80 | field<<6])+bytes([32+frame*4+field])*1440
                         for field in (0,1) for _ in range(self.height//2))
            for n in range(self.per_frame):
                if self.stopped.is_set(): self.last_result=0; return 0
                self.options['on_packet'](4,raw[len(raw)*n//self.per_frame:len(raw)*(n+1)//self.per_frame],stamp)
                self.options['on_packet'](3,self.audio(),stamp); stamp+=125
        self.options['on_packet'](4,b'\xff\0\0\x80',stamp)
        self.options['on_packet'](3,b'\0'*24,stamp)
        self.last_result=0; return 0
    def stop(self): self.stopped.set()
    def close(self): pass


class ParserCases(unittest.TestCase):
    def test_record_can_arm_before_lock_without_waiting_for_three_frames(self):
        from recording_session import RecordingSession
        class Source:
            current_profile=(1,576,25,1); state={}; signal=None
        folder=ROOT/'build/timed-tests'/uuid.uuid4().hex; folder.mkdir(parents=True)
        session=RecordingSession(Source(),folder/'armed.ts',field_order='tff',diagnostics_dir=folder/'private')
        self.assertTrue(session._ready())
        self.assertFalse((folder/'armed.ts').exists())

    def test_positive_gap_is_preserved_and_backwards_pts_refused(self):
        engine=CaptureStream(container='mpegts',field_order='tff')
        captured=[]; events=[]
        parser=TimedParser(engine,lambda record,data:captured.append(record),events.append)
        parser.write(0,10000000,400000,b'x')
        parser.write(0,22400000,400000,b'y')
        self.assertEqual([r['pts'] for r in captured],[10000000,22400000])
        self.assertEqual(engine.stats.held_video_frames,0)
        self.assertEqual(parser.state['source_gap_events'],1)
        with self.assertRaisesRegex(StreamError,'backwards'): parser.write(0,22300000,400000,b'z')


@unittest.skipUnless(os.name=='nt' and (ROOT/'build/timestamp-ffmpeg/bin/ffmpeg.exe').exists() and shutil.which('ffprobe'),
                     'timestamp-aware FFmpeg build required')
class EncoderCases(unittest.TestCase):
    def record(self,factory=Packets,extension='.ts',field_order='tff'):
        from windows_recording import StrictRecording
        from verify_windows_recording import verify
        class Source:
            standard='auto'
            current_profile=(1,factory.height,factory.num,factory.den)
            session_factory=factory
        folder=ROOT/'build/timed-tests'/uuid.uuid4().hex; folder.mkdir(parents=True)
        recording=StrictRecording(Source(),folder/('capture'+extension),field_order=field_order,timestamped=True,
                                  diagnostics_dir=folder/'private')
        recording.start(); self.assertTrue(recording.done.wait(20))
        self.assertEqual(recording.state['state'],'captured-unverified',recording.state)
        report=verify(recording.manifest)
        return recording,report

    def test_ts_and_ps_keep_every_source_picture_and_pcm_sample(self):
        for extension in ('.ts','.mpg'):
            with self.subTest(extension=extension):
                recording,report=self.record(extension=extension)
                self.assertEqual(report['video_frames'],12)
                self.assertEqual(report['source_pcm_samples'],12*1920+6)
                self.assertTrue(report['timeline_preserved'])

    def test_pal_secam_positive_gap_one_file_no_wait_or_fake_frames(self):
        class Gap(Packets): gap=1200000
        for extension in ('.ts','.mpg'):
            recording,report=self.record(Gap,extension)
            self.assertEqual(report['video_frames'],12)
            self.assertFalse(report['full_source_continuity'])
            self.assertEqual(report['source_gap_events'],1)
            video=[json.loads(row) for row in Path(recording.engine.windows_status['timeline_path']).read_text().splitlines()
                   if '"stream": 0' in row]
            self.assertEqual(video[4]['pts'],23600000) # first recovered picture, no readiness delay
            self.assertEqual(len(list(recording.path.parent.glob('*'+extension))),1)
            pictures=subprocess.check_output(['ffmpeg','-nostdin','-v','error','-i',str(recording.path),
                '-map','0:v:0','-an','-fps_mode','passthrough','-pix_fmt','uyvy422','-f','rawvideo','pipe:1'])
            size=720*576*2
            self.assertEqual(len(pictures),12*size)
            # Confirm the first recovered picture's actual two fields, not just
            # a correct PTS attached to an old/repeated picture.
            for row,expected in ((288,48),(289,49)):
                value=pictures[4*size+row*1440+721]
                self.assertLessEqual(abs(value-expected),2)

    def test_native_epoch_recovery_retains_first_new_complete_picture(self):
        class Recovery(Packets): gap=2000000; recover=True
        recording,report=self.record(Recovery)
        self.assertEqual(report['video_frames'],11) # old final pair had no closing boundary before source ended
        self.assertEqual(recording.engine.windows_status['source_epochs'],1)
        rows=[json.loads(row) for row in Path(recording.engine.windows_status['timeline_path']).read_text().splitlines()]
        self.assertIn(31600000,[row['pts'] for row in rows if row.get('stream')==0])

    def test_long_positive_gap_is_not_compressed_by_encoder(self):
        class Gap(Packets): gap=15000000
        for extension in ('.ts','.mpg'):
            recording,report=self.record(Gap,extension)
            self.assertEqual(report['video_frames'],12)
            self.assertLess(report['video_pts_max_error_seconds'],1/90000+2e-6)

    def test_lock_loss_is_reported_even_if_device_keeps_complete_frames(self):
        class Pulse(Packets): pulse=True
        recording,report=self.record(Pulse)
        self.assertEqual(report['video_frames'],12)
        self.assertEqual(report['signal_loss_events'],1)
        self.assertEqual(report['source_gap_events'],0)
        self.assertFalse(report['full_source_continuity'])

    def test_variable_usb_pcm_packet_sizes_preserve_samples_and_pts(self):
        class Variable(Packets): audio_extra_every=640
        _,report=self.record(Variable)
        self.assertEqual(report['source_pcm_samples'],12*1920+6+6)
        self.assertLessEqual(report['audio_pts_max_error_seconds'],report['audio_pts_tolerance_seconds'])

    def test_offline_check_rejects_flattened_source_timeline(self):
        from verify_timed_recording import verify_timed
        class Gap(Packets): gap=1200000
        recording,_=self.record(Gap)
        state=json.loads(recording.manifest.read_text())
        original=Path(state['windows']['timeline_path'])
        rows=[json.loads(row) for row in original.read_text().splitlines()]
        video=[row for row in rows if row.get('stream')==0]
        for index,row in enumerate(video): row['pts']=video[0]['pts']+index*400000
        changed=original.with_name('flattened-fixture.jsonl')
        changed.write_text(''.join(json.dumps(row)+'\n' for row in rows))
        state['windows']['timeline_path']=str(changed)
        with self.assertRaisesRegex(ValueError,'picture PTS'): verify_timed(state)

    def test_cross_family_rolls_to_native_file_and_manual_stop_keeps_source(self):
        from windows_preview import PreviewCapture
        from recording_session import RecordingSession
        from test_windows_http import PacketPublisher
        from verify_windows_recording import verify
        source=PreviewCapture(None,enable_preview=False)
        source._publish(('profile',1,576,25,1))
        publisher=PacketPublisher(source,change_family=True)
        folder=ROOT/'build/timed-rollover-tests'/uuid.uuid4().hex; folder.mkdir(parents=True)
        session=RecordingSession(source,folder/'capture.ts',field_order='tff',diagnostics_dir=folder/'private')
        publisher.thread.start(); session.start()
        try:
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                if len(session.state['parts'])>=2 and session.current.engine.stats.video_frames>=5: break
                time.sleep(.05)
            self.assertGreaterEqual(len(session.state['parts']),2,session.state)
        finally:
            session.stop(); self.assertTrue(session.done.wait(10))
            publisher.stop.set(); publisher.thread.join(timeout=2)
        self.assertFalse(source.closing.is_set())
        states=[json.loads(Path(row['manifest']).read_text()) for row in session.state['parts']]
        self.assertEqual([row['height'] for row in states[:2]],[576,480])
        for row,entry in zip(states,session.state['parts']):
            result=verify(entry['manifest'],inspect_interrupted=row['state']=='failed')
            self.assertTrue(result['timeline_preserved'])

    def test_ntsc_preserves_480_native_rate_and_timestamps(self):
        class Ntsc(Packets): height=480; num=30000; den=1001; per_frame=267
        for extension in ('.ts','.mpg'):
            for order in ('tff','bff'):
                _,report=self.record(Ntsc,extension,order)
                self.assertEqual(report['native_geometry'],'720x480')
                self.assertEqual(report['rate'],'30000/1001')
                self.assertEqual(report['video_frames'],12)
