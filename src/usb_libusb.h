// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef C039_USB_LIBUSB_H
#define C039_USB_LIBUSB_H
#include "av_init.h"
#include <libusb.h>

/* Control transport only. No detach, configuration change or driver install.
 * Caller must claim all required streaming interfaces before AV initialization.
 * USB completion wall time must never be substituted for bus packet timestamps. */
typedef struct {
    libusb_device_handle *handle;
} c039_libusb;
int c039_libusb_control(void *, int, uint8_t, uint16_t, uint16_t, uint8_t *, unsigned);
void c039_libusb_sleep(void *, unsigned);
#endif
