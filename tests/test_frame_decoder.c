// SPDX-License-Identifier: GPL-2.0-or-later
#include "frame_decoder.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct { unsigned frames,height; } state;
static void frame(void *context,const uint8_t *bytes,size_t count,unsigned height) {
    state *s=context;
    assert(height==s->height && count==1440*height);
    for(unsigned row=0;row<height;row++) for(unsigned x=0;x<1440;x++)
        assert(bytes[row*1440+x]==16+((row%2)*10+row/2)%200);
    s->frames++;
}
static void feed(c039_frame_decoder *d,const uint8_t *bytes,size_t count,unsigned chunk) {
    for(size_t i=0;i<count;) {
        size_t n=count-i<chunk?count-i:chunk;
        c039_frame_decoder_feed(d,bytes+i,n); i+=n;
    }
}
static void pair(c039_frame_decoder *d,unsigned height,unsigned chunk,int damaged) {
    uint8_t line[1444]={255,0,0,0};
    for(unsigned field=0;field<2;field++) for(unsigned y=0;y<height/2;y++) {
        line[3]=0x80|field*0x40;
        memset(line+4,16+(field*10+y)%200,1440);
        feed(d,line,sizeof(line)-(damaged && !field && !y),chunk);
    }
    const uint8_t boundary[]={255,0,0,0xa0};
    feed(d,boundary,4,chunk);
}
int main(void) {
    for(unsigned height=480;height<=576;height+=96) for(unsigned chunk=1;chunk<=4096;chunk*=16) {
        state s={.height=height};
        c039_frame_decoder *d=c039_frame_decoder_create(height,frame,&s); assert(d);
        uint8_t noise[100003]; memset(noise,0xff,sizeof(noise));
        for(unsigned i=0;i<3;i++) c039_frame_decoder_feed(d,noise,sizeof(noise));
        pair(d,height,chunk,1); assert(s.frames==0);
        pair(d,height,chunk,0); assert(s.frames==1);
        unsigned other=height==480?576:480;
        c039_frame_decoder_set_height(d,other); s.height=other;
        pair(d,other,chunk,0); assert(s.frames==2);
        c039_frame_decoder_destroy(d);
    }
    puts("PASS: native UYVY weaving, byte boundaries, damage rejection, bounded garbage and geometry changes");
}
