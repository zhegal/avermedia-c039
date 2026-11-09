// SPDX-License-Identifier: GPL-2.0-or-later
// Preview only: bounded PCM storage; underflow produces silence without stopping video.
#include "preview_audio.h"
#include <stdatomic.h>
#include <stdlib.h>
struct c039_preview_audio {
    unsigned capacity,prefill;
    int primed; // Owned exclusively by the render thread.
    int16_t *samples;
    atomic_uint_fast64_t head,tail,input,played,silent,dropped;
};
c039_preview_audio *c039_preview_audio_create(unsigned capacity,unsigned prefill) {
    if(capacity<128 || capacity>480000 || prefill>capacity) return NULL;
    c039_preview_audio *a=calloc(1,sizeof(*a));
    if(!a) return NULL;
    a->samples=calloc((size_t)capacity*2,sizeof(int16_t));
    if(!a->samples) { free(a); return NULL; }
    a->capacity=capacity; a->prefill=prefill;
    atomic_init(&a->head,0); atomic_init(&a->tail,0); atomic_init(&a->input,0);
    atomic_init(&a->played,0); atomic_init(&a->silent,0); atomic_init(&a->dropped,0);
    return a;
}
void c039_preview_audio_push(c039_preview_audio *a,const uint8_t *bytes,size_t count) {
    if(!a || !bytes || count%4) return;
    uint64_t frames=count/4;
    uint64_t head=atomic_load_explicit(&a->head,memory_order_relaxed);
    uint64_t tail=atomic_load_explicit(&a->tail,memory_order_acquire);
    atomic_fetch_add_explicit(&a->input,frames,memory_order_relaxed);
    if(frames>a->capacity-(head-tail)) {
        atomic_fetch_add_explicit(&a->dropped,frames,memory_order_relaxed); return;
    }
    for(uint64_t i=0;i<frames;i++) {
        size_t pos=(size_t)((head+i)%a->capacity)*2;
        a->samples[pos]=(int16_t)((unsigned)bytes[i*4] | (unsigned)bytes[i*4+1]<<8);
        a->samples[pos+1]=(int16_t)((unsigned)bytes[i*4+2] | (unsigned)bytes[i*4+3]<<8);
    }
    atomic_store_explicit(&a->head,head+frames,memory_order_release);
}
unsigned c039_preview_audio_render(c039_preview_audio *a,float *left,float *right,unsigned frames) {
    if(!a || !left || !right) return 0;
    uint64_t tail=atomic_load_explicit(&a->tail,memory_order_relaxed);
    uint64_t head=atomic_load_explicit(&a->head,memory_order_acquire);
    if(!a->primed && head-tail>=a->prefill) a->primed=1;
    unsigned used=a->primed?(unsigned)(head-tail<frames?head-tail:frames):0;
    for(unsigned i=0;i<used;i++) {
        size_t pos=(size_t)((tail+i)%a->capacity)*2;
        left[i]=a->samples[pos]/32768.0f; right[i]=a->samples[pos+1]/32768.0f;
    }
    for(unsigned i=used;i<frames;i++) left[i]=right[i]=0;
    if(used<frames) a->primed=0;
    atomic_store_explicit(&a->tail,tail+used,memory_order_release);
    atomic_fetch_add_explicit(&a->played,used,memory_order_relaxed);
    atomic_fetch_add_explicit(&a->silent,frames-used,memory_order_relaxed);
    return used;
}
c039_preview_audio_stats c039_preview_audio_get_stats(c039_preview_audio *a) {
    c039_preview_audio_stats s={0};
    if(!a) return s;
    s.input_frames=atomic_load_explicit(&a->input,memory_order_relaxed);
    s.played_frames=atomic_load_explicit(&a->played,memory_order_relaxed);
    s.silent_frames=atomic_load_explicit(&a->silent,memory_order_relaxed);
    s.dropped_frames=atomic_load_explicit(&a->dropped,memory_order_relaxed);
    uint64_t tail=atomic_load_explicit(&a->tail,memory_order_acquire);
    uint64_t head=atomic_load_explicit(&a->head,memory_order_acquire);
    s.buffered_frames=head-tail;
    return s;
}
void c039_preview_audio_destroy(c039_preview_audio *a) { if(a) { free(a->samples); free(a); } }
