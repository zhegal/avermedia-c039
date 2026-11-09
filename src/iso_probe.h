// SPDX-License-Identifier: MIT
#ifndef C039_ISO_PROBE_H
#define C039_ISO_PROBE_H
#include <IOKit/usb/IOUSBLib.h>
// Called on the transport run loop; must not block. USB time is in microseconds.
typedef int (*c039_payload_callback)(void *,int,const uint8_t *,size_t,uint64_t);
int c039_iso_capture(IOUSBDeviceInterface182 **dev,int endpoint,unsigned seconds,
                    c039_payload_callback payload,void *payload_context,
                    int (*cancelled)(void *),void *context,
                    int (*monitor)(void *),void *monitor_context);
int c039_iso_probe(IOUSBDeviceInterface182 **dev,const char *path,
                   int endpoint,unsigned seconds,int fifo_telemetry,int (*cancelled)(void *),void *context,
                   int (*monitor)(void *),void *monitor_context);
#endif
