// SPDX-License-Identifier: GPL-2.0-or-later
/* Read-only preflight: descriptors/open/claim/release only. No AV writes,
 * alternate settings, detach, reset, configuration changes or installation. */
#include "usb_libusb.h"
#include <stdio.h>
#include <string.h>
#include "windows_capture_cli.h"

int main(int argc,char **argv) {
    if(argc>1 && !strcmp(argv[1],"--capture")) return c039_windows_capture_cli(argc,argv);
    if(argc==2 && !strcmp(argv[1],"--list-standards")) {
        putchar('[');
        for(size_t n=0;n<c039_standard_name_count;n++) {
            const c039_standard_alias *a=c039_standard_name_at(n);
            const c039_video_standard *p=c039_standard(a->id);
            printf("%s{\"name\":\"%s\",\"id\":%u,\"height\":%u,\"rate_num\":%u,\"rate_den\":%u}",
                   n?",":"",a->name,a->id,p?p->height:0,p?p->rate_num:0,p?p->rate_den:1);
        }
        puts("]"); return 0;
    }
    if(argc!=2 || strcmp(argv[1],"--check")) {
        fprintf(stderr,"Usage: c039-probe --check | --list-standards (no capture or register writes)\n");
        return 64;
    }
    libusb_context *context=NULL;
    int code=libusb_init(&context);
    if(code) { fprintf(stderr,"libusb_init: %s\n",libusb_error_name(code)); return 1; }
    libusb_device **devices=NULL;
    ssize_t count=libusb_get_device_list(context,&devices);
    int found=0,failed=count<0;
    for(ssize_t i=0;i<count;i++) {
        struct libusb_device_descriptor d;
        if(libusb_get_device_descriptor(devices[i],&d) || d.idVendor!=0x07ca || d.idProduct!=0xc039) continue;
        found++;
        printf("C039 bus=%u address=%u speed=%d configurations=%u\n",
               libusb_get_bus_number(devices[i]),libusb_get_device_address(devices[i]),libusb_get_device_speed(devices[i]),d.bNumConfigurations);
        struct libusb_config_descriptor *config=NULL;
        code=libusb_get_active_config_descriptor(devices[i],&config);
        if(code) { printf("descriptor: %s\n",libusb_error_name(code)); failed=1; continue; }
        for(unsigned n=0;n<config->bNumInterfaces;n++) {
            const struct libusb_interface *interface=&config->interface[n];
            for(int a=0;a<interface->num_altsetting;a++) {
                const struct libusb_interface_descriptor *alt=&interface->altsetting[a];
                printf("interface=%u alt=%u class=%02x endpoints=%u\n",alt->bInterfaceNumber,alt->bAlternateSetting,alt->bInterfaceClass,alt->bNumEndpoints);
                for(unsigned e=0;e<alt->bNumEndpoints;e++) {
                    const struct libusb_endpoint_descriptor *ep=&alt->endpoint[e];
                    unsigned packet=ep->wMaxPacketSize;
                    printf("  endpoint=%02x type=%u max_packet=%u interval=%u capacity=%u\n",
                           ep->bEndpointAddress,ep->bmAttributes&3,packet,ep->bInterval,
                           (packet&0x7ff)*(1+((packet>>11)&3)));
                }
            }
        }
        libusb_device_handle *handle=NULL;
        code=libusb_open(devices[i],&handle);
        printf("open: %s\n",libusb_error_name(code));
        if(code) failed=1;
        else {
            /* Descriptor interface numbers on Windows can differ from macOS.
             * Probe only default alt settings; do not assume macOS's 3/4. */
            for(unsigned n=0;n<config->bNumInterfaces;n++) {
                const struct libusb_interface *interface=&config->interface[n];
                if(!interface->num_altsetting) continue;
                int number=interface->altsetting[0].bInterfaceNumber;
                if(number==0) { puts("interface=0 preserved outside MI_01 capture function"); continue; }
                code=libusb_claim_interface(handle,number);
                printf("claim interface=%d: %s\n",number,libusb_error_name(code));
                if(code) failed=1;
                else if(libusb_release_interface(handle,number)) failed=1;
            }
            libusb_close(handle);
        }
        libusb_free_config_descriptor(config);
    }
    if(devices) libusb_free_device_list(devices,1);
    libusb_exit(context);
    if(!found) { fprintf(stderr,"C039 not visible to libusb\n"); return 2; }
    if(failed) fprintf(stderr,"Preflight incomplete: keep the existing driver; no capture attempted.\n");
    return failed?3:0;
}
