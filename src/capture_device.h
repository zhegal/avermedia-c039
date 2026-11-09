// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef C039_CAPTURE_DEVICE_H
#define C039_CAPTURE_DEVICE_H
#include <stdint.h>
#include <stddef.h>
#include "video_standard.h"
typedef struct c039_session c039_session;
typedef int (*c039_sample_callback)(void *,int,const uint8_t *,size_t,uint64_t);
// standard: a video_standard.h profile or C039_AUTO. endpoint: 4 video, 0 A/V.
c039_session *c039_session_create(unsigned standard,int endpoint,unsigned seconds);
// Blocking, single-use; caller owns the run-loop thread and callback lifetime.
int c039_session_run(c039_session *,c039_sample_callback,void *);
// Thread-safe; run() restores controls before returning. Never destroy while running.
void c039_session_stop(c039_session *);
void c039_session_set_standard_callback(c039_session *,void (*)(void *,const c039_video_standard *));
void c039_session_set_attenuation(c039_session *,unsigned db);
void c039_session_destroy(c039_session *);
#endif
