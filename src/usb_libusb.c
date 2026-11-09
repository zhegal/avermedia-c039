// SPDX-License-Identifier: GPL-2.0-or-later
#include "usb_libusb.h"
#include <stdio.h>
#ifdef _WIN32
#include <windows.h>
#else
#include <time.h>
#endif

int c039_libusb_control(void *context,int write,uint8_t request,uint16_t value,
                       uint16_t index,uint8_t *data,unsigned size) {
    c039_libusb *usb=context;
    if(!usb || !usb->handle || size>UINT16_MAX || (size && !data)) return C039_CONTROL_ERROR;
    int result=libusb_control_transfer(usb->handle,write?0x40:0xc0,request,value,index,
                                       data,(uint16_t)size,2000);
    if(result==(int)size) return 0;
    fprintf(stderr,"USB control %s request=%02x index=%04x: %s (%d/%u)\n",
            write?"OUT":"IN",request,index,result<0?libusb_error_name(result):"short transfer",result,size);
    /* libusb errors do not distinguish an applied power-transition write from
     * a rejected request. Fail closed; do not reuse IOKit's transaction code. */
    return C039_CONTROL_ERROR;
}
void c039_libusb_sleep(void *context,unsigned ms) {
    (void)context;
#ifdef _WIN32
    Sleep(ms);
#else
    struct timespec duration={ms/1000,(long)(ms%1000)*1000000};
    nanosleep(&duration,NULL);
#endif
}
