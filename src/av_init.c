// SPDX-License-Identifier: GPL-2.0-or-later
/* External A/V sequence adapted from Linux v6.12 cx231xx-core.c and
 * cx231xx-avcore.c, Copyright (C) 2008 Srinivasa Deevi / Conexant.
 * macOS-independent bounded, fail-fast diagnostic with a rollback journal.
 * macOS adaptation/modifications: 2026-11-09. Additional upstream credits: NOTICE.
 * Source URLs and hashes: references/linux-sources.json.
 */
#include "av_init.h"
#include <stdio.h>
#include <string.h>

typedef struct {
    uint8_t request, size;
    uint16_t value, index;
    uint8_t original[4];
    uint32_t mask;
    int masked;
} entry;
typedef struct {
    c039_transport *io;
    entry journal[128];
    unsigned count;
} session;

static int cancelled(session *s) {
    return s->io->cancelled && s->io->cancelled(s->io->context);
}
static void delay(session *s, unsigned ms) {
    if(s->io->sleep_ms) s->io->sleep_ms(s->io->context,ms);
}
static int read_reg(session *s,uint8_t request,uint16_t value,uint16_t index,
                    uint8_t *data,unsigned size) {
    if(cancelled(s)) return 1;
    return s->io->control(s->io->context,0,request,value,index,data,size);
}
static int write_reg(session *s,uint8_t request,uint16_t value,uint16_t index,
                     const uint8_t *data,unsigned size) {
    if(cancelled(s)) return 1;
    unsigned i;
    for(i=0;i<s->count;i++) {
        entry *e=&s->journal[i];
        if(e->request==request && e->value==value && e->index==index && e->size==size) break;
    }
    if(i==s->count) {
        if(s->count==128 || size>4) return 1;
        entry *e=&s->journal[i];
        *e=(entry){.request=request,.value=value,.index=index,.size=size,.mask=0xffffffff};
        if(read_reg(s,request==0x0c?0x0d:4,value,index,e->original,size)) return 1;
        // A failed OUT may still affect hardware. Journal it before sending.
        s->count++;
    }
    uint8_t bytes[4]; memcpy(bytes,data,size);
    return s->io->control(s->io->context,1,request,value,index,bytes,size);
}
static void restore_mask(session *s,unsigned value,unsigned index,uint32_t mask) {
    for(unsigned i=0;i<s->count;i++) {
        entry *e=&s->journal[i];
        if(e->value==value && e->index==index) {
            e->mask=e->masked?(e->mask|mask):mask;
            e->masked=1;
        }
    }
}
static int afe_read(session *s,unsigned reg,uint8_t *value) {
    return read_reg(s,4,0x6029,reg,value,1);
}
static int afe_write(session *s,unsigned reg,uint8_t value) {
    return write_reg(s,0,0x6029,reg,&value,1);
}
static int i2s_write(session *s,unsigned reg,uint8_t value) {
    return write_reg(s,0,0x9825,reg,&value,1);
}
static int power(session *s) {
    uint8_t b[4];
    if(read_reg(s,0x0d,0xf,0x74,b,4)) return 1;
    uint32_t value=b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;
    // Do not disturb another capture session or an unexpected power state.
    if(value & 0x17f) { fprintf(stderr,"refusing non-idle PWR_CTL_EN=%08x\n",value); return 1; }
    const unsigned flags[]={8,0x40,0x30};
    for(unsigned i=0;i<3;i++) {
        value|=flags[i];
        for(unsigned j=0;j<4;j++) b[j]=(uint8_t)(value>>(8*j));
        int written=write_reg(s,0x0c,0xf,0x74,b,4);
        if(written) {
            uint8_t actual[4]={0};
            delay(s,10);
            int error=read_reg(s,0x0d,0xf,0x74,actual,4);
            fprintf(stderr,"power OUT failed; readback_status=%d data=%02x%02x%02x%02x\n",
                error,actual[0],actual[1],actual[2],actual[3]);
            if(written!=C039_CONTROL_TRANSACTION_ERROR || error || memcmp(actual,b,4)) return 1;
            puts("power_transition_reconciled=exact-readback (USB status remains an error)");
        }
        delay(s,10);
    }
    // First prove AFE read transport works, then use the Linux power sequence.
    uint8_t status=0;
    if(afe_read(s,8,&status)) return 1;
    for(unsigned i=0;i<10;i++) {
        if(afe_write(s,8,0x18) || afe_read(s,8,&status)) return 1;
        if(status==0x18) break;
        if(i==9) { fprintf(stderr,"AFE power readback timed out: %02x\n",status); return 1; }
        delay(s,10);
    }
    for(unsigned ch=0;ch<3;ch++) if(afe_write(s,0x23+ch*0x20,0)) return 1;
    return i2s_write(s,0xf,0);
}
static int super_block(session *s) {
    uint8_t value=0;
    if(afe_write(s,1,0x3c) || afe_read(s,1,&value)) return 1;
    if(value!=0x3c) { fprintf(stderr,"AFE TUNE2 readback mismatch: %02x\n",value); return 1; }
    if(afe_write(s,0,0x42) || afe_write(s,5,0x0f)) return 1;
    for(unsigned i=0;i<10;i++) {
        if(afe_write(s,8,0x18) || afe_read(s,8,&value)) return 1;
        if(value==0x18) break;
        if(i==9) return 1;
        delay(s,10);
    }
    int tune=afe_write(s,2,0x40);
    // Only bit 6 requests tuning. The low bits change during calibration.
    restore_mask(s,0x6029,2,0x40);
    if(tune) return 1;
    delay(s,5);
    return afe_write(s,2,0);
}
static int channels(session *s) {
    for(unsigned ch=0;ch<3;ch++) if(afe_write(s,0x23+ch*0x20,0)) return 1;
    if(afe_write(s,0xb,2)) return 1;
    const unsigned regs[]={0x27,0x22,0x27,0x29,0x2a,0x26};
    const uint8_t values[]={0x17,0x10,7,0xf0,0,3};
    for(unsigned step=0;step<6;step++) {
        for(unsigned ch=0;ch<3;ch++) {
            unsigned reg=regs[step]+ch*0x20; uint8_t value=values[step];
            if(step==4) { if(afe_read(s,reg,&value)) return 1; value&=7; }
            if(afe_write(s,reg,value)) return 1;
        }
        if(step==1) delay(s,5);
    }
    return 0;
}
static int video_byte(session *s,unsigned reg,uint8_t value) {
    return write_reg(s,0,0x8829,reg,&value,1);
}
static int video_mask(session *s,unsigned reg,uint32_t mask,uint32_t bits) {
    uint8_t b[4];
    if(read_reg(s,4,0x8829,reg,b,4)) return 1;
    uint32_t v=b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24;
    v=(v&~mask)|(bits&mask);
    for(unsigned i=0;i<4;i++) b[i]=(uint8_t)(v>>(8*i));
    int result=write_reg(s,0,0x8829,reg,b,4);
    restore_mask(s,0x8829,reg,mask);
    return result;
}
static int video_byte_mask(session *s,unsigned reg,uint8_t mask,uint8_t bits) {
    uint8_t v=0;
    if(read_reg(s,4,0x8829,reg,&v,1)) return 1;
    return video_byte(s,reg,(v&~mask)|(bits&mask));
}
static int video_setup(session *s,unsigned standard) {
    // Composite VIN_2_1 and DIF bypass from cx231xx_set_decoder_video_input.
    // No MCU reset/start, firmware download, or audio-DSP register writes.
    uint8_t mux=0;
    if(afe_read(s,0x28,&mux) || afe_write(s,0x28,(mux&~0x30)|0x10)) return 1;
    if(video_mask(s,0x104,0x01ff8030,0x01000010) ||
       video_mask(s,0x340,0xffffffff,0x0df7df83) ||
       video_mask(s,0x33c,0x80000000,0x80000000) ||
       video_mask(s,0x488,0x18000000,0x18000000) ||
       video_mask(s,0x404,0x83,0x82)) return 1;
    unsigned ntsc=standard==3,secam=standard==2;
    unsigned fmt=ntsc?1:secam?12:4;
    // PAL comb-filter startup sequence from set_v4lstd.
    if(!ntsc && !secam && (video_byte_mask(s,0x400,0xf,1) || video_byte_mask(s,0x47b,6,0))) return 1;
    if(video_byte_mask(s,0x400,0x3f,fmt|0x20) ||
       video_byte_mask(s,0x401,6,0) || video_byte_mask(s,0x403,3,0)) return 1;
    // Native 720-pixel window, no horizontal or vertical scaling. These use
    // cx25840_std_setup generic timing values, with exact 576/480 active rows.
    unsigned hb=ntsc?122:132,ha=720,vb=ntsc?20:34,va=ntsc?480:576;
    unsigned sc=ntsc?556063:secam?0x0a425f:688739;
    uint8_t timing[]={hb,((hb>>8)&3)|((ha<<4)&0xf0),ha>>4,ntsc?0x5b:93,
        vb,((vb>>8)&3)|((va<<4)&0xf0),va>>4,ntsc?24:38,
        0x1f,2,(uint8_t)((ntsc?1:2)<<6 | (secam?0:1)<<4),
        ntsc?0x66:secam?0:0x20,sc,sc>>8,sc>>16,ntsc?0:1};
    for(unsigned i=0;i<sizeof(timing);i++) if(video_byte(s,0x470+i,timing[i])) return 1;
    const unsigned scale_regs[]={0x418,0x419,0x41a,0x41c,0x41d,0x41e};
    for(unsigned i=0;i<6;i++) if(video_byte(s,scale_regs[i],i==5?8:0)) return 1;
    if(video_byte(s,0x49f,ntsc?0x14:0x11) || video_byte(s,0x402,secam?0:4) ||
       video_byte_mask(s,0x401,0x60,0) || video_byte_mask(s,0x401,0x60,0x60)) return 1;
    delay(s,100);
    uint8_t status[4];
    return read_reg(s,4,0x8829,0x40c,status,4);
}
static int audio_setup(session *s) {
    // Line input subset of cx231xx_set_audio_decoder_input + 48kHz SRCs.
    // Deliberately no writes to 0x000 or 0x800..0x803 (firmware interface).
    if(video_byte_mask(s,0x810,1,1) || i2s_write(s,0xe,0x80) || i2s_write(s,0xf,0)) return 1;
    if(video_mask(s,0x124,0xffffffff,0) || video_mask(s,0x91c,0x01000000,0x01000000) ||
       video_mask(s,0x910,0xffffffff,0) || video_mask(s,0x8d0,0xffffffff,0x00063073) ||
       video_mask(s,0x8d4,0x7fff00ff,0x7fff0024+2*s->io->audio_attenuation_db) ||
       video_mask(s,0x8dc,0x7fff0000,0x7fff0000)) return 1;
    const unsigned srcs[]={0x900,0x904,0x90c};
    for(unsigned i=0;i<3;i++) if(video_mask(s,srcs[i],0xffffffff,0x08014faa)) return 1;
    return video_byte_mask(s,0x810,1,0);
}
int c039_av_probe(c039_transport *transport,uint16_t *decoder_id,int calibrate) {
    session s={.io=transport};
    *decoder_id=0;
    if(transport->audio_attenuation_db>48 || transport->video_standard>3) return 1;
    puts("stage=external-av-power");
    int failed=power(&s);
    if(!failed && calibrate) { puts("stage=afe-super-block"); failed=super_block(&s); }
    if(!failed && calibrate) { puts("stage=afe-channels"); failed=channels(&s); }
    // DIF / decoder setup is gated on a recognized hardware ID.
    if(!failed) {
        puts("stage=i2s-clock"); uint8_t value=0;
        failed=read_reg(&s,4,0x9825,0xe,&value,1);
        if(!failed) failed=i2s_write(&s,0xe,value|0x80) || i2s_write(&s,0xf,0);
    }
    if(!failed) {
        puts("stage=decoder-id"); uint8_t low=0,high=0;
        failed=read_reg(&s,4,0x8829,0x100,&low,1) || read_reg(&s,4,0x8829,0x101,&high,1);
        if(!failed) {
            *decoder_id=(uint16_t)low|((uint16_t)high<<8);
            printf("decoder_id=%04x decimal=%u confirmed_cx231xx=%s\n",*decoder_id,*decoder_id,
                (*decoder_id&0xfff0)==0x5a30?"yes":"no");
            failed=(*decoder_id&0xfff0)!=0x5a30;
        }
    }
    if(!failed && transport->video_standard) {
        puts("stage=firmware-free-composite-video");
        failed=video_setup(&s,transport->video_standard);
    }
    if(!failed && transport->line_audio) {
        puts("stage=firmware-free-line-audio"); failed=audio_setup(&s);
    }
    if(!failed && transport->on_ready) failed=transport->on_ready(transport->context);
    printf("stage=rollback registers=%u\n",s.count);
    int cleanup_failed=0;
    while(s.count) {
        entry *e=&s.journal[--s.count];
        uint8_t restored[4]; memcpy(restored,e->original,4);
        if(e->masked) {
            uint8_t current[4]={0};
            if(transport->control(transport->context,0,e->request==0xc?0xd:4,e->value,e->index,current,e->size))
                cleanup_failed=1;
            else for(unsigned i=0;i<e->size;i++) {
                uint8_t mask=(uint8_t)(e->mask>>(8*i));
                restored[i]=(current[i]&~mask)|(e->original[i]&mask);
            }
            printf("rollback_mask value=%04x index=%04x mask=%08x\n",e->value,e->index,e->mask);
        }
        if(transport->control(transport->context,1,e->request,e->value,e->index,restored,e->size))
            cleanup_failed=1;
        // Verify restoration independently, including the bridge power state.
        uint8_t actual[4]={0};
        int read_failed=transport->control(transport->context,0,e->request==0x0c?0x0d:4,
                             e->value,e->index,actual,e->size);
        int mismatch=read_failed;
        for(unsigned i=0;i<e->size;i++) mismatch|=(actual[i]^e->original[i])&((e->mask>>(8*i))&0xff);
        if(mismatch) {
            fprintf(stderr,"rollback mismatch value=%04x index=%04x expected=%02x actual=%02x\n",
                e->value,e->index,e->original[0],actual[0]);
            cleanup_failed=1;
        }
        if(e->request==0x0c && e->index==0x74)
            printf("bridge_power_restored=%s\n",read_failed || memcmp(actual,e->original,4)?"NO":"yes");
    }
    printf("rollback_verified=%s\n",cleanup_failed?"NO":"yes");
    return cleanup_failed?2:failed?1:0;
}
