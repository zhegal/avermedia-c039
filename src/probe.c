// SPDX-License-Identifier: MIT
// USB descriptor probe and firmware-free experimental Composite A/V capture.
// Default/--registers/--afe are read-only. Active modes restore owned controls.
#include <CoreFoundation/CoreFoundation.h>
#include <IOKit/IOCFPlugIn.h>
#include <IOKit/usb/IOUSBLib.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <mach/mach_error.h>
#include <time.h>
#include <signal.h>
#include "av_init.h"
#include "iso_probe.h"

static volatile sig_atomic_t interrupted=0;
static void on_signal(int sig) { (void)sig; interrupted=1; }
static int av_control(void *context,int write,uint8_t request,uint16_t value,
                       uint16_t index,uint8_t *data,unsigned size) {
    IOUSBDeviceInterface182 **dev=context;
    IOUSBDevRequestTO req={.bmRequestType=write?0x40:0xc0,.bRequest=request,
        .wValue=value,.wIndex=index,.wLength=size,.pData=data,
        .noDataTimeout=1000,.completionTimeout=2000};
    IOReturn r=(*dev)->DeviceRequestTO(dev,&req);
    printf("%s req=%02x value=%04x index=%04x size=%u actual=%u status=%08x data=",
        write?"OUT":"IN",request,value,index,size,(unsigned)req.wLenDone,r);
    if(!r) for(unsigned i=0;i<size;i++) printf("%02x",data[i]);
    putchar('\n');
    if(r==kIOReturnNotResponding) return C039_CONTROL_TRANSACTION_ERROR;
    return r || req.wLenDone!=size;
}
static void av_sleep(void *context,unsigned ms) {
    (void)context;
    struct timespec delay={.tv_sec=ms/1000,.tv_nsec=(ms%1000)*1000000};
    nanosleep(&delay,NULL);
}
static int av_cancelled(void *context) { (void)context; return interrupted; }
static const char *iso_path=NULL;
static int iso_endpoint=4;
static unsigned iso_seconds=1;
static int fifo_telemetry=0;
static int av_iso_ready(void *context) { return c039_iso_probe(context,iso_path,iso_endpoint,iso_seconds,fifo_telemetry,av_cancelled,context); }
static int recover_preview(IOUSBDeviceInterface182 **dev) {
    // Recovery only for the exact state left by our first preview process.
    // The original register values are recorded in evidence/live-preview-01.txt.
    const unsigned regs[]={0x18,4,0x74};
    const uint8_t active[][4]={{8,0,0,4},{0,1,0,0},{0x78,0,0,0}};
    const uint8_t idle[][4]={{0,0,0,4},{0,0,0,0},{0,0,0,0}};
    uint8_t current[3][4];
    for(unsigned i=0;i<3;i++) {
        if(av_control(dev,0,0xd,0xf,regs[i],current[i],4)) return 1;
        if(memcmp(current[i],active[i],4) && memcmp(current[i],idle[i],4)) {
            fprintf(stderr,"refusing recovery: unexpected register %04x\n",regs[i]); return 1;
        }
    }
    for(unsigned i=0;i<3;i++) {
        uint8_t bytes[4]; memcpy(bytes,idle[i],4);
        if(av_control(dev,1,0xc,0xf,regs[i],bytes,4) ||
           av_control(dev,0,0xd,0xf,regs[i],bytes,4) || memcmp(bytes,idle[i],4)) return 1;
    }
    puts("preview_stream_disabled_and_power_restored=yes (previous AFE journal was lost)");
    return 0;
}

