// SPDX-License-Identifier: GPL-2.0-or-later
#include "usb_libusb.h"
#include <assert.h>
#include <stdio.h>

static int result,calls;
static uint8_t expected_type;
int LIBUSB_CALL libusb_control_transfer(libusb_device_handle *handle,uint8_t type,
        uint8_t request,uint16_t value,uint16_t index,unsigned char *data,
        uint16_t length,unsigned int timeout) {
    assert(handle==(libusb_device_handle *)1);
    assert(type==expected_type);
    assert(request==0x0c && value==0x0f && index==0x18);
    assert(data && length==4 && timeout==2000);
    calls++; return result;
}
const char * LIBUSB_CALL libusb_error_name(int code) { (void)code; return "injected"; }
int main(void) {
    c039_libusb usb={(libusb_device_handle *)1}; uint8_t data[4]={0};
    for(int write=0;write<=1;write++) {
        expected_type=write?0x40:0xc0;
        result=4;
        assert(!c039_libusb_control(&usb,write,0x0c,0x0f,0x18,data,4));
        result=3;
        assert(c039_libusb_control(&usb,write,0x0c,0x0f,0x18,data,4)==C039_CONTROL_ERROR);
        for(int error=LIBUSB_ERROR_IO;error>=LIBUSB_ERROR_NOT_SUPPORTED;error--) {
            result=error;
            assert(c039_libusb_control(&usb,write,0x0c,0x0f,0x18,data,4)==C039_CONTROL_ERROR);
        }
    }
    int before=calls;
    assert(c039_libusb_control(NULL,0,0,0,0,data,4));
    assert(c039_libusb_control(&usb,0,0,0,0,data,65536));
    assert(c039_libusb_control(&usb,0,0,0,0,NULL,4));
    assert(calls==before);
    puts("PASS: control setup, exact length, short/error transfers, invalid arguments");
}
