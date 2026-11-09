"""Retry hysteresis and byte-exact pre-roll without USB or desktop interaction."""
from pathlib import Path
import sys
import os
import shutil
import threading
import unittest
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from recording_session import RecordingSession
from windows_shared import SharedSession


class Source:
    standard='auto'; current_profile=(2,576,25,1); generation=1; enable_preview=True
    def __init__(self):
        self.state=dict(complete_frames=100,full_streak=100,last_complete_monotonic=100.)
        self.signal=dict(present=1,hlock=1,vlock=1,selected=2,detected=2)
        self.subscribers=set(); self.subscriptions=0; self.done=threading.Event()
        self.subscriber_lock=threading.Lock()
    def subscribe(self, consumer):
        self.subscriptions+=1; self.subscribers.add(consumer)
        return self.current_profile,self.signal,1000000
    def unsubscribe(self, consumer): self.subscribers.discard(consumer)


class RetryBufferTests(unittest.TestCase):
    @unittest.skipUnless(os.name=='nt' and shutil.which('ffmpeg') and shutil.which('ffprobe'), 'Windows/FFmpeg required')
    def test_two_second_preroll_survives_real_encoder_and_full_decode(self):
        from windows_recording import StrictRecording
        sys.path.insert(0,str(ROOT/'tools'))
        from verify_windows_recording import verify
        source=Source(); buffer=SharedSession(source,queue_capacity=768); buffer.prime()
        cursor=1000000; chunks=[[],[]]
        def packet(video):
            nonlocal cursor
            chunks[0].append(video); chunks[1].append(b'\x10\0\xf0\xff'*6)
            if len(chunks[0])==64:
                flush()
        def flush():
            nonlocal cursor
            count=len(chunks[0])
            for index,endpoint in enumerate((4,3)):
                offset=0; descriptors=[]
                for chunk in chunks[index]:
                    descriptors.append((offset,len(chunk),0)); offset+=len(chunk)
                buffer.offer(('batch',endpoint,b''.join(chunks[index]),tuple(descriptors),cursor))
            cursor+=count*125; chunks[0].clear(); chunks[1].clear()
        for frame in range(50):
            raw=b''.join(b'\xff\0\0'+bytes([0x80 | field<<6])+bytes([16+frame+field])*1440
                         for field in (0,1) for _ in range(288))
            for n in range(320): packet(raw[len(raw)*n//320:len(raw)*(n+1)//320])
        packet(b'\xff\0\0\x80'); flush()
        self.assertIsNone(buffer.failure)
        source.done.set()
        folder=ROOT/'build/retry-encode-tests'/uuid.uuid4().hex; folder.mkdir(parents=True)
        recording=StrictRecording(source,folder/'buffered.ts',field_order='tff',native_factory=buffer.factory,
                                  diagnostics_dir=folder/'private')
        recording.start(); self.assertTrue(recording.done.wait(15))
        result=verify(recording.manifest)
        self.assertEqual(result['video_frames'],50)
        self.assertEqual(result['source_pcm_samples'],96000)
        self.assertTrue(result['verified'])
        self.assertEqual(source.subscriptions,1)

    def test_seven_frame_recovery_is_rejected_then_stable_buffer_is_admitted(self):
        source=Source()
        folder=ROOT/'build/retry-tests'/uuid.uuid4().hex; folder.mkdir(parents=True)
        session=RecordingSession(source,folder/'record.ts',field_order='tff',diagnostics_dir=folder/'private')
        session.state['parts'].append(dict(file='previous interrupted part'))
        def frames(total,streak,now):
            source.state.update(complete_frames=total,full_streak=streak,last_complete_monotonic=now)
        with patch('recording_session.time.monotonic',return_value=100.):
            frames(103,103,100.)
            self.assertFalse(session._ready())
            first=session.retry
        with patch('recording_session.time.monotonic',return_value=100.28):
            frames(110,110,100.28)
            self.assertFalse(session._ready())
        # A partial frame then three complete frames can occur between polls.
        # A changed complete-frame sequence must still reset the whole gate.
        with patch('recording_session.time.monotonic',return_value=100.6):
            frames(113,3,100.6)
            self.assertFalse(session._ready())
            self.assertTrue(first.stopped.is_set())
            self.assertIsNot(first,session.retry)
        with patch('recording_session.time.monotonic',return_value=102.65):
            frames(165,55,102.65)
            self.assertTrue(session._ready())
            self.assertFalse(session.retry.buffering)
            session.retry.offer(('signal',dict(present=0,hlock=0,vlock=0)))
            self.assertIsNone(session.retry.failure)
        self.assertEqual(session.state['retry_rejections'],1)
        self.assertEqual(list(folder.glob('*.ts')),[])
        self.assertEqual(len(source.subscribers),1)
        session._discard_retry('test manual disarm')
        self.assertFalse(source.subscribers)

    def test_short_lock_loss_between_polls_and_buffer_budget_are_not_ignored(self):
        source=Source(); buffer=SharedSession(source,queue_capacity=768); buffer.prime()
        buffer.offer(('signal',dict(present=0,hlock=0,vlock=0)))
        buffer.offer(('signal',source.signal))
        self.assertIsNotNone(buffer.failure)
        buffer.close()
        buffer=SharedSession(source,queue_capacity=768); buffer.prime()
        buffer.buffer_bytes=96*1024*1024
        buffer.offer(('batch',4,b'x',((0,1,0),),1000000))
        self.assertIn('byte budget',str(buffer.failure))
        buffer.close(); self.assertFalse(source.subscribers)

    def test_admission_replays_earliest_packet_bytes_and_timestamps_once(self):
        source=Source(); buffer=SharedSession(source,queue_capacity=768); buffer.prime()
        items=[(4,b'first video',((0,11,0),),1000000),
               (3,b'first audio',((0,11,0),),1000000)]
        for values in items: buffer.offer(('batch',*values))
        captured=[]
        def receive(*values):
            captured.append(values)
            if len(captured)==2: buffer.stopped.set()
        native=buffer.factory(on_standard=lambda *args:None,on_batch=receive,seconds=0)
        self.assertEqual(native.run(),0)
        self.assertEqual(captured,items)
        self.assertEqual(source.subscriptions,1)
        self.assertFalse(source.subscribers)
