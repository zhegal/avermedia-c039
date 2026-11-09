// SPDX-License-Identifier: GPL-2.0-or-later
/* Windows transport for the unchanged shared AV/Auto register engine.
 * Scheduled ISO reads use a common bus frame; no callback-arrival timestamps.
 * This file is selected only by the Windows build, never the macOS Makefile. */
#define UNICODE
#define _UNICODE
#include <windows.h>
#include <setupapi.h>
#include <winusb.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "capture_device.h"
#include "capture_windows.h"
#include "av_init.h"

int c039_windows_set_log_path(const wchar_t *path) {
    if(!path || !*path) return 1;
    if(!_wfreopen(path,L"a",stderr)) return 1;
    fputs("native_log_redirected=yes\n",stderr); fflush(stderr);
    return 0;
}

enum { SLOTS=32, PACKETS=64, TRANSFER_MS=8 };
static const GUID application_guid={0xdc5d64d5,0x1ddb,0x4b6f,{0x80,0xcb,0x34,0x72,0x92,0x79,0x54,0xae}};
typedef struct {
    OVERLAPPED operation;
    USBD_ISO_PACKET_DESCRIPTOR packets[PACKETS];
    WINUSB_ISOCH_BUFFER_HANDLE registration;
    uint8_t *data;
    uint64_t frame;
    int pending;
} iso_slot;
typedef struct {
    WINUSB_INTERFACE_HANDLE usb;
    UCHAR saved_alt,pipe;
    unsigned number,capacity;
    int changed_alt;
    uint64_t submitted,consumed,bytes,packets,bad;
    iso_slot slots[SLOTS];
} iso_stream;
struct c039_session {
    volatile LONG stopped;
    unsigned standard,seconds,attenuation;
    int endpoint,used,transport_result,retain_resources;
    HANDLE device;
    WINUSB_INTERFACE_HANDLE interfaces[7];
    c039_sample_callback payload;
    void *context;
    void (*standard_changed)(void *,const c039_video_standard *);
    void (*signal_changed)(void *,const c039_signal_status *);
    c039_windows_batch_callback batch;
};
static int win_error(const char *operation) {
    fprintf(stderr,"%s failed Windows error=%lu\n",operation,GetLastError()); return 1;
}
c039_session *c039_session_create(unsigned standard,int endpoint,unsigned seconds) {
    if((standard!=C039_AUTO && !c039_standard(standard)) || (endpoint!=0 && endpoint!=4) || seconds>3600) return NULL;
    c039_session *s=calloc(1,sizeof(*s));
    if(s) { s->standard=standard; s->endpoint=endpoint; s->seconds=seconds; s->attenuation=6; s->device=INVALID_HANDLE_VALUE; }
    return s;
}
void c039_session_stop(c039_session *s) { if(s) InterlockedExchange(&s->stopped,1); }
void c039_session_destroy(c039_session *s) { free(s); }
void c039_session_set_attenuation(c039_session *s,unsigned db) { if(s && !s->used && db<=48) s->attenuation=db; }
void c039_session_set_standard_callback(c039_session *s,void (*callback)(void *,const c039_video_standard *)) {
    if(s && !s->used) s->standard_changed=callback;
}
void c039_session_set_signal_callback(c039_session *s,void (*callback)(void *,const c039_signal_status *)) {
    if(s && !s->used) s->signal_changed=callback;
}
void c039_windows_session_set_batch_callback(c039_session *s,c039_windows_batch_callback callback) {
    if(s && !s->used) s->batch=callback;
}
static int cancelled(void *context) { return InterlockedCompareExchange(&((c039_session *)context)->stopped,0,0)!=0; }
static void delay(void *context,unsigned ms) { (void)context; Sleep(ms); }
static void changed(void *context,const c039_video_standard *profile) {
    c039_session *s=context;
    if(s->standard_changed) s->standard_changed(s->context,profile);
}
static void signal_changed(void *context,const c039_signal_status *status) {
    c039_session *s=context;
    if(s->signal_changed) s->signal_changed(s->context,status);
}
static int control(void *context,int write,uint8_t request,uint16_t value,uint16_t index,uint8_t *data,unsigned size) {
    c039_session *s=context;
    if(size>UINT16_MAX || (size && !data)) return C039_CONTROL_ERROR;
    WINUSB_SETUP_PACKET setup={write?0x40:0xc0,request,value,index,(USHORT)size};
    ULONG transferred=0;
    BOOL ok=WinUsb_ControlTransfer(s->interfaces[1],setup,data,(ULONG)size,&transferred,NULL);
    if(ok && transferred==size) return 0;
    DWORD code=ok?ERROR_INVALID_DATA:GetLastError();
    fprintf(stderr,"WinUSB control write=%d request=%02x value=%04x index=%04x bytes=%lu/%u error=%lu\n",
            write,request,value,index,transferred,size,code);
    /* Only the shared engine's known power-transition write can reconcile a
     * failed USB transaction, and only by exact successful register readback. */
    return !ok && code==ERROR_GEN_FAILURE?C039_CONTROL_TRANSACTION_ERROR:C039_CONTROL_ERROR;
}
static int bridge(c039_session *s,int write,unsigned reg,uint8_t data[4]) {
    return control(s,write,write?0x0c:0x0d,0x000f,(uint16_t)reg,data,4);
}
static int restore_bridge(c039_session *s,unsigned reg,uint8_t saved[4]) {
    uint8_t actual[4]={0};
    int failed=bridge(s,1,reg,saved);
    failed|=bridge(s,0,reg,actual) || memcmp(actual,saved,4)!=0;
    fprintf(stderr,"restore bridge reg=%04x verified=%s\n",reg,failed?"no":"yes"); return failed;
}
static int open_device(c039_session *s) {
    HDEVINFO list=SetupDiGetClassDevsW(&application_guid,NULL,NULL,DIGCF_PRESENT|DIGCF_DEVICEINTERFACE);
    if(list==INVALID_HANDLE_VALUE) return win_error("enumerate WinUSB application interfaces");
    unsigned found=0; wchar_t *path=NULL;
    for(DWORD n=0;;n++) {
        SP_DEVICE_INTERFACE_DATA entry={0}; entry.cbSize=sizeof(entry);
        if(!SetupDiEnumDeviceInterfaces(list,NULL,&application_guid,n,&entry)) break;
        DWORD size=0;
        SetupDiGetDeviceInterfaceDetailW(list,&entry,NULL,0,&size,NULL);
        SP_DEVICE_INTERFACE_DETAIL_DATA_W *detail=calloc(1,size);
        SP_DEVINFO_DATA device={0}; device.cbSize=sizeof(device);
        if(!detail) { free(path); SetupDiDestroyDeviceInfoList(list); return 1; }
        detail->cbSize=sizeof(*detail);
        wchar_t id[512];
        if(SetupDiGetDeviceInterfaceDetailW(list,&entry,detail,size,NULL,&device) &&
           SetupDiGetDeviceInstanceIdW(list,&device,id,512,NULL)) {
            const wchar_t *prefix=L"USB\\VID_07CA&PID_C039&MI_01\\";
            if(!_wcsnicmp(id,prefix,wcslen(prefix))) { found++; free(path); path=_wcsdup(detail->DevicePath); }
        }
        free(detail);
    }
    SetupDiDestroyDeviceInfoList(list);
    if(found!=1 || !path) { fprintf(stderr,"Expected one accessible C039 MI_01, found %u; no driver change attempted\n",found); free(path); return 1; }
    s->device=CreateFileW(path,GENERIC_READ|GENERIC_WRITE,0,NULL,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL|FILE_FLAG_OVERLAPPED,NULL);
    free(path);
    if(s->device==INVALID_HANDLE_VALUE) return win_error("open C039 MI_01 exclusively");
    if(!WinUsb_Initialize(s->device,&s->interfaces[1])) return win_error("WinUsb_Initialize");
    USB_INTERFACE_DESCRIPTOR descriptor;
    if(!WinUsb_QueryInterfaceSettings(s->interfaces[1],0,&descriptor) || descriptor.bInterfaceNumber!=1) {
        fputs("Unexpected primary WinUSB interface; refusing hardware writes\n",stderr); return 1;
    }
    for(UCHAR n=0;n<5;n++) {
        WINUSB_INTERFACE_HANDLE handle=NULL;
        if(!WinUsb_GetAssociatedInterface(s->interfaces[1],n,&handle)) return win_error("associated interface");
        if(!WinUsb_QueryInterfaceSettings(handle,0,&descriptor) || descriptor.bInterfaceNumber<2 || descriptor.bInterfaceNumber>6 || s->interfaces[descriptor.bInterfaceNumber]) {
            WinUsb_Free(handle); fputs("Unexpected associated interface layout\n",stderr); return 1;
        }
        s->interfaces[descriptor.bInterfaceNumber]=handle;
    }
    ULONG timeout=2000;
    if(!WinUsb_SetPipePolicy(s->interfaces[1],0,PIPE_TRANSFER_TIMEOUT,sizeof(timeout),&timeout)) return win_error("control timeout policy");
    for(unsigned n=1;n<7;n++) {
        UCHAR alt=255;
        if(!WinUsb_GetCurrentAlternateSetting(s->interfaces[n],&alt)) return win_error("check idle function alternate");
        if(alt) { fprintf(stderr,"Refusing non-idle interface=%u alt=%u\n",n,alt); return 1; }
    }
    uint8_t endpoints[4];
    if(bridge(s,0,0x18,endpoints) || (endpoints[0]&0x3f)) { fputs("Refusing non-idle endpoint mask\n",stderr); return 1; }
    return 0;
}
static int prepare(iso_stream *stream,c039_session *s,unsigned number) {
    stream->number=number; stream->usb=s->interfaces[number];
    stream->capacity=number==4?2892:28; stream->pipe=(UCHAR)(0x80|number);
    if(!WinUsb_GetCurrentAlternateSetting(stream->usb,&stream->saved_alt)) return win_error("read alternate");
    if(stream->saved_alt) { fputs("Refusing already active ISO alternate\n",stderr); return 1; }
    if(!WinUsb_SetCurrentAlternateSetting(stream->usb,number==4?3:1)) return win_error("set ISO alternate");
    stream->changed_alt=1;
    WINUSB_PIPE_INFORMATION_EX info;
    if(!WinUsb_QueryPipeEx(stream->usb,number==4?3:1,0,&info)) return win_error("ISO pipe properties");
    if(info.PipeType!=UsbdPipeTypeIsochronous || info.PipeId!=stream->pipe || info.Interval!=1 || info.MaximumBytesPerInterval!=stream->capacity) {
        fputs("Unexpected ISO pipe capacity/type/interval\n",stderr); return 1;
    }
    fprintf(stderr,"ISO prepared interface=%u alt=%u pipe=%02x capacity=%u\n",number,number==4?3:1,stream->pipe,stream->capacity);
    return 0;
}
static int register_buffers(iso_stream *stream) {
    for(unsigned n=0;n<SLOTS;n++) {
        iso_slot *slot=&stream->slots[n];
        slot->data=calloc(PACKETS,stream->capacity);
        slot->operation.hEvent=CreateEventW(NULL,TRUE,FALSE,NULL);
        if(!slot->data || !slot->operation.hEvent) return 1;
        if(!WinUsb_RegisterIsochBuffer(stream->usb,stream->pipe,slot->data,PACKETS*stream->capacity,&slot->registration)) return win_error("register ISO buffer");
    }
    return 0;
}
static int submit(iso_stream *stream,iso_slot *slot,uint64_t frame) {
    memset(slot->packets,0,sizeof(slot->packets));
    ResetEvent(slot->operation.hEvent);
    slot->operation.Internal=slot->operation.InternalHigh=0;
    slot->operation.Offset=slot->operation.OffsetHigh=0;
    slot->frame=frame;
    ULONG next=(ULONG)frame;
    BOOL ok=WinUsb_ReadIsochPipe(slot->registration,0,PACKETS*stream->capacity,&next,PACKETS,slot->packets,&slot->operation);
    if(!ok && GetLastError()!=ERROR_IO_PENDING) return win_error("submit scheduled ISO read");
    slot->pending=1; stream->submitted++;
    if(next!=(ULONG)(frame+TRANSFER_MS)) {
        fprintf(stderr,"ISO scheduling mismatch requested=%llu returned_next=%lu\n",(unsigned long long)frame,next); return 1;
    }
    return 0;
}
static int consume(iso_stream *stream,c039_session *s,iso_slot *slot) {
    DWORD ignored=0;
    if(!WinUsb_GetOverlappedResult(stream->usb,&slot->operation,&ignored,FALSE)) {
        if(GetLastError()==ERROR_IO_INCOMPLETE) return 0;
        DWORD code=GetLastError();
        slot->pending=0; stream->bad++;
        for(unsigned n=0;n<8;n++) fprintf(stderr,"failed_iso_packet endpoint=%u packet=%u status=%08lx length=%lu\n",
            stream->number,n,slot->packets[n].Status,slot->packets[n].Length);
        SetLastError(code); return win_error("ISO transfer completion");
    }
    slot->pending=0;
    uint64_t batch_bytes=0;
    for(unsigned n=0;n<PACKETS;n++) {
        USBD_ISO_PACKET_DESCRIPTOR *packet=&slot->packets[n];
        stream->packets++;
        if(packet->Status || packet->Length>stream->capacity || packet->Offset>PACKETS*stream->capacity ||
           packet->Length>PACKETS*stream->capacity-packet->Offset) {
            fprintf(stderr,"ISO packet failure endpoint=%u frame=%llu micro=%u status=%08lx length=%lu offset=%lu\n",
                    stream->number,(unsigned long long)(slot->frame+n/8),n%8,packet->Status,packet->Length,packet->Offset);
            stream->bad++; return 1;
        }
        uint64_t timestamp=(slot->frame+n/8)*1000+(n%8)*125;
        if(!s->batch) {
            if(s->payload(s->context,(int)stream->number,slot->data+packet->Offset,packet->Length,timestamp)) return 1;
            stream->bytes+=packet->Length;
        } else batch_bytes+=packet->Length;
    }
    if(s->batch) {
        if(s->batch(s->context,(int)stream->number,slot->data,PACKETS*stream->capacity,slot->packets,PACKETS,slot->frame*1000)) return 1;
        stream->bytes+=batch_bytes;
    }
    stream->consumed++;
    return 0;
}
static int cleanup(iso_stream *stream) {
    int failed=0;
    ULONGLONG until=GetTickCount64()+2000;
    for(unsigned n=0;n<SLOTS;n++) {
        iso_slot *slot=&stream->slots[n];
        if(slot->pending) {
            ULONGLONG now=GetTickCount64();
            DWORD left=now<until?(DWORD)(until-now):0;
            if(WaitForSingleObject(slot->operation.hEvent,left)!=WAIT_OBJECT_0) {
                fputs("ISO drain timeout: retaining buffers/handles until process exit\n",stderr); return 2;
            }
            DWORD ignored=0;
            if(!WinUsb_GetOverlappedResult(stream->usb,&slot->operation,&ignored,FALSE) && GetLastError()!=ERROR_OPERATION_ABORTED) {
                /* The signaled operation is drained even when its transfer
                 * failed. Keep that source error separate from restore failure. */
                stream->bad++; win_error("drained failed ISO result");
            }
            slot->pending=0;
        }
    }
    for(unsigned n=0;n<SLOTS;n++) {
        iso_slot *slot=&stream->slots[n];
        if(slot->registration && !WinUsb_UnregisterIsochBuffer(slot->registration)) {
            win_error("unregister ISO buffer"); return 2;
        }
        slot->registration=NULL;
        if(slot->operation.hEvent) CloseHandle(slot->operation.hEvent);
        slot->operation.hEvent=NULL;
        free(slot->data); slot->data=NULL;
    }
    fprintf(stderr,"iso_summary endpoint=%u bytes=%llu transfers=%llu packets=%llu packet_errors=%llu cleanup_failed=%d\n",
            stream->number,(unsigned long long)stream->bytes,(unsigned long long)stream->consumed,
            (unsigned long long)stream->packets,(unsigned long long)stream->bad,failed);
    return failed;
}
static int ready(void *context,int (*monitor)(void *),void *monitor_context) {
    c039_session *s=context;
    unsigned count=s->endpoint==4?1:2;
    iso_stream *streams=calloc(count,sizeof(*streams));
    if(!streams) return 1;
    int failed=0,cleanup_failed=0,restore_ep=0,restore_ts=0;
    uint8_t ep[4]={0},ts[4]={0};
    for(unsigned n=0;!failed && n<count;n++) failed=prepare(&streams[n],s,n?3:4);
    /* WinUSB reconfigures the function when selecting associated alternates.
     * Finish all selections before any endpoint buffer registration. */
    for(unsigned n=0;!failed && n<count;n++) failed=register_buffers(&streams[n]);
    if(!failed) failed=bridge(s,0,0x18,ep) || bridge(s,0,0x4,ts);
    if(!failed && (ep[0]&0x3f)) { fputs("Refusing active endpoint mask\n",stderr); failed=1; }
    if(!failed) {
        uint8_t mode[4]={0,s->endpoint==4?1:0x93,0,0}; restore_ts=1;
        failed=bridge(s,1,0x4,mode);
    }
    ULONG current=0; LARGE_INTEGER at;
    if(!failed && (!WinUsb_GetCurrentFrameNumber(streams[0].usb,&current,&at) || !WinUsb_GetAdjustedFrameNumber(&current,at))) failed=win_error("USB bus frame");
    uint64_t first=(uint64_t)current+64;
    uint64_t wanted=s->seconds?(uint64_t)s->seconds*1000/TRANSFER_MS:UINT64_MAX;
    for(unsigned n=0;!failed && n<count;n++)
        for(unsigned i=0;!failed && i<SLOTS && i<wanted;i++) failed=submit(&streams[n],&streams[n].slots[i],first+(uint64_t)i*TRANSFER_MS);
    if(!failed) {
        uint8_t enabled[4]; memcpy(enabled,ep,4); enabled[0]|=s->endpoint==4?8:12;
        restore_ep=1; failed=bridge(s,1,0x18,enabled);
    }
    ULONGLONG deadline=GetTickCount64()+(ULONGLONG)s->seconds*1000+3000,next_monitor=GetTickCount64();
    while(!failed && !cancelled(s)) {
        int finished=1;
        for(unsigned n=0;n<count;n++) if(streams[n].consumed<wanted) finished=0;
        if(finished) break;
        ULONGLONG now=GetTickCount64();
        if(s->seconds && now>deadline) { fputs("ISO capture deadline exceeded\n",stderr); failed=1; break; }
        if(monitor && now>=next_monitor) { failed=monitor(monitor_context); next_monitor=GetTickCount64()+200; }
        for(unsigned n=0;!failed && n<count;n++) {
            iso_stream *stream=&streams[n];
            while(!failed && stream->consumed<wanted) {
                iso_slot *slot=&stream->slots[stream->consumed%SLOTS];
                if(!slot->pending || WaitForSingleObject(slot->operation.hEvent,0)!=WAIT_OBJECT_0) break;
                failed=consume(stream,s,slot);
                if(!failed && stream->submitted<wanted)
                    failed=submit(stream,slot,first+stream->submitted*TRANSFER_MS);
            }
        }
        if(!failed) Sleep(1);
    }
    if(restore_ep) cleanup_failed|=restore_bridge(s,0x18,ep);
    /* Admission is closed. Already scheduled reads finish within 256 ms;
     * drain them without resubmission before unregistering. CancelIoEx/AbortPipe
     * invalidate WinUSB ISO registrations on this host and prevent orderly
     * unregister. A two-second drain deadline still bounds unplug/stall errors. */
    for(unsigned n=0;n<count;n++) {
        int result=cleanup(&streams[n]);
        if(result==2) s->retain_resources=1;
        cleanup_failed|=result!=0;
        failed|=!streams[n].bytes || streams[n].bad!=0;
    }
    /* Setting an associated alternate can invalidate endpoint registrations.
     * All streams must drain/unregister before restoring any alternate. */
    if(!s->retain_resources) for(unsigned n=0;n<count;n++)
        if(streams[n].changed_alt && !WinUsb_SetCurrentAlternateSetting(streams[n].usb,streams[n].saved_alt))
            cleanup_failed|=win_error("restore ISO alternate");
    if(restore_ts) cleanup_failed|=restore_bridge(s,0x4,ts);
    if(!s->retain_resources) free(streams);
    s->transport_result=cleanup_failed?2:failed;
    return s->transport_result;
}
int c039_session_run(c039_session *s,c039_sample_callback payload,void *context) {
    if(!s || !payload || s->used) return 1;
    s->used=1; s->payload=payload; s->context=context;
    if(cancelled(s)) return 0;
    int failed=open_device(s);
    if(!failed) {
        c039_transport transport={.context=s,.control=control,.sleep_ms=delay,.cancelled=cancelled,
            .on_ready=ready,.video_standard=s->standard,.standard_changed=changed,
            .line_audio=s->endpoint==0,.audio_attenuation_db=s->attenuation,.allow_powered_idle=1,
            .signal_changed=signal_changed};
        uint16_t id=0;
        failed=c039_av_probe(&transport,&id,1);
    }
    if(!s->retain_resources) {
        for(unsigned n=2;n<7;n++) if(s->interfaces[n]) WinUsb_Free(s->interfaces[n]);
        if(s->interfaces[1]) WinUsb_Free(s->interfaces[1]);
        if(s->device!=INVALID_HANDLE_VALUE) CloseHandle(s->device);
    }
    return failed==2 || s->transport_result==2?2:failed || s->transport_result;
}
