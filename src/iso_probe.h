// SPDX-License-Identifier: MIT
#ifndef C039_ISO_PROBE_H
#define C039_ISO_PROBE_H
#include <IOKit/usb/IOUSBLib.h>
int c039_iso_probe(IOUSBDeviceInterface182 **dev,const char *path,
                   int endpoint,unsigned seconds,int fifo_telemetry,int (*cancelled)(void *),void *context);
#endif
