// SPDX-License-Identifier: GPL-2.0-or-later
/* Bounded raw hardware diagnostic. Existing files are never overwritten. */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "capture_device.h"
#include "windows_capture_cli.h"

typedef struct {
    FILE *raw[2],*packets[2],*result;
    uint64_t offsets[2],counts[2];
    unsigned height,rate_num,rate_den;
    int incompatible;
} output;
static SRWLOCK handler_lock=SRWLOCK_INIT;
static c039_session *active_session;
static volatile LONG interrupted;
static BOOL WINAPI stop_handler(DWORD event) {
    if(event!=CTRL_C_EVENT && event!=CTRL_BREAK_EVENT && event!=CTRL_CLOSE_EVENT) return FALSE;
    AcquireSRWLockShared(&handler_lock);
    InterlockedExchange(&interrupted,1);
    if(active_session) c039_session_stop(active_session);
    ReleaseSRWLockShared(&handler_lock);
    return TRUE;
}
static void standard(void *context,const c039_video_standard *profile) {
    output *out=context;
    fprintf(stderr,"native_standard name=%s height=%u rate=%u/%u\n",profile->name,profile->height,profile->rate_num,profile->rate_den);
    if(profile->height!=out->height || profile->rate_num!=out->rate_num || profile->rate_den!=out->rate_den) {
        out->incompatible=1;
        fputs("Geometry/rate family changed: ending fixed-format raw diagnostic explicitly\n",stderr);
    }
}
static int sample(void *context,int endpoint,const uint8_t *data,size_t size,uint64_t stamp) {
    output *out=context;
    if(out->incompatible) return 1;
    unsigned index=endpoint==4?0:1;
    if(endpoint!=3 && endpoint!=4) return 1;
    if(endpoint==3 && size%4) { fputs("Incomplete stereo PCM sample\n",stderr); return 1; }
    if(fprintf(out->packets[index],"%llu,%u,00000000,00000000,%zu,%llu\n",
         (unsigned long long)(stamp/1000),(unsigned)(stamp%1000/125),size,(unsigned long long)out->offsets[index])<0 ||
       fwrite(data,1,size,out->raw[index])!=size) return 1;
    out->offsets[index]+=size; out->counts[index]++;
    return 0;
}
static FILE *new_file(const char *prefix,const char *suffix) {
    size_t size=strlen(prefix)+strlen(suffix)+1;
    char *path=malloc(size);
    if(!path) return NULL;
    snprintf(path,size,"%s%s",prefix,suffix);
    FILE *file=fopen(path,"wbx");
    if(!file) fprintf(stderr,"Cannot create new output %s (existing files are refused)\n",path);
    free(path); return file;
}
static int unsigned_arg(const char *text,unsigned max,unsigned *value) {
    char *end=NULL;
    if(!*text || *text=='-') return 1;
    unsigned long result=strtoul(text,&end,10);
    if(*end || result>max) return 1;
    *value=(unsigned)result; return 0;
}
int c039_windows_capture_cli(int argc,char **argv) {
    unsigned seconds=3,attenuation=6;
    if(argc<4) { fputs("Usage: c039-probe --capture STANDARD NEW_PREFIX [--seconds 1..60] [--audio-attenuation-db 0..48]\n",stderr); return 64; }
    unsigned mode=c039_standard_parse(argv[2]);
    if(!mode) { fputs("Unknown standard; use --list-standards\n",stderr); return 64; }
    for(int n=4;n<argc;n++) {
        if(!strcmp(argv[n],"--seconds") && n+1<argc) {
            if(unsigned_arg(argv[++n],60,&seconds) || !seconds) return 64;
        } else if(!strcmp(argv[n],"--audio-attenuation-db") && n+1<argc) {
            if(unsigned_arg(argv[++n],48,&attenuation)) return 64;
        } else return 64;
    }
    char directory[MAX_PATH],*name=NULL;
    DWORD length=GetFullPathNameA(argv[3],MAX_PATH,directory,&name);
    if(!length || length>=MAX_PATH || !name) return 1;
    *name=0;
    ULARGE_INTEGER available;
    if(!GetDiskFreeSpaceExA(directory,&available,NULL,NULL) ||
       available.QuadPart<(uint64_t)seconds*24000000+67108864) {
        fputs("Raw diagnostic disk budget unavailable/insufficient; no capture started\n",stderr); return 1;
    }
    const c039_video_standard *profile=c039_standard(mode==C039_AUTO?C039_PAL:mode);
    output out={.height=profile->height,.rate_num=profile->rate_num,.rate_den=profile->rate_den};
    out.result=new_file(argv[3],".result.json");
    if(!out.result) return 1;
    const char *raw_suffix[]={".video.bin",".audio.s16le"};
    const char *packet_suffix[]={".video.bin.packets.csv",".audio.s16le.packets.csv"};
    int failed=0;
    for(unsigned n=0;n<2;n++) {
        out.raw[n]=new_file(argv[3],raw_suffix[n]);
        out.packets[n]=new_file(argv[3],packet_suffix[n]);
        if(!out.raw[n] || !out.packets[n]) failed=1;
        else fputs("bus_frame,microframe,transfer_status,packet_status,length,file_offset\n",out.packets[n]);
    }
    c039_session *session=NULL;
    if(!failed) {
        session=c039_session_create(mode,0,seconds);
        if(!session) failed=1;
    }
    if(!failed) {
        c039_session_set_attenuation(session,attenuation);
        c039_session_set_standard_callback(session,standard);
        AcquireSRWLockExclusive(&handler_lock); active_session=session; InterlockedExchange(&interrupted,0); ReleaseSRWLockExclusive(&handler_lock);
        if(!SetConsoleCtrlHandler(stop_handler,TRUE)) failed=1;
        else failed=c039_session_run(session,sample,&out);
        SetConsoleCtrlHandler(stop_handler,FALSE);
        AcquireSRWLockExclusive(&handler_lock); active_session=NULL; ReleaseSRWLockExclusive(&handler_lock);
        if(InterlockedCompareExchange(&interrupted,0,0) && !failed) failed=130;
    }
    c039_session_destroy(session);
    for(unsigned n=0;n<2;n++) {
        if(out.raw[n] && fclose(out.raw[n])) failed=1;
        if(out.packets[n] && fclose(out.packets[n])) failed=1;
    }
    fprintf(out.result,"{\"return_code\":%d,\"requested_seconds\":%u,\"video_bytes\":%llu,\"audio_bytes\":%llu,\"video_packets\":%llu,\"audio_packets\":%llu,\"incompatible_geometry\":%s}\n",
            failed,seconds,(unsigned long long)out.offsets[0],(unsigned long long)out.offsets[1],
            (unsigned long long)out.counts[0],(unsigned long long)out.counts[1],out.incompatible?"true":"false");
    if(fclose(out.result)) failed=1;
    return failed;
}
