// SPDX-License-Identifier: GPL-2.0-or-later
#include "preview_audio.h"
#include <assert.h>
#include <math.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
static void push(c039_preview_audio *audio,unsigned count,int16_t left,int16_t right) {
    uint8_t samples[1024]; assert(count<=256);
    for(unsigned i=0;i<count;i++) {
        samples[i*4]=(uint16_t)left; samples[i*4+1]=(uint16_t)left>>8;
        samples[i*4+2]=(uint16_t)right; samples[i*4+3]=(uint16_t)right>>8;
    }
    c039_preview_audio_push(audio,samples,count*4);
}
typedef struct { c039_preview_audio *audio; atomic_int done; } concurrent;
static void *producer(void *context) {
    concurrent *c=context;
    for(unsigned i=0;i<20000;i++) push(c->audio,32,16384,-16384);
    atomic_store(&c->done,1); return NULL;
}
int main(void) {
    assert(!c039_preview_audio_create(16,0));
    c039_preview_audio *audio=c039_preview_audio_create(128,32); assert(audio);
    float left[256],right[256];
    // No video or input PCM is needed to keep the output callback alive.
    for(unsigned i=0;i<100;i++) assert(c039_preview_audio_render(audio,left,right,64)==0);
    for(unsigned i=0;i<64;i++) assert(left[i]==0 && right[i]==0);
    push(audio,16,16384,-32768);
    assert(c039_preview_audio_render(audio,left,right,16)==0); // Wait for prefill.
    push(audio,16,16384,-32768);
    assert(c039_preview_audio_render(audio,left,right,16)==16);
    for(unsigned i=0;i<16;i++) assert(left[i]==0.5f && right[i]==-1);
    assert(c039_preview_audio_render(audio,left,right,32)==16); // Partial underflow.
    for(unsigned i=16;i<32;i++) assert(left[i]==0 && right[i]==0);
    push(audio,128,32767,-16384); push(audio,32,0,0); // Bounded overflow.
    assert(c039_preview_audio_get_stats(audio).dropped_frames==32);
    assert(c039_preview_audio_render(audio,left,right,128)==128);
    assert(fabsf(left[127]-32767/32768.0f)<1e-7f && right[127]==-0.5f);
    // Repeated wraparound, underflow and recovery never change stereo ordering.
    for(unsigned i=0;i<100;i++) {
        push(audio,64,8192,-8192);
        assert(c039_preview_audio_render(audio,left,right,80)==64);
        for(unsigned n=0;n<64;n++) assert(left[n]==0.25f && right[n]==-0.25f);
    }
    c039_preview_audio_stats s=c039_preview_audio_get_stats(audio);
    assert(s.input_frames==s.played_frames+s.dropped_frames+s.buffered_frames);
    c039_preview_audio_destroy(audio);

    concurrent c={.audio=c039_preview_audio_create(4096,0)}; atomic_init(&c.done,0);
    pthread_t thread; assert(!pthread_create(&thread,NULL,producer,&c));
    while(!atomic_load(&c.done) || c039_preview_audio_get_stats(c.audio).buffered_frames) {
        unsigned used=c039_preview_audio_render(c.audio,left,right,64);
        for(unsigned i=0;i<used;i++) assert(left[i]==0.5f && right[i]==-0.5f);
    }
    pthread_join(thread,NULL);
    s=c039_preview_audio_get_stats(c.audio);
    assert(s.input_frames==640000 && s.input_frames==s.played_frames+s.dropped_frames);
    c039_preview_audio_destroy(c.audio);
    puts("PASS: preview PCM silence, prefill, stereo conversion, bounded overflow, wraparound and concurrent recovery");
}
