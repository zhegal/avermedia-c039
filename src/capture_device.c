// SPDX-License-Identifier: GPL-2.0-or-later
// Embeddable transport: no child processes, signal handlers or payload files.
#include "capture_device.h"
#include "av_init.h"
#include "iso_probe.h"
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOCFPlugIn.h>
#include <stdatomic.h>
#include <stdlib.h>
#include <stdio.h>
#include <time.h>

struct c039_session {
    atomic_bool stopped;
    unsigned standard,seconds,attenuation;
    int endpoint,used,transport_result;
    IOUSBDeviceInterface182 **device;
    c039_sample_callback payload;
    void *payload_context;
    void (*standard_changed)(void *,const c039_video_standard *);
    void (*signal_changed)(void *,const c039_signal_status *);
};
c039_session *c039_session_create(unsigned standard,int endpoint,unsigned seconds) {
    if((standard!=C039_AUTO && !c039_standard(standard)) || (endpoint!=0 && endpoint!=4) || seconds>3600) return NULL;
    c039_session *s=calloc(1,sizeof(*s));
    if(s) { atomic_init(&s->stopped,0); s->standard=standard; s->endpoint=endpoint; s->seconds=seconds; s->attenuation=6; }
    return s;
}
void c039_session_stop(c039_session *s) { if(s) atomic_store(&s->stopped,1); }
void c039_session_destroy(c039_session *s) { free(s); }
void c039_session_set_attenuation(c039_session *s,unsigned db) { if(s && !s->used && db<=48) s->attenuation=db; }
void c039_session_set_standard_callback(c039_session *s,void (*callback)(void *,const c039_video_standard *)) {
    if(s && !s->used) s->standard_changed=callback;
}
void c039_session_set_signal_callback(c039_session *s,void (*callback)(void *,const c039_signal_status *)) {
    if(s && !s->used) s->signal_changed=callback;
}
static void changed(void *context,const c039_video_standard *profile) {
    c039_session *s=context;
    if(s->standard_changed) s->standard_changed(s->payload_context,profile);
}
static void signal_changed(void *context,const c039_signal_status *status) {
    c039_session *s=context;
    if(s->signal_changed) s->signal_changed(s->payload_context,status);
}
static int cancelled(void *context) { return atomic_load(&((c039_session *)context)->stopped); }
static void delay(void *context,unsigned ms) {
    (void)context;
    struct timespec t={ms/1000,(ms%1000)*1000000}; nanosleep(&t,NULL);
}
static int control(void *context,int write,uint8_t request,uint16_t value,
                   uint16_t index,uint8_t *data,unsigned size) {
    IOUSBDeviceInterface182 **dev=((c039_session *)context)->device;
    IOUSBDevRequestTO r={.bmRequestType=write?0x40:0xc0,.bRequest=request,.wValue=value,
        .wIndex=index,.wLength=size,.pData=data,.noDataTimeout=1000,.completionTimeout=2000};
    IOReturn code=(*dev)->DeviceRequestTO(dev,&r);
    if(code) fprintf(stderr,"capture control error=%08x write=%d value=%04x index=%04x\n",code,write,value,index);
    if(code==kIOReturnNotResponding) return C039_CONTROL_TRANSACTION_ERROR;
    return code || r.wLenDone!=size;
}
static int ready(void *context,int (*monitor)(void *),void *monitor_context) {
    c039_session *s=context;
    s->transport_result=c039_iso_capture(s->device,s->endpoint,s->seconds,s->payload,s->payload_context,
                                         cancelled,s,monitor,monitor_context);
    return s->transport_result;
}
int c039_session_run(c039_session *s,c039_sample_callback payload,void *context) {
    if(!s || !payload || s->used) return 1;
    s->used=1; s->payload=payload; s->payload_context=context;
    if(cancelled(s)) return 0;
    CFMutableDictionaryRef match=IOServiceMatching(kIOUSBDeviceClassName);
    if(!match) return 1;
    int vid=0x07ca,pid=0xc039;
    CFNumberRef v=CFNumberCreate(NULL,kCFNumberIntType,&vid),p=CFNumberCreate(NULL,kCFNumberIntType,&pid);
    CFDictionarySetValue(match,CFSTR(kUSBVendorID),v); CFDictionarySetValue(match,CFSTR(kUSBProductID),p);
    CFRelease(v); CFRelease(p);
    io_service_t service=IOServiceGetMatchingService(kIOMainPortDefault,match);
    if(!service) { fprintf(stderr,"C039 not connected\n"); return 1; }
    IOCFPlugInInterface **plugin=NULL; SInt32 score=0;
    IOReturn code=IOCreatePlugInInterfaceForService(service,kIOUSBDeviceUserClientTypeID,
        kIOCFPlugInInterfaceID,&plugin,&score);
    IOObjectRelease(service);
    if(code || !plugin) return 1;
    HRESULT query=(*plugin)->QueryInterface(plugin,CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID182),(LPVOID *)&s->device);
    IODestroyPlugInInterface(plugin);
    if(query || !s->device) return 1;
    IOUSBDeviceInterface182 **dev=s->device;
    code=(*dev)->USBDeviceOpen(dev);
    int failed=code!=0;
    if(!code) {
        c039_transport transport={.context=s,.control=control,.sleep_ms=delay,.cancelled=cancelled,
            .on_ready=ready,.video_standard=s->standard,.standard_changed=changed,
            .line_audio=s->endpoint==0,.audio_attenuation_db=s->attenuation,.signal_changed=signal_changed};
        uint16_t id=0;
        failed=c039_av_probe(&transport,&id,1);
        IOReturn closed=(*dev)->USBDeviceClose(dev);
        fprintf(stderr,"capture USBDeviceClose=%08x\n",closed); failed|=closed!=0;
    } else fprintf(stderr,"capture USBDeviceOpen=%08x\n",code);
    (*dev)->Release(dev); s->device=NULL;
    // Cancellation is reported separately from an initialization/rollback error.
    return s->transport_result==2?2:failed;
}