static IOUSBInterfaceInterface182 **open_video(IOUSBDeviceInterface182 **dev, UInt8 *saved) {
    IOUSBFindInterfaceRequest request={kIOUSBFindInterfaceDontCare,kIOUSBFindInterfaceDontCare,
        kIOUSBFindInterfaceDontCare,kIOUSBFindInterfaceDontCare};
    io_iterator_t it=0;
    if((*dev)->CreateInterfaceIterator(dev,&request,&it)) return NULL;
    io_service_t service; IOUSBInterfaceInterface182 **video=NULL;
    while((service=IOIteratorNext(it))) {
        IOCFPlugInInterface **plugin=NULL; SInt32 score=0;
        IOReturn r=IOCreatePlugInInterfaceForService(service,kIOUSBInterfaceUserClientTypeID,
            kIOCFPlugInInterfaceID,&plugin,&score);
        IOObjectRelease(service);
        if(r || !plugin) continue;
        IOUSBInterfaceInterface182 **intf=NULL;
        HRESULT hr=(*plugin)->QueryInterface(plugin,CFUUIDGetUUIDBytes(kIOUSBInterfaceInterfaceID182),(LPVOID *)&intf);
        IODestroyPlugInInterface(plugin);
        if(hr || !intf) continue;
        UInt8 number=255;
        r=(*intf)->GetInterfaceNumber(intf,&number);
        if(r || number!=4) { (*intf)->Release(intf); continue; }
        r=(*intf)->USBInterfaceOpen(intf);
        if(!r) {
            r=(*intf)->GetAlternateSetting(intf,saved);
            if(!r && *saved!=0) {
                fprintf(stderr,"refusing wake: video alt=%u already in use\n",*saved);
                r=kIOReturnExclusiveAccess;
            }
            if(!r) r=(*intf)->SetAlternateInterface(intf,3);
            if(!r) video=intf;
            else (*intf)->USBInterfaceClose(intf);
        }
        fprintf(stderr,"video interface 4 alt 3 status=%08x\n",r);
        if(!video) (*intf)->Release(intf);
        break;
    }
    IOObjectRelease(it);
    return video;
}

static int power_transfer(IOUSBDeviceInterface182 **dev, int write, unsigned char bytes[4]) {
    IOUSBDevRequestTO req={.bmRequestType=write?0x40:0xc0,.bRequest=write?0x0c:0x0d,
        .wValue=0xf,.wIndex=0x74,.wLength=4,.pData=bytes,.noDataTimeout=1000,.completionTimeout=2000};
    IOReturn r=(*dev)->DeviceRequestTO(dev,&req);
    fprintf(stderr,"PWR_CTL_EN %s status=%08x actual=%u data=%02x%02x%02x%02x\n",
            write?"write":"read",r,(unsigned)req.wLenDone,bytes[0],bytes[1],bytes[2],bytes[3]);
    return r || req.wLenDone!=4;
}

