// SPDX-License-Identifier: GPL-2.0-or-later
// Fault injection for the hardware initialization / rollback boundary.
#include "av_init.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

typedef struct {
    uint8_t bridge[256][4],afe[256],i2s[256],video[4096];
    unsigned calls,fail_at,cancel_at,writes,failures;
    int pll_stuck,power_transaction_error,power_not_applied;
    unsigned standard,forward_calls;
    int line_audio;
} mock;
static int transfer(void *context,int write,uint8_t request,uint16_t value,
                     uint16_t index,uint8_t *data,unsigned size) {
    mock *m=context;
    m->calls++;
    if(m->calls==m->fail_at) {
        // Model an OUT applied to the device but reported as failed by host.
        m->failures++;
        if(!write) return 1;
    }
    if(!write && value==0x8829 && (index==0x100 || index==0x101)) {
        assert(request==4 && size==1 && (index==0x100 || index==0x101));
        *data=index==0x100?0x3e:0x5a;
    } else {
        uint8_t *p=NULL;
        if(value==0xf) { assert(index==0x74 && size==4); p=m->bridge[index]; }
        else if(value==0x6029) { assert(index<0x80 && size==1); p=&m->afe[index]; }
        else if(value==0x9825) { assert((index==0xe || index==0xf) && size==1); p=&m->i2s[index]; }
        else if(value==0x8829) {
            assert(index+size<4096 && size<=4);
            assert(index!=0 && (index<0x800 || index>0x803)); // Never firmware writes.
            p=&m->video[index];
        }
        else assert(0);
        assert(request==(value==0xf?(write?0xc:0xd):(write?0:4)));
        if(write) {
            if(value==0x6029 && index==2) *p=(*p&~0x40)|(data[0]&0x40);
            else if(!(m->power_not_applied && value==0xf && data[0])) memcpy(p,data,size);
            m->writes++;
        }
        else { memcpy(data,p,size); if(m->pll_stuck && value==0x6029 && index==8) *data=0; }
    }
    if(m->power_transaction_error && write && value==0xf && data[0]) return 2;
    return m->calls==m->fail_at;
}
static int cancelled(void *context) { mock *m=context; return m->cancel_at && m->calls>=m->cancel_at; }
static void sleep_ms(void *context,unsigned ms) { (void)context; assert(ms<=100); }
static int ready(void *context) { mock *m=context; m->forward_calls=m->calls; return 0; }
static mock initial(void) {
    mock m={0};
    // Nonzero defaults catch implementations that blindly restore zero.
    memset(m.afe,0x55,sizeof(m.afe));
    memset(m.video,0x5a,sizeof(m.video));
    m.i2s[0xe]=0x31; m.i2s[0xf]=0xfe;
    m.bridge[0x74][1]=2; // Preserve bits outside PWR_MODE_MASK.
    return m;
}
static int run(mock *m) {
    c039_transport io={.context=m,.control=transfer,.sleep_ms=sleep_ms,.cancelled=cancelled,
        .on_ready=ready,.video_standard=m->standard,.line_audio=m->line_audio};
    uint16_t id=0;
    return c039_av_probe(&io,&id,1);
}
static void restored(mock *m) {
    mock expected=initial();
    assert(!memcmp(m->bridge,expected.bridge,sizeof(m->bridge)));
    assert(!memcmp(m->afe,expected.afe,sizeof(m->afe)));
    assert(!memcmp(m->i2s,expected.i2s,sizeof(m->i2s)));
    assert(!memcmp(m->video,expected.video,sizeof(m->video)));
}
int main(void) {
    mock good=initial(); assert(run(&good)==0); restored(&good);
    unsigned total=good.calls;
    unsigned injected=total;
    // Every single transfer can fail, including cleanup. Never report success.
    for(unsigned i=1;i<=total;i++) {
        mock m=initial(); m.fail_at=i;
        assert(run(&m)!=0); assert(m.failures==1);
        // All failures before rollback must still restore the complete state.
        if(m.calls!=i) restored(&m);
    }
    for(unsigned i=1;i<50;i++) {
        mock m=initial(); m.cancel_at=i;
        assert(run(&m)!=0); restored(&m);
    }
    mock stuck=initial(); stuck.pll_stuck=1;
    assert(run(&stuck)!=0); assert(stuck.calls<100);
    mock busy=initial(); busy.bridge[0x74][0]=0x78;
    assert(run(&busy)!=0); assert(busy.writes==0);
    mock applied=initial(); applied.power_transaction_error=1;
    assert(run(&applied)==0); restored(&applied);
    mock not_applied=initial(); not_applied.power_transaction_error=1; not_applied.power_not_applied=1;
    assert(run(&not_applied)!=0); restored(&not_applied);
    for(unsigned standard=1;standard<=3;standard++) {
        mock av=initial(); av.standard=standard; av.line_audio=1;
        assert(run(&av)==0); restored(&av);
        injected+=av.calls;
        for(unsigned i=1;i<=av.calls;i++) {
            mock m=initial(); m.standard=standard; m.line_audio=1; m.fail_at=i;
            assert(run(&m)!=0);
            if(i<=av.forward_calls) restored(&m);
        }
    }
    printf("PASS: %u transfer failures across AFE/PAL/SECAM/NTSC+audio, cancellation, bounded PLL, busy-state refusal\n",injected);
}
