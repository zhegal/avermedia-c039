// SPDX-License-Identifier: GPL-2.0-or-later
/* Explicit, bounded physical check; never part of the automatic test suite. */
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "capture_device.h"
#include "frame_decoder.h"

typedef struct {
    c039_session *session;
    c039_frame_decoder *decoder;
    uint64_t packets[2],bytes[2],last[2],frames;
    int failed,inject_sink,result;
} smoke;
static void frame(void *context,const uint8_t *data,size_t size,unsigned height) {
    smoke *s=context; (void)data;
    if(size!=(size_t)720*height*2) s->failed=1;
    s->frames++;
}
static int sample(void *context,int endpoint,const uint8_t *data,size_t size,uint64_t stamp) {
    smoke *s=context; unsigned index=endpoint==4?0:1;
    if((endpoint!=3 && endpoint!=4) || (endpoint==3 && size%4) ||
       (s->packets[index] && stamp-s->last[index]!=125)) { s->failed=1; return 1; }
    s->last[index]=stamp; s->packets[index]++; s->bytes[index]+=size;
    if(endpoint==4) c039_frame_decoder_feed(s->decoder,data,size);
    return s->inject_sink && s->packets[0]>=2000;
}
static void standard(void *context,const c039_video_standard *profile) {
    smoke *s=context; c039_frame_decoder_set_height(s->decoder,profile->height);
}
static DWORD WINAPI capture(void *context) {
    smoke *s=context; s->result=c039_session_run(s->session,sample,s); return 0;
}
int main(int argc,char **argv) {
    if(argc!=3 || strcmp(argv[1],"--hardware") ||
       (strcmp(argv[2],"--finite") && strcmp(argv[2],"--cancel") && strcmp(argv[2],"--sink-failure"))) {
        fputs("Usage: windows-capture-smoke --hardware --finite|--cancel|--sink-failure\n",stderr); return 64;
    }
    smoke s={0};
    s.inject_sink=!strcmp(argv[2],"--sink-failure");
    int cancel=!strcmp(argv[2],"--cancel");
    s.session=c039_session_create(C039_AUTO,0,3);
    s.decoder=c039_frame_decoder_create(576,frame,&s);
    if(!s.session || !s.decoder) return 1;
    c039_session_set_standard_callback(s.session,standard);
    HANDLE thread=CreateThread(NULL,0,capture,&s,0,NULL);
    if(!thread) return 1;
    if(cancel) { Sleep(1200); c039_session_stop(s.session); }
    if(WaitForSingleObject(thread,10000)!=WAIT_OBJECT_0) {
        fputs("FAILED: capture did not return within bounded deadline\n",stderr); return 2;
    }
    CloseHandle(thread);
    c039_session_destroy(s.session); c039_frame_decoder_destroy(s.decoder);
    printf("hardware_smoke mode=%s native_result=%d video_packets=%llu audio_packets=%llu video_bytes=%llu audio_bytes=%llu frames=%llu integrity_error=%d\n",
           argv[2],s.result,(unsigned long long)s.packets[0],(unsigned long long)s.packets[1],
           (unsigned long long)s.bytes[0],(unsigned long long)s.bytes[1],(unsigned long long)s.frames,s.failed);
    return s.failed || !s.bytes[0] || !s.bytes[1] || !s.frames || s.result!=(s.inject_sink?1:0);
}
