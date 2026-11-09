// SPDX-License-Identifier: GPL-2.0-or-later
// Format codes and timings: Linux v6.12 cx25840-core.c, generic native window.
// Composite/RCA has no RF tuner: regional PAL/SECAM RF variants share profiles.
#include "video_standard.h"
#include <string.h>
static const c039_video_standard profiles[]={
    {C039_PAL,"pal",4,576,25,1,93,2,0x20,688739},
    {C039_SECAM,"secam",12,576,25,1,93,2,0,0x0a425f},
    {C039_NTSC,"ntsc",1,480,30000,1001,0x5b,1,0x66,556063},
    {C039_NTSC_J,"ntsc-j",2,480,30000,1001,0x5b,1,0x66,556063},
    {C039_NTSC_443,"ntsc-443",3,480,30000,1001,0x5b,1,0x66,688739},
    {C039_PAL_M,"pal-m",5,480,30000,1001,0x61,1,0x20,555452},
    {C039_PAL_N,"pal-n",6,576,25,1,93,2,0x20,688739},
    {C039_PAL_NC,"pal-nc",7,576,25,1,95,1,0x20,556453},
    {C039_PAL_60,"pal-60",8,480,30000,1001,0x59,2,0x20,688739},
};
const c039_standard_alias c039_standard_names[]={
    {"auto",C039_AUTO},{"pal",C039_PAL},{"secam",C039_SECAM},{"ntsc",C039_NTSC},
    {"pal-b",C039_PAL},{"pal-d",C039_PAL},{"pal-g",C039_PAL},{"pal-h",C039_PAL},
    {"pal-i",C039_PAL},{"pal-m",C039_PAL_M},{"pal-n",C039_PAL_N},
    {"pal-nc",C039_PAL_NC},{"pal-60",C039_PAL_60},{"ntsc-m",C039_NTSC},
    {"ntsc-j",C039_NTSC_J},{"ntsc-443",C039_NTSC_443},{"ntsc-433",C039_NTSC_443},
    {"secam-b",C039_SECAM},{"secam-d",C039_SECAM},{"secam-g",C039_SECAM},
    {"secam-h",C039_SECAM},{"secam-k",C039_SECAM},{"secam-k1",C039_SECAM},
    {"secam-l",C039_SECAM},{"secam-l1",C039_SECAM},
};
const size_t c039_standard_name_count=sizeof(c039_standard_names)/sizeof(c039_standard_names[0]);
const c039_video_standard *c039_standard(unsigned id) {
    for(size_t i=0;i<sizeof(profiles)/sizeof(profiles[0]);i++) if(profiles[i].id==id) return &profiles[i];
    return NULL;
}
unsigned c039_standard_parse(const char *name) {
    for(size_t i=0;i<c039_standard_name_count;i++) if(!strcmp(c039_standard_names[i].name,name)) return c039_standard_names[i].id;
    return 0;
}
unsigned c039_standard_detect(unsigned format) {
    for(size_t i=0;i<sizeof(profiles)/sizeof(profiles[0]);i++) if(profiles[i].format==format) return profiles[i].id;
    return 0;
}
