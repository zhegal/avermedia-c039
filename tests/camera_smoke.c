// SPDX-License-Identifier: GPL-2.0-or-later
// Explicit hardware check for the exact embeddable camera path; never run by make test.
#include "capture_device.h"
#include "frame_decoder.h"
#include <stdio.h>
#include <stdlib.h>
#include <signal.h>
typedef struct { c039_frame_decoder *decoder; FILE *file; unsigned frames,height; int failed; } state;
static c039_session *session;
static void stop(int sig) { (void)sig; c039_session_stop(session); }
static void frame(void *context,const uint8_t *bytes,size_t size,unsigned height) {
    state *s=context; s->failed|=fwrite(bytes,1,size,s->file)!=size; s->frames++; s->height=height;
}
static int payload(void *context,int endpoint,const uint8_t *bytes,size_t count,uint64_t stamp) {
    (void)stamp; state *s=context;
    if(endpoint==4) c039_frame_decoder_feed(s->decoder,bytes,count);
    return s->failed;
}
static void changed(void *context,const c039_video_standard *profile) {
    state *s=context; c039_frame_decoder_set_height(s->decoder,profile->height);
    printf("camera_format=%s height=%u fps=%u/%u\n",profile->name,profile->height,profile->rate_num,profile->rate_den);
}
int main(int argc,char **argv) {
    if(argc!=4) { fprintf(stderr,"usage: %s STANDARD SECONDS NEW-UYVY-FILE\n",argv[0]); return 64; }
    unsigned standard=c039_standard_parse(argv[1]);
    char *end=NULL; unsigned long seconds=strtoul(argv[2],&end,10);
    if(!standard || !*argv[2] || *end || seconds>3600) return 64;
    state s={0};
    session=c039_session_create(standard,4,(unsigned)seconds);
    if(!session) return 1;
    s.file=fopen(argv[3],"wbx");
    if(!s.file) { perror(argv[3]); c039_session_destroy(session); return 1; }
    s.decoder=c039_frame_decoder_create(576,frame,&s);
    if(!s.decoder) { fclose(s.file); c039_session_destroy(session); return 1; }
    signal(SIGINT,stop); signal(SIGTERM,stop);
    c039_session_set_standard_callback(session,changed);
    int code=c039_session_run(session,payload,&s);
    s.failed|=fclose(s.file)!=0;
    c039_session_destroy(session); c039_frame_decoder_destroy(s.decoder);
    printf("camera_smoke frames=%u height=%u capture_exit=%d write_error=%d\n",s.frames,s.height,code,s.failed);
    return code || s.failed || !s.frames;
}
