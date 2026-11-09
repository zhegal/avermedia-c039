# SPDX-License-Identifier: GPL-2.0-or-later
"""Continuous original-USB-PTS recording; no cadence repair or source ownership."""
import json
from pathlib import Path
import queue
import struct
import subprocess
import threading

from bt656 import Decoder
from capture_stream import PacketWindow, StreamError
from runtime_paths import timestamp_ffmpeg_path
from windows_pipe import PipeWriter


def transport_header(height, numerator, denominator, field_order, origin):
    return struct.pack('<8s8Iq',b'VHST0002',720,height,numerator,denominator,48000,2,
                       1 if field_order=='tff' else 2,1,origin)


def packet_header(stream, pts, duration, size):
    return struct.pack('<4sIqqII',b'PKT1',stream,pts,duration,size,0)


def mux_command(engine, pipe):
    num,den=map(int,engine.rate.split('/'))
    command=[timestamp_ffmpeg_path(),'-nostdin','-hide_banner','-loglevel','warning',
        '-copyts','-thread_queue_size','64','-f','vhsts','-probesize','32','-analyzeduration','0','-i',pipe,
        '-map','0:v:0','-map','0:a:0','-vf','setfield='+engine.field_order,
        '-c:v','mpeg2video','-pix_fmt','yuv422p','-b:v',f'{engine.video_bitrate}M',
        '-flags','+ilme+ildct+low_delay','-alternate_scan','1','-g','12','-bf','0','-aspect','4:3',
        '-fps_mode','passthrough','-enc_time_base:v','1:90000','-ticks_per_frame:v',str(90000*den//num),
        '-c:a','mp2','-b:a','256k','-ar','48000','-ac','2','-avoid_negative_ts','make_non_negative',
        '-max_interleave_delta','100000','-muxdelay','0','-muxpreload','0']
    command += (['-vhs_pts','1'] if engine.container=='mpeg' else
                ['-mpegts_flags','+pat_pmt_at_frames','-omit_video_pes_length','0'])
    return command+['-flush_packets','1','-f',engine.container,'pipe:1']


class TimedParser:
    """Runs on a subscription worker, never in the native USB callback."""
    def __init__(self,engine,submit,event):
        self.engine,self.submit,self.event=engine,submit,event
        self.num,self.den=map(int,engine.rate.split('/'))
        self.period=10000000*self.den/self.num
        self.last_pts=[None,None]; self.last_packet=[None,None]
        self.origin=None
        self.signal_key=None; self.signal_locked=None
        self.packet_cache={3:[],4:[]}
        self.state=engine.windows_status=dict(time_policy='original-usb-pts-v2',origin_100ns=None,
            output_frames=0,written_video_frames=0,written_audio_samples=0,source_audio_bytes=0,
            source_gap_events=0,source_packet_errors=0,source_epochs=0,events=[],
            invalid_field_pairs=0,
            source_incomplete_pairs=0,source_short_lines=0,missing_pcm_packets=0,
            signal_loss_events=0,native_errors=0,
            first_video_usb_us=None,last_video_usb_us=None,first_audio_usb_us=None,last_audio_usb_us=None,
            video_clock_drift_us=None,audio_clock_drift_samples=None,pipe_errors=[])
        self.reset_video()

    def note(self,kind,**values):
        record=dict(event=kind,**values)
        self.state['events'].append(record); del self.state['events'][:-64]
        self.event(record)

    def reset_video(self):
        if hasattr(self,'decoder'):
            self.state['source_incomplete_pairs']+=self.decoder.dropped_pairs
            self.state['source_short_lines']+=self.decoder.short_lines
        self.window=PacketWindow(); self.offset=0; self.decoded=[]
        self.decoder=Decoder(720,self.engine.height,self.decoded.append,self.frame)
        self.last_packet[0]=None

    def discontinuity(self,kind,values):
        self.finish()
        self.state['source_epochs']+=kind=='epoch'
        self.state['native_errors']+=int(kind=='native_end' and bool(values and values[0]))
        self.note(kind,details=values,decoder=self.decoder.summary())
        self.reset_video(); self.last_packet[1]=None

    def signal(self,value):
        self.engine.latest_signal=value
        key=tuple(sorted(value.items()))
        if key==self.signal_key: return
        locked=all(value.get(name) for name in ('present','hlock','vlock'))
        if not locked and self.signal_locked is not False:
            self.state['signal_loss_events']+=1
        self.signal_key=key; self.signal_locked=locked
        self.note('signal',signal=value)

    def standard(self,profile,height,num,den):
        if (height,num,den)!=(self.engine.height,self.num,self.den):
            raise StreamError('native geometry/rate family changed; ending fixed-format stream without scaling')
        self.note('standard',profile=profile,height=height,numerator=num,denominator=den)

    def write(self,stream,pts,duration,data,**metadata):
        previous=self.last_pts[stream]
        if previous is not None and pts<=previous:
            raise StreamError('source PTS reset/backwards; refusing silent timeline rebase')
        if stream==0 and previous is not None and pts-previous>self.period+10000:
            self.state['source_gap_events']+=1
            self.note('video_gap',previous_pts=previous,pts=pts,extra_100ns=pts-previous-round(self.period))
        self.last_pts[stream]=pts
        record=dict(stream=stream,pts=pts,duration=duration,bytes=len(data),**metadata)
        if stream==1: record['samples']=len(data)//4
        self.submit(record,data)
        if stream==0:
            self.engine.stats.video_frames+=1; self.state['output_frames']+=1
            if self.state['first_video_usb_us'] is None: self.state['first_video_usb_us']=pts/10
            self.state['last_video_usb_us']=pts/10
        else:
            self.engine.stats.audio_bytes+=len(data); self.state['source_audio_bytes']+=len(data)
            if self.state['first_audio_usb_us'] is None: self.state['first_audio_usb_us']=pts/10
            self.state['last_audio_usb_us']=pts/10

    def frame(self,index,field1,field2):
        data=self.decoded.pop()
        pts=round(self.window.byte_time(field1)*10)
        second=round(self.window.byte_time(field2)*10)
        # Preserve source phase jitter. Reject only fields spanning more than
        # an entire nominal frame, rather than imposing a 1 ms field filter.
        if second<=pts or second-pts>self.period:
            self.state['invalid_field_pairs']+=1
            self.note('invalid_field_pair',first_pts=pts,second_pts=second)
            return
        self.write(0,pts,round(self.period),data,second_field_pts=second)

    def packet(self,endpoint,data,stamp):
        if endpoint not in self.packet_cache: raise StreamError('unexpected USB endpoint')
        cached=self.packet_cache[endpoint]
        if cached and stamp-cached[-1][1]!=125: self.flush_packets(endpoint)
        cached.append((data,stamp))
        if len(cached)==64: self.flush_packets(endpoint)

    def flush_packets(self,endpoint):
        cached=self.packet_cache[endpoint]
        if not cached: return
        offset=0; descriptors=[]
        for payload,_ in cached:
            descriptors.append((offset,len(payload),0)); offset+=len(payload)
        data=b''.join(item[0] for item in cached); stamp=cached[0][1]; cached.clear()
        self.batch(endpoint,data,descriptors,stamp)

    def finish(self):
        self.flush_packets(4); self.flush_packets(3)

    def batch(self,endpoint,data,descriptors,stamp):
        if self.engine.errors: return
        if endpoint not in (3,4): raise StreamError('unexpected USB endpoint')
        if self.origin is None:
            self.origin=round(stamp*10); self.state['origin_100ns']=self.origin
        audio=bytearray(); audio_start=None; missing_pcm=0
        def release_audio():
            nonlocal audio,audio_start
            if audio:
                self.write(1,round(audio_start*10),round(len(audio)//4*10000000/48000),bytes(audio))
                audio.clear(); audio_start=None
        for n,(offset,length,status) in enumerate(descriptors):
            current=stamp+n*125; index=0 if endpoint==4 else 1
            if endpoint==4: self.engine.stats.video_packets+=1
            else: self.engine.stats.audio_packets+=1
            invalid=status or offset+length>len(data) or (endpoint==3 and length%4)
            previous=self.last_packet[index]
            if invalid or (previous is not None and current-previous!=125):
                if endpoint==4: self.reset_video()
                else: release_audio()
                self.state['source_packet_errors']+=bool(invalid)
                self.note('usb_packet_gap',endpoint=endpoint,previous_us=previous,usb_us=current,status=status)
            self.last_packet[index]=current
            if invalid: continue
            payload=data[offset:offset+length]
            if endpoint==4:
                self.window.add_packet(self.offset,length,current); self.offset+=length
                self.decoder.feed(payload)
            elif length:
                if audio_start is None: audio_start=current
                audio.extend(payload)
            else:
                release_audio()
                missing_pcm+=1
        release_audio()
        if missing_pcm:
            self.state['missing_pcm_packets']+=missing_pcm
            self.note('pcm_missing',usb_us=stamp,packets=missing_pcm)


def run_timed(engine,output,log_path,*,native_factory):
    """One encoder/file across positive gaps; bounded EOF drain on manual Stop."""
    log_path=Path(log_path); log_path.parent.mkdir(parents=True,exist_ok=True)
    timeline=log_path.with_name('timeline.jsonl')
    media=queue.Queue(256); done=threading.Event(); capture_done=threading.Event()
    byte_lock=threading.Lock(); queued_bytes=[0]
    pipe=PipeWriter(); threads=[]; parser=None
    with log_path.open('w',encoding='utf8') as log, timeline.open('x',encoding='utf8',buffering=1) as trace:
        def event(record):
            trace.write(json.dumps(record)+'\n')
        def submit(record,data):
            with byte_lock:
                if queued_bytes[0]+len(data)>64*1024*1024:
                    raise StreamError('timestamp writer byte budget exhausted; source continues')
                try: media.put_nowait((record,data))
                except queue.Full as error: raise StreamError('timestamp writer queue exhausted; source continues') from error
                queued_bytes[0]+=len(data)
            event(record)
        parser=TimedParser(engine,submit,event)
        parser.state['timeline_path']=str(timeline)
        def writer():
            try:
                pipe.connect()
                header=False
                while True:
                    try: item=media.get(timeout=.1)
                    except queue.Empty:
                        if capture_done.is_set(): break
                        continue
                    record,data=item
                    with byte_lock: queued_bytes[0]-=len(data)
                    if not header:
                        pipe.write(transport_header(engine.height,parser.num,parser.den,engine.field_order,parser.origin))
                        header=True
                    pipe.write(packet_header(record['stream'],record['pts'],record['duration'],len(data)))
                    pipe.write(data)
                    if record['stream']==0: parser.state['written_video_frames']+=1
                    else: parser.state['written_audio_samples']+=len(data)//4
            except Exception as error:
                parser.state['pipe_errors'].append(str(error)); engine.fail('timestamp pipe: '+str(error))
            finally: pipe.close(); done.set()
        def capture():
            try:
                result=engine.native.run()
                if result: engine.fail(f'timestamp subscription failed ({result})')
            except Exception as error: engine.fail(error)
            finally:
                try:
                    parser.finish()
                except Exception as error: engine.fail(error)
                try: engine.native.close()
                except Exception as error: engine.fail(error)
                finally: capture_done.set()
        try:
            engine.native=native_factory(standard=engine.standard,seconds=engine.seconds,attenuation=engine.attenuation,
                on_packet=parser.packet,on_batch=parser.batch,on_standard=parser.standard,
                on_signal=parser.signal,decode_frames=False,
                allow_discontinuities=True,on_discontinuity=parser.discontinuity)
            engine.mux=subprocess.Popen(mux_command(engine,pipe.path),stdout=output,stderr=log,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
            threads=[threading.Thread(target=writer,daemon=True),threading.Thread(target=capture,daemon=True)]
            for thread in threads: thread.start()
            while not capture_done.wait(.02):
                if engine.mux.poll() is not None and not engine.stopping.is_set():
                    engine.fail('timestamp encoder exited before input completed')
                if engine.stopping.is_set(): engine.native.stop()
        except Exception as error: engine.fail(error)
        finally:
            if not capture_done.is_set() and engine.native: engine.native.stop()
            started=[thread for thread in threads if thread.ident is not None]
            if len(started)==2:
                threads[-1].join(timeout=10)
                if threads[-1].is_alive(): engine.fail('timestamp input did not drain')
                capture_done.set(); threads[0].join(timeout=10)
                if threads[0].is_alive(): pipe.cancel(); engine.fail('timestamp output did not drain')
            else:
                if engine.native: engine.native.close()
                capture_done.set()
                if started:
                    started[0].join(timeout=10)
                    if started[0].is_alive(): pipe.cancel(); engine.fail('timestamp writer did not stop')
                else: pipe.close()
            if engine.mux:
                try: engine.mux.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    engine.mux.terminate()
                    try: engine.mux.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        engine.mux.kill(); engine.mux.wait(timeout=3)
                    engine.fail('timestamp mux finalization timeout')
                engine.stats.mux_exit=engine.mux.returncode
                if engine.mux.returncode: engine.fail('timestamp encoder/mux failed')
            engine.stats.native_exit=getattr(engine.native,'last_result',None)
            if not engine.errors:
                if parser.state['written_video_frames']!=engine.stats.video_frames:
                    engine.fail('timestamp admitted/written picture counts differ')
                if parser.state['written_audio_samples']*4!=engine.stats.audio_bytes:
                    engine.fail('timestamp admitted/written sample counts differ')
            parser.note('final',errors=engine.errors,stopped=engine.requested_stop,decoder=parser.decoder.summary())
    return 1 if engine.errors else 0
