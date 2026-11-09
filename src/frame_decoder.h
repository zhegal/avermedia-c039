// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef C039_FRAME_DECODER_H
#define C039_FRAME_DECODER_H
#include <stdint.h>
#include <stddef.h>
typedef struct c039_frame_decoder c039_frame_decoder;
typedef void (*c039_frame_callback)(void *,const uint8_t *,size_t,unsigned);
c039_frame_decoder *c039_frame_decoder_create(unsigned height,c039_frame_callback,void *);
void c039_frame_decoder_set_height(c039_frame_decoder *,unsigned height);
void c039_frame_decoder_feed(c039_frame_decoder *,const uint8_t *,size_t);
void c039_frame_decoder_destroy(c039_frame_decoder *);
#endif
