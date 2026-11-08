// SPDX-License-Identifier: MIT
// Bounded video endpoint diagnostic. No decoder/firmware writes.
#include "iso_probe.h"
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOCFPlugIn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

enum { SLOTS=8, PACKETS=64, CAPACITY=2892 };
typedef struct {
    uint8_t data[PACKETS*CAPACITY];
    IOUSBIsocFrame frames[PACKETS];
    IOReturn result;
    UInt64 bus;
    int done,pending;
} slot;
typedef struct {
    slot slots[SLOTS];
} storage;
static void completed(void *context,IOReturn result,void *arg) {
    (void)arg; slot *s=context; s->result=result; s->done=1; s->pending=0;
}
static int request(IOUSBDeviceInterface182 **dev,int write,unsigned reg,uint8_t data[4]) {
    IOUSBDevRequestTO req={.bmRequestType=write?0x40:0xc0,.bRequest=write?0xc:0xd,
        .wValue=0xf,.wIndex=reg,.wLength=4,.pData=data,
        .noDataTimeout=1000,.completionTimeout=2000};
    IOReturn r=(*dev)->DeviceRequestTO(dev,&req);
    printf("iso bridge %s reg=%04x status=%08x data=%02x%02x%02x%02x\n",
        write?"OUT":"IN",reg,r,data[0],data[1],data[2],data[3]);
    return r || req.wLenDone!=4;
}
static IOUSBInterfaceInterface182 **open_stream(IOUSBDeviceInterface182 **dev,int endpoint,UInt8 *saved) {
    IOUSBFindInterfaceRequest req={kIOUSBFindInterfaceDontCare,kIOUSBFindInterfaceDontCare,
        kIOUSBFindInterfaceDontCare,kIOUSBFindInterfaceDontCare};
    io_iterator_t iterator=0;
    if((*dev)->CreateInterfaceIterator(dev,&req,&iterator)) return NULL;
    io_service_t service; IOUSBInterfaceInterface182 **out=NULL;
    while((service=IOIteratorNext(iterator))) {
        IOCFPlugInInterface **plugin=NULL; SInt32 score=0;
        IOReturn r=IOCreatePlugInInterfaceForService(service,kIOUSBInterfaceUserClientTypeID,
            kIOCFPlugInInterfaceID,&plugin,&score);
        IOObjectRelease(service);
        if(r || !plugin) continue;
        IOUSBInterfaceInterface182 **intf=NULL;
        HRESULT hr=(*plugin)->QueryInterface(plugin,CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID182),(LPVOID *)&intf);
        IODestroyPlugInInterface(plugin);
        if(hr || !intf) continue;
        UInt8 number=255; r=(*intf)->GetInterfaceNumber(intf,&number);
        if(r || number!=endpoint) { (*intf)->Release(intf); continue; }
        r=(*intf)->USBInterfaceOpen(intf);
        if(!r) {
            r=(*intf)->GetAlternateSetting(intf,saved);
            if(!r && *saved) r=kIOReturnExclusiveAccess;
            if(!r) r=(*intf)->SetAlternateInterface(intf,endpoint==4?3:1);
            if(!r) out=intf;
            else (*intf)->USBInterfaceClose(intf);
        }
        printf("iso open interface=%d alt=%d status=%08x\n",endpoint,endpoint==4?3:1,r);
        if(!out) (*intf)->Release(intf);
        break;
    }
    IOObjectRelease(iterator); return out;
}
static int submit(IOUSBInterfaceInterface182 **intf,UInt8 pipe,slot *s,UInt64 bus,unsigned capacity) {
    memset(s->frames,0,sizeof(s->frames));
    for(unsigned i=0;i<PACKETS;i++) s->frames[i].frReqCount=capacity;
    s->done=0; s->bus=bus;
    IOReturn r=(*intf)->ReadIsochPipeAsync(intf,pipe,s->data,bus,PACKETS,s->frames,completed,s);
    if(r) { printf("iso submit bus=%llu status=%08x\n",bus,r); return 1; }
    s->pending=1; return 0;
}
typedef struct {
    IOUSBInterfaceInterface182 **intf;
    CFRunLoopSourceRef source;
    UInt8 saved_alt,pipe;
    int endpoint;
    unsigned capacity,expected,transfers,packets,bad;
    size_t bytes;
    UInt64 next_bus;
    FILE *raw,*log;
    storage *memory;
} stream;
static int prepare(stream *s,IOUSBDeviceInterface182 **dev,const char *path,int endpoint,int telemetry) {
    s->endpoint=endpoint; s->capacity=endpoint==4?2892:28;
    s->intf=open_stream(dev,endpoint,&s->saved_alt);
    if(!s->intf) return 1;
    UInt8 count=0;
    if((*s->intf)->GetNumEndpoints(s->intf,&count)) return 1;
    for(UInt8 p=1;p<=count;p++) {
        UInt8 direction=0,number=0,type=0,interval=0; UInt16 max=0;
        IOReturn r=(*s->intf)->GetPipeProperties(s->intf,p,&direction,&number,&type,&max,&interval);
        printf("iso pipe=%u dir=%u endpoint=%u type=%u max=%u interval=%u status=%08x\n",
            p,direction,number,type,max,interval,r);
        if(!r && direction==kUSBIn && number==endpoint && type==kUSBIsoc && max==s->capacity) s->pipe=p;
    }
    if(!s->pipe) return 1;
    if((*s->intf)->CreateInterfaceAsyncEventSource(s->intf,&s->source)) return 1;
    CFRunLoopAddSource(CFRunLoopGetCurrent(),s->source,kCFRunLoopDefaultMode);
    struct stat info;
    int fifo=lstat(path,&info)==0 && S_ISFIFO(info.st_mode);
    s->raw=fopen(path,fifo?"wb":"wbx");
    char *logpath=malloc(strlen(path)+13);
    if(!logpath) return 1;
    sprintf(logpath,"%s.packets.csv",path);
    s->log=fopen(fifo && !telemetry?"/dev/null":logpath,fifo && !telemetry?"w":"wx");
    free(logpath);
    if(!s->raw || !s->log) { perror("capture output"); return 1; }
    fputs("bus_frame,microframe,transfer_status,packet_status,length,file_offset\n",s->log);
    s->memory=calloc(1,sizeof(*s->memory));
    return !s->memory;
}
static int consume(stream *s,int resubmit) {
    slot *b=&s->memory->slots[s->expected%SLOTS];
    if(!b->done) return 0;
    if(b->result && b->result!=kIOReturnUnderrun) {
        printf("iso transfer endpoint=%d status=%08x bus=%llu\n",s->endpoint,b->result,b->bus);
        s->bad++; return 1;
    }
    for(unsigned i=0;i<PACKETS;i++) {
        IOUSBIsocFrame *f=&b->frames[i];
        fprintf(s->log,"%llu,%u,%08x,%08x,%u,%zu\n",b->bus+i/8,i%8,b->result,f->frStatus,f->frActCount,s->bytes);
        s->packets++;
        if(f->frActCount>s->capacity) { s->bad++; return 1; }
        if(f->frStatus && f->frStatus!=kIOReturnUnderrun) { s->bad++; continue; }
        if(fwrite(b->data+i*s->capacity,1,f->frActCount,s->raw)!=f->frActCount) return 1;
        s->bytes+=f->frActCount;
    }
    b->done=0; s->transfers++; s->expected++;
    if(fflush(s->log)) return 1;
    if(resubmit) {
        int failed=submit(s->intf,s->pipe,b,s->next_bus,s->capacity);
        s->next_bus+=PACKETS/8;
        return failed;
    }
    return 0;
}
static int cleanup(stream *s) {
    int failed=0;
    if(s->intf && s->pipe && s->memory) {
        IOReturn r=(*s->intf)->AbortPipe(s->intf,s->pipe);
        printf("iso AbortPipe endpoint=%d status=%08x\n",s->endpoint,r); failed|=r!=0;
        CFAbsoluteTime until=CFAbsoluteTimeGetCurrent()+2;
        unsigned pending=0;
        do {
            pending=0; for(unsigned i=0;i<SLOTS;i++) pending+=s->memory->slots[i].pending;
            if(!pending) break;
            CFRunLoopRunInMode(kCFRunLoopDefaultMode,0.01,false);
        } while(CFAbsoluteTimeGetCurrent()<until);
        if(pending) { fprintf(stderr,"iso callbacks did not drain; retaining buffers until process exit\n"); failed=1; }
        else free(s->memory);
    } else free(s->memory);
    if(s->source) { CFRunLoopRemoveSource(CFRunLoopGetCurrent(),s->source,kCFRunLoopDefaultMode); CFRelease(s->source); }
    if(s->raw && fclose(s->raw)) failed=1;
    if(s->log && fclose(s->log)) failed=1;
    if(s->intf) {
        IOReturn r=(*s->intf)->SetAlternateInterface(s->intf,s->saved_alt);
        printf("iso restore endpoint=%d alt=%u status=%08x\n",s->endpoint,s->saved_alt,r); failed|=r!=0;
        r=(*s->intf)->USBInterfaceClose(s->intf);
        printf("iso interface endpoint=%d close=%08x\n",s->endpoint,r); failed|=r!=0;
        (*s->intf)->Release(s->intf);
    }
    printf("iso_summary endpoint=%d bytes=%zu transfers=%u packets=%u packet_errors=%u\n",
        s->endpoint,s->bytes,s->transfers,s->packets,s->bad);
    return failed;
}
int c039_iso_probe(IOUSBDeviceInterface182 **dev,const char *path,
                   int endpoint,unsigned seconds,int fifo_telemetry,int (*cancelled)(void *),void *context) {
    if((endpoint!=0 && endpoint!=3 && endpoint!=4) || seconds<1 || seconds>3600) return 1;
    // endpoint=0 captures EP84 and EP83 together, on a shared USB bus timeline.
    stream streams[2]={0}; unsigned count=endpoint?1:2;
    int failed=0,restore_ep=0,restore_ts=0;
    char *video=NULL,*audio=NULL;
    if(!endpoint) {
        video=malloc(strlen(path)+11); audio=malloc(strlen(path)+14);
        if(!video || !audio) failed=1;
        else { sprintf(video,"%s.video.bin",path); sprintf(audio,"%s.audio.s16le",path); }
    }
    if(!failed) failed=prepare(&streams[0],dev,endpoint?path:video,endpoint?endpoint:4,fifo_telemetry);
    if(!failed && count==2) failed=prepare(&streams[1],dev,audio,3,fifo_telemetry);
    uint8_t ep[4]={0},ts[4]={0};
    if(!failed) failed=request(dev,0,0x18,ep) || request(dev,0,0x4,ts);
    if(!failed && (ep[0]&0x3f)) { fprintf(stderr,"refusing an already active endpoint mask\n"); failed=1; }
    if(!failed) {
        uint8_t mode[4]={0,endpoint==4?1:0x93,0,0}; restore_ts=1;
        failed=request(dev,1,0x4,mode);
    }
    UInt64 start_bus=0; AbsoluteTime at;
    if(!failed) failed=(*streams[0].intf)->GetBusFrameNumber(streams[0].intf,&start_bus,&at)!=0;
    start_bus+=20;
    for(unsigned n=0;!failed && n<count;n++) {
        stream *s=&streams[n]; s->next_bus=start_bus;
        for(unsigned i=0;i<SLOTS;i++) {
            if(submit(s->intf,s->pipe,&s->memory->slots[i],s->next_bus,s->capacity)) { failed=1; break; }
            s->next_bus+=PACKETS/8;
        }
    }
    if(!failed) {
        uint8_t enabled[4]; memcpy(enabled,ep,4);
        enabled[0]|=endpoint?(1<<(endpoint-1)):0xc;
        restore_ep=1; failed=request(dev,1,0x18,enabled);
    }
    // A fixed whole number of 8ms transfers yields matching USB time spans.
    unsigned wanted=(seconds*1000)/(PACKETS/8);
    CFAbsoluteTime deadline=CFAbsoluteTimeGetCurrent()+seconds+2;
    while(!failed && !cancelled(context)) {
        int finished=1;
        for(unsigned n=0;n<count;n++) if(streams[n].transfers<wanted) finished=0;
        if(finished) break;
        if(CFAbsoluteTimeGetCurrent()>deadline) { fprintf(stderr,"iso capture deadline exceeded\n"); failed=1; break; }
        CFRunLoopRunInMode(kCFRunLoopDefaultMode,0.002,false);
        for(unsigned n=0;!failed && n<count;n++) {
            stream *s=&streams[n];
            while(s->transfers<wanted && s->memory->slots[s->expected%SLOTS].done) {
                int again=s->transfers+SLOTS<wanted;
                if(consume(s,again)) { failed=1; break; }
            }
        }
    }
    if(restore_ep) {
        failed|=request(dev,1,0x18,ep);
        uint8_t actual[4]={0}; failed|=request(dev,0,0x18,actual) || memcmp(actual,ep,4)!=0;
    }
    for(unsigned n=0;n<count;n++) {
        failed|=cleanup(&streams[n]);
        failed|=!streams[n].bytes || streams[n].bad;
    }
    if(restore_ts) {
        failed|=request(dev,1,0x4,ts);
        uint8_t actual[4]={0}; failed|=request(dev,0,0x4,actual) || memcmp(actual,ts,4)!=0;
    }
    free(video); free(audio);
    return failed || cancelled(context);
}
