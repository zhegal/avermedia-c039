// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef C039_PREVIEW_AUDIO_H
#define C039_PREVIEW_AUDIO_H
#include <stdint.h>
#include <stddef.h>
typedef struct c039_preview_audio c039_preview_audio;
typedef struct {
    uint64_t input_frames,played_frames,silent_frames,dropped_frames,buffered_frames;
} c039_preview_audio_stats;
// Single producer (USB) and single real-time consumer (audio output).
c039_preview_audio *c039_preview_audio_create(unsigned capacity,unsigned prefill);
void c039_preview_audio_push(c039_preview_audio *,const uint8_t *,size_t);
unsigned c039_preview_audio_render(c039_preview_audio *,float *left,float *right,unsigned frames);
c039_preview_audio_stats c039_preview_audio_get_stats(c039_preview_audio *);
void c039_preview_audio_destroy(c039_preview_audio *);
#endif
