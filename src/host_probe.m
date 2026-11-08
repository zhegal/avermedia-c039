// SPDX-License-Identifier: MIT
// Native IOUSBHost diagnostic, analogous to the legacy Mac driver's interface IO.
// --wake writes only PWR_CTL_EN using the documented external A/V power sequence.
// No reset, firmware upload, EEPROM write or arbitrary register write interface.
#import <Foundation/Foundation.h>
#import <IOUSBHost/IOUSBHost.h>
#include <IOKit/IOKitLib.h>
#include <signal.h>
#include <time.h>

static volatile sig_atomic_t stopped=0;
static void stop(int sig) { (void)sig; stopped=1; }

static NSMutableData *request(IOUSBHostInterface *host, BOOL write, uint8_t req,
                             uint16_t value, uint16_t index, NSData *payload, NSUInteger size) {
    IOUSBDeviceRequest setup={.bmRequestType=write?0x40:0xc0,.bRequest=req,
        .wValue=value,.wIndex=index,.wLength=(uint16_t)size};
    NSMutableData *data=write?[payload mutableCopy]:[NSMutableData dataWithLength:size];
    NSUInteger actual=0; NSError *error=nil;
    BOOL ok=[host sendDeviceRequest:setup data:data bytesTransferred:&actual completionTimeout:5 error:&error];
    printf("%s req=%02x value=%04x index=%04x expected=%lu actual=%lu status=%08x data=",
           write?"OUT":"IN",req,value,index,(unsigned long)size,(unsigned long)actual,
           ok?0:(unsigned)error.code);
    if(ok) { const uint8_t *b=data.bytes; for(NSUInteger i=0;i<actual;i++) printf("%02x",b[i]); }
    putchar('\n');
    if(!ok) fprintf(stderr,"IOUSBHost: %s\n",error.description.UTF8String);
    return ok && actual==size ? data : nil;
}

int main(int argc,const char **argv) { @autoreleasepool {
    BOOL wake=argc==2 && !strcmp(argv[1],"--wake");
    BOOL find=argc==2 && !strcmp(argv[1],"--find");
    if(argc>1 && !wake && !find) { fprintf(stderr,"usage: %s [--wake|--find]\n",argv[0]); return 64; }
    setvbuf(stdout,NULL,_IOLBF,0); signal(SIGINT,stop); signal(SIGTERM,stop);
    CFMutableDictionaryRef match=IOServiceMatching("IOUSBHostInterface");
    CFMutableDictionaryRef props=CFDictionaryCreateMutable(NULL,0,&kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
    int values[]={0x07ca,0xc039,4};
    CFStringRef keys[]={CFSTR("idVendor"),CFSTR("idProduct"),CFSTR("bInterfaceNumber")};
    for(int i=0;i<3;i++) { CFNumberRef n=CFNumberCreate(NULL,kCFNumberIntType,&values[i]);
        CFDictionarySetValue(props,keys[i],n); CFRelease(n); }
    CFDictionarySetValue(match,CFSTR(kIOPropertyMatchKey),props); CFRelease(props);
    io_service_t service=IOServiceGetMatchingService(kIOMainPortDefault,match);
    if(!service) { fprintf(stderr,"07ca:c039 interface 4 not found\n"); return 1; }
    if(find) { puts("07ca:c039 interface 4 found in IORegistry"); IOObjectRelease(service); return 0; }
    NSError *error=nil;
    IOUSBHostInterface *host=[[IOUSBHostInterface alloc] initWithIOService:service
        options:IOUSBHostObjectInitOptionsNone queue:nil error:&error interestHandler:nil];
    IOObjectRelease(service);
    if(!host) { fprintf(stderr,"IOUSBHost init: %s\n",error.description.UTF8String); return 2; }
    printf("IOUSBHost interface 4 opened, alternate=%u\n",host.interfaceDescriptor->bAlternateSetting);
    NSData *saved=nil; BOOL restore=NO; int failed=0;
    if(wake) {
        saved=request(host,NO,0x0d,0xf,0x74,nil,4);
        if(!saved) failed=1;
        else {
            const uint8_t *b=saved.bytes;
            uint32_t power=(b[0]|(uint32_t)b[1]<<8|(uint32_t)b[2]<<16|(uint32_t)b[3]<<24)&~0x17fu;
            uint32_t flags[]={0x08,0x40,0x30};
            restore=YES;
            for(int i=0;i<3;i++) {
                if(stopped) { failed=1; break; }
                power|=flags[i]; uint8_t bytes[]={power,power>>8,power>>16,power>>24};
                if(!request(host,YES,0x0c,0xf,0x74,[NSData dataWithBytes:bytes length:4],4)) { failed=1; break; }
                struct timespec delay={.tv_nsec=10000000}; nanosleep(&delay,NULL);
            }
        }
    }
    if(!failed && !stopped) {
        if(!request(host,NO,0x0d,0xf,0,nil,4)) failed=1;
        if(!request(host,NO,0x0d,0xf,0x74,nil,4)) failed=1;
        // Same register reads as cx25840_probe; no blind I2C address scanning.
        for(int period=1;period<=2;period++) {
            uint16_t value=0x8800|(period<<4)|0x8|1;
            NSData *lo=request(host,NO,4,value,0x100,nil,1);
            NSData *hi=request(host,NO,4,value,0x101,nil,1);
            if(lo && hi) {
                unsigned id=((const uint8_t *)lo.bytes)[0] | ((const uint8_t *)hi.bytes)[0]<<8;
                printf("decoder_id=%04x decimal=%u confirmed_cx231xx=%s\n",id,id,
                    (id&0xfff0)==0x5a30?"yes":"no");
            } else failed=1;
        }
    }
    if(restore) {
        BOOL restored=request(host,YES,0x0c,0xf,0x74,saved,4)!=nil;
        printf("power_restored=%s\n",restored?"yes":"NO");
        if(!restored) failed=1;
    }
    [host destroy]; puts("IOUSBHost interface destroyed");
    return failed || stopped ? 4 : 0;
} }
