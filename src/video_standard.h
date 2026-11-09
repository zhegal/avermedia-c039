// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef C039_VIDEO_STANDARD_H
#define C039_VIDEO_STANDARD_H
#include <stddef.h>
enum { C039_PAL=1, C039_SECAM=2, C039_NTSC=3, C039_AUTO=4,
       C039_NTSC_J=5, C039_NTSC_443=6, C039_PAL_M=7, C039_PAL_N=8,
       C039_PAL_NC=9, C039_PAL_60=10 };
typedef struct {
    unsigned id;
    const char *name;
    unsigned format,height,rate_num,rate_den,burst,luma,comb,subcarrier;
} c039_video_standard;
typedef struct { const char *name; unsigned id; } c039_standard_alias;
typedef struct {
    unsigned detected,selected,present,hlock,vlock,chroma;
} c039_signal_status;
extern const c039_standard_alias c039_standard_names[];
extern const size_t c039_standard_name_count;
const c039_standard_alias *c039_standard_name_at(size_t index);
const c039_video_standard *c039_standard(unsigned id);
unsigned c039_standard_parse(const char *name);
unsigned c039_standard_detect(unsigned decoder_format);
#endif
