// SPDX-License-Identifier: GPL-2.0-or-later
// Bounded native equivalent of bt656.py. UYVY bytes and both fields unchanged.
#include "frame_decoder.h"
#include <stdlib.h>
#include <string.h>
enum { STRIDE=1440, BUFFER=131072, FRAME=STRIDE*576 };
struct c039_frame_decoder {
    unsigned height,lines[2];
    int bad[2],field,marker,first_complete;
    size_t count;
    uint8_t buffer[BUFFER],frame[FRAME];
    c039_frame_callback emit;
    void *context;
};
c039_frame_decoder *c039_frame_decoder_create(unsigned height,c039_frame_callback emit,void *context) {
    if((height!=480 && height!=576) || !emit) return NULL;
    c039_frame_decoder *d=calloc(1,sizeof(*d));
    if(d) { d->height=height; d->emit=emit; d->context=context; d->field=d->marker=-1; }
    return d;
}
void c039_frame_decoder_set_height(c039_frame_decoder *d,unsigned height) {
    if(!d || (height!=480 && height!=576)) return;
    d->height=height; d->count=0; d->field=d->marker=-1;
    d->lines[0]=d->lines[1]=0; d->bad[0]=d->bad[1]=d->first_complete=0;
}
static void consume(c039_frame_decoder *d,size_t count) {
    memmove(d->buffer,d->buffer+count,d->count-count); d->count-=count;
}
static void line(c039_frame_decoder *d,unsigned field,size_t bytes) {
    if((int)field!=d->field) {
        if(!field) {
            d->lines[0]=d->lines[1]=0; d->bad[0]=d->bad[1]=d->first_complete=0;
        } else d->first_complete=d->lines[0]==d->height/2 && !d->bad[0];
        d->field=(int)field;
    }
    if(bytes<STRIDE) d->bad[field]=1;
    else {
        if(d->lines[field]<d->height/2)
            memcpy(d->frame+(d->lines[field]*2+field)*STRIDE,d->buffer,STRIDE);
        if(++d->lines[field]>d->height/2) d->bad[field]=1;
    }
}
static void parse(c039_frame_decoder *d) {
    for(;;) {
        size_t pos=0;
        while(pos+3<=d->count && !(d->buffer[pos]==255 && !d->buffer[pos+1] && !d->buffer[pos+2])) pos++;
        if(pos+3>d->count) {
            if((d->marker<0 || d->count>STRIDE+65536) && d->count>3) {
                if(d->marker>=0) { d->bad[0]=d->bad[1]=1; d->marker=-1; }
                consume(d,d->count-3);
            }
            return;
        }
        if(pos+4>d->count) return;
        unsigned marker=d->buffer[pos+3];
        if(marker<0x80) {
            if(d->marker>=0) d->bad[0]=d->bad[1]=1;
            consume(d,pos+1); continue;
        }
        if(d->marker>=0 && ((d->marker&0xf0)==0x80 || (d->marker&0xf0)==0xc0))
            line(d,(d->marker&0x40)!=0,pos);
        if(d->field==1 && !(marker&0x40)) {
            if(d->first_complete && !d->bad[0] && !d->bad[1] && d->lines[1]==d->height/2)
                d->emit(d->context,d->frame,STRIDE*d->height,d->height);
            d->lines[0]=d->lines[1]=0; d->bad[0]=d->bad[1]=d->first_complete=0; d->field=-1;
        }
        d->marker=(int)marker; consume(d,pos+4);
    }
}
void c039_frame_decoder_feed(c039_frame_decoder *d,const uint8_t *data,size_t size) {
    if(!d || !data) return;
    while(size) {
        size_t n=size>4096?4096:size;
        memcpy(d->buffer+d->count,data,n); d->count+=n; data+=n; size-=n;
        parse(d);
    }
}
void c039_frame_decoder_destroy(c039_frame_decoder *d) { free(d); }
