// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef C039_CAPTURE_WINDOWS_H
#define C039_CAPTURE_WINDOWS_H
#include <windows.h>
#include <winusb.h>
#include "capture_device.h"
/* Optional transfer-sized delivery avoids per-microframe Python callbacks.
 * Descriptors are validated first. Pointers live only during this callback.
 * first_us is the scheduled time of packet 0; packet n is first_us+n*125. */
typedef int (*c039_windows_batch_callback)(void *,int,const uint8_t *,size_t,
    const USBD_ISO_PACKET_DESCRIPTOR *,unsigned,uint64_t);
void c039_windows_session_set_batch_callback(c039_session *,c039_windows_batch_callback);
/* Configure the DLL's own C stderr before capture, including windowed bundles.
 * Does not enumerate/open USB or alter driver/device state. */
int c039_windows_set_log_path(const wchar_t *);
#endif