static unsigned le16(const unsigned char *p) { return p[0] | p[1]<<8; }
static void usage(const char *program) {
    fprintf(stderr,"usage: %s MODE [OPTIONS] [configuration.bin]\n"
        "  --registers | --afe          read-only register diagnostics\n"
        "  --av-power | --av-init       temporary power/AFE/I2S and hardware ID\n"
        "  --iso-probe FILE             video transport, unchanged decoder\n"
        "  --video-probe pal|secam|ntsc FILE  Composite raw endpoint payload\n"
        "  --audio-probe FILE           line PCM, stereo S16_LE 48kHz\n"
        "  --capture pal|secam|ntsc PREFIX   simultaneous video + audio\n"
        "  --calibrate                 AFE calibration (automatic in --capture)\n"
        "  --seconds 1..3600            capture duration (default 1 second)\n"
        "  --audio-attenuation-db 0..48 additional PCM attenuation (default 0)\n"
        "  --wake | --wake-device       historical bridge-only experiments\n"
        "  --recover-preview           exact-state recovery for preview-01 only\n"
        "No mode: descriptors only. --help: show this text. No firmware upload.\n",program);
}
static void result(const char *op, IOReturn r) {
    printf("%s: 0x%08x (%s)\n", op, r, mach_error_string(r));
}
static int read_register(IOUSBDeviceInterface182 **dev, const char *name,
                         UInt8 request, UInt16 value, UInt16 index, UInt16 size) {
    unsigned char bytes[4]={0};
    IOUSBDevRequestTO req={.bmRequestType=0xc0,.bRequest=request,.wValue=value,
        .wIndex=index,.wLength=size,.pData=bytes,.noDataTimeout=1000,.completionTimeout=2000};
    IOReturn r=(*dev)->DeviceRequestTO(dev,&req);
    printf("read %s request=%02x value=%04x index=%04x status=%08x actual=%u data=",
           name,request,value,index,r,(unsigned)req.wLenDone);
    if(!r) for(unsigned i=0;i<req.wLenDone;i++) printf("%02x",bytes[i]);
    putchar('\n');
    if(r || req.wLenDone!=size) return 1;
    if(request==4 && index==0x100) {
        unsigned id=le16(bytes);
        if((id&0xfff0)==0x5a30) printf("decoder_id=%04x decimal=%u (Linux cx231xx identification)\n",id,id);
        else printf("decoder_id=%04x (not confirmed as cx231xx)\n",id);
    }
    return 0;
}
int main(int argc, char **argv) {
    signal(SIGINT,on_signal); signal(SIGTERM,on_signal); signal(SIGPIPE,SIG_IGN);
    setvbuf(stdout,NULL,_IOLBF,0);
    const char *output="configuration.bin"; int registers=0,wake=0,device_only=0,afe=0,av_init=0;
    unsigned video_standard=0; int calibrate=0,recover=0;
    unsigned attenuation=0;
    int modes=0,positions=0;
    for(int i=1;i<argc;i++) {
        int is_mode=strcmp(argv[i],"--calibrate") && strcmp(argv[i],"--seconds") &&
            strcmp(argv[i],"--audio-attenuation-db") && strcmp(argv[i],"--log-fifo-packets") && argv[i][0]=='-';
        if(is_mode) modes++;
        if(!strcmp(argv[i],"--help")) { usage(argv[0]); return 0; }
        if(!strcmp(argv[i],"--registers")) registers=1;
        else if(!strcmp(argv[i],"--wake")) { wake=1; registers=1; }
        else if(!strcmp(argv[i],"--afe")) { afe=1; registers=1; }
        else if(!strcmp(argv[i],"--wake-device")) { wake=1; registers=1; device_only=1; afe=1; }
        else if(!strcmp(argv[i],"--av-init")) av_init=1;
        else if(!strcmp(argv[i],"--calibrate")) calibrate=1;
        else if(!strcmp(argv[i],"--log-fifo-packets")) fifo_telemetry=1;
        else if(!strcmp(argv[i],"--recover-preview")) recover=1;
        else if(!strcmp(argv[i],"--audio-attenuation-db") && i+1<argc) {
            char *end=NULL; unsigned long db=strtoul(argv[++i],&end,10);
            if(!*argv[i] || *end || db>48) { fprintf(stderr,"attenuation must be 0..48 dB\n"); return 64; }
            attenuation=(unsigned)db;
        }
        else if(!strcmp(argv[i],"--av-power")) av_init=2;
        else if(!strcmp(argv[i],"--iso-probe") && i+1<argc) { iso_path=argv[++i]; av_init=2; }
        else if(!strcmp(argv[i],"--audio-probe") && i+1<argc) { iso_path=argv[++i]; iso_endpoint=3; av_init=2; }
        else if(!strcmp(argv[i],"--seconds") && i+1<argc) {
            char *end=NULL; unsigned long seconds=strtoul(argv[++i],&end,10);
            if(!*argv[i] || *end || seconds<1 || seconds>3600) { fprintf(stderr,"seconds must be 1..3600\n"); return 64; }
            iso_seconds=(unsigned)seconds;
        }
        else if(!strcmp(argv[i],"--video-probe") && i+2<argc) {
            const char *standard=argv[++i];
            video_standard=!strcmp(standard,"pal")?1:!strcmp(standard,"secam")?2:!strcmp(standard,"ntsc")?3:0;
            if(!video_standard) { fprintf(stderr,"expected pal, secam or ntsc\n"); return 64; }
            iso_path=argv[++i]; av_init=2;
        }
        else if(!strcmp(argv[i],"--capture") && i+2<argc) {
            const char *standard=argv[++i];
            video_standard=!strcmp(standard,"pal")?1:!strcmp(standard,"secam")?2:!strcmp(standard,"ntsc")?3:0;
            if(!video_standard) { fprintf(stderr,"expected pal, secam or ntsc\n"); return 64; }
            iso_path=argv[++i]; av_init=2; calibrate=1; iso_endpoint=0;
        }
        else if(argv[i][0]=='-') { usage(argv[0]); return 64; }
        else { output=argv[i]; positions++; }
    }
    if(modes>1 || positions>1 || (calibrate && !av_init) || (iso_seconds!=1 && !iso_path) ||
       (attenuation && (!iso_path || iso_endpoint==4))) { usage(argv[0]); return 64; }
    if(av_init && (wake || registers)) { fprintf(stderr,"--av-init cannot be combined with other modes\n"); return 64; }
    CFMutableDictionaryRef match=IOServiceMatching(kIOUSBDeviceClassName);
    int vid=0x07ca,pid=0xc039;
    CFNumberRef v=CFNumberCreate(NULL,kCFNumberIntType,&vid);
    CFNumberRef p=CFNumberCreate(NULL,kCFNumberIntType,&pid);
    CFDictionarySetValue(match,CFSTR(kUSBVendorID),v);
    CFDictionarySetValue(match,CFSTR(kUSBProductID),p);
    CFRelease(v); CFRelease(p);
    io_service_t service=IOServiceGetMatchingService(kIOMainPortDefault,match);
    if (!service) { fprintf(stderr,"07ca:c039 not found\n"); return 1; }
    io_connect_t connection=0;
    IOReturn direct=IOServiceOpen(service,mach_task_self(),0,&connection);
    result("IOServiceOpen diagnostic",direct);
    if(!direct) IOServiceClose(connection);
    IOCFPlugInInterface **plugin=NULL; SInt32 score=0;
    IOReturn r=IOCreatePlugInInterfaceForService(service,kIOUSBDeviceUserClientTypeID,
                           kIOCFPlugInInterfaceID,&plugin,&score);
    IOObjectRelease(service); result("IOCreatePlugInInterfaceForService",r);
    if (r || !plugin) return 2;
    IOUSBDeviceInterface182 **dev=NULL;
    HRESULT hr=(*plugin)->QueryInterface(plugin,CFUUIDGetUUIDBytes(kIOUSBDeviceInterfaceID182),(LPVOID *)&dev);
    IODestroyPlugInInterface(plugin);
    if (hr || !dev) { fprintf(stderr,"QueryInterface: %08x\n",(unsigned)hr); return 2; }
    UInt16 vendor=0,product=0,release=0; UInt8 count=0,speed=0;
    (*dev)->GetDeviceVendor(dev,&vendor); (*dev)->GetDeviceProduct(dev,&product);
    (*dev)->GetDeviceReleaseNumber(dev,&release); (*dev)->GetNumberOfConfigurations(dev,&count);
    (*dev)->GetDeviceSpeed(dev,&speed);
    printf("device=%04x:%04x bcdDevice=%04x configurations=%u speed=%u\n",vendor,product,release,count,speed);
    for(unsigned i=0;i<count;i++) {
        IOUSBConfigurationDescriptorPtr cfg=NULL;
        r=(*dev)->GetConfigurationDescriptorPtr(dev,i,&cfg); result("GetConfigurationDescriptorPtr",r);
        if(r || !cfg) continue;
        const unsigned char *b=(void *)cfg; unsigned n=le16(b+2);
        FILE *f=fopen(output,"wb");
        if(!f) { perror(output); (*dev)->Release(dev); return 3; }
        if(fwrite(b,1,n,f)!=n) { perror("fwrite"); fclose(f); (*dev)->Release(dev); return 3; }
        fclose(f);
        printf("configuration=%u bytes=%u interfaces=%u power=%umA saved=%s\n",b[5],n,b[4],2*b[8],output);
        for(unsigned off=0;off+2<=n;) {
            unsigned len=b[off],type=b[off+1];
            if(len<2 || off+len>n) { fprintf(stderr,"malformed descriptor at %u\n",off); break; }
            const unsigned char *d=b+off;
            if(type==4 && len>=9)
                printf(" interface=%u alt=%u endpoints=%u class=%02x subclass=%02x protocol=%02x\n",d[2],d[3],d[4],d[5],d[6],d[7]);
            else if(type==5 && len>=7) {
                unsigned w=le16(d+4);
                printf("  endpoint=%02x type=%u wMaxPacketSize=%04x capacity=%u interval=%u\n",d[2],d[3]&3,w,(w&0x7ff)*(1+((w>>11)&3)),d[6]);
            } else {
                printf(" descriptor type=%02x length=%u data=",type,len);
                for(unsigned k=0;k<len;k++) printf("%02x",d[k]);
                putchar('\n');
            }
            off+=len;
        }
    }
    int failed=0;
    r=(*dev)->USBDeviceOpen(dev); result("USBDeviceOpen",r);
    if(!r) {
        unsigned char descriptor[18]={0};
        IOUSBDevRequestTO req={.bmRequestType=0x80,.bRequest=6,.wValue=0x100,.wIndex=0,.wLength=18,.pData=descriptor,.noDataTimeout=1000,.completionTimeout=2000};
        r=(*dev)->DeviceRequestTO(dev,&req); result("GET_DESCRIPTOR device",r);
        if(!r) { printf("device_descriptor="); for(unsigned k=0;k<req.wLenDone;k++) printf("%02x",descriptor[k]); putchar('\n'); }
        failed = r || req.wLenDone!=18;
        if(recover && !failed) failed=recover_preview(dev);
        if(av_init && !failed) {
            c039_transport transport={.context=dev,.control=av_control,
                .sleep_ms=av_sleep,.cancelled=av_cancelled,.on_ready=iso_path?av_iso_ready:NULL,
                .video_standard=video_standard,.line_audio=iso_path && iso_endpoint!=4,
                .audio_attenuation_db=attenuation};
            uint16_t id=0;
            failed=c039_av_probe(&transport,&id,av_init==1 || calibrate);
        }
        unsigned char saved_power[4]={0}; int restore_power=0;
        UInt8 saved_alt=0; IOUSBInterfaceInterface182 **video=NULL;
        if(wake && !device_only && !failed) {
            // C039-specific EP0 workaround in Linux cx231xx_init_dev().
            video=open_video(dev,&saved_alt);
            if(!video) failed=1;
        }
        if(wake && !failed) {
            failed |= power_transfer(dev,0,saved_power);
            if(!failed) {
                restore_power=1;
                unsigned power=(unsigned)saved_power[0] | (unsigned)saved_power[1]<<8 |
                               (unsigned)saved_power[2]<<16 | (unsigned)saved_power[3]<<24;
                // Linux cx231xx_set_power_mode(EXTERNAL_AV): enable AV, ISO, external input.
                power &= ~0x17fu;
                const unsigned flags[]={0x08,0x40,0x30};
                for(unsigned k=0;k<3;k++) {
                    if(interrupted) { failed=1; break; }
                    power|=flags[k];
                    unsigned char data[4]={power,power>>8,power>>16,power>>24};
                    if(power_transfer(dev,1,data)) { failed=1; break; }
                    struct timespec delay={.tv_nsec=10000000}; nanosleep(&delay,NULL);
                }
            }
        }
        if(registers && !failed && !interrupted) {
            // Fixed read-only allowlist from Linux v6.12 cx231xx-{core,conf-reg}.
            failed |= read_register(dev,"BOARD_CFG_STAT",0x0d,0x000f,0x0000,4);
            failed |= read_register(dev,"EP_MODE_SET",0x0d,0x000f,0x0018,4);
            failed |= read_register(dev,"GBULK_BIT_EN",0x0d,0x000f,0x0068,4);
            failed |= read_register(dev,"PWR_CTL_EN",0x0d,0x000f,0x0074,4);
            if(afe) {
                // Linux AFE address8=0x60, I2S address8=0x98, master0.
                failed |= read_register(dev,"AFE_SUP_BLK_PWRDN",4,0x6029,8,1);
                failed |= read_register(dev,"I2S_CH_PWR_CTRL1",4,0x9825,0x0e,1);
                failed |= read_register(dev,"I2S_CH_PWR_CTRL2",4,0x9825,0x0f,1);
            }
            // I2C master0, address 0x44, 100 kHz, 2-byte subaddress, sync.
            failed |= read_register(dev,"DECODER_ID",0x04,0x8829,0x0100,2);
            failed |= read_register(dev,"GEN_STAT",0x04,0x8829,0x040c,4);
            failed |= read_register(dev,"CHIP_VERSION",0x04,0x8829,0x04b4,4);
        }
        if(restore_power) failed |= power_transfer(dev,1,saved_power);
        if(video) {
            IOReturn restored=(*video)->SetAlternateInterface(video,saved_alt);
            result("restore video alternate setting",restored); failed |= restored!=0;
            IOReturn closed=(*video)->USBInterfaceClose(video);
            result("USBInterfaceClose",closed); failed |= closed!=0;
            (*video)->Release(video);
        }
        IOReturn closed=(*dev)->USBDeviceClose(dev); result("USBDeviceClose",closed);
        failed |= closed!=0;
    }
    (*dev)->Release(dev);
    return r || failed || interrupted ? 4 : 0;
}
