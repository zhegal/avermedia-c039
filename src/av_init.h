// SPDX-License-Identifier: GPL-2.0-or-later
#ifndef C039_AV_INIT_H
#define C039_AV_INIT_H
#include <stdint.h>

// Synchronous transfer callback: 0=complete, 1=error, 2=USB transaction error.
// Only a bridge power transition may reconcile code 2 by exact readback.
enum { C039_CONTROL_ERROR=1, C039_CONTROL_TRANSACTION_ERROR=2 };
typedef int (*c039_control)(void *, int write, uint8_t request, uint16_t value,
                            uint16_t index, uint8_t *data, unsigned size);
typedef struct {
    void *context;
    c039_control control;
    void (*sleep_ms)(void *, unsigned);
    int (*cancelled)(void *);
    int (*on_ready)(void *); // Optional bounded transport probe before rollback.
    unsigned video_standard; // 0=unchanged, 1=PAL, 2=SECAM, 3=NTSC-M.
    int line_audio;
    unsigned audio_attenuation_db; // 0..48, PATH1_VOLUME half-dB steps.
} c039_transport;

// Temporary external AV/AFE/I2S initialization, ID read, then rollback.
// No firmware registers, EEPROM, GPIO or USB reset. on_ready may capture.
// 0: recognized chip and cleanup succeeded; 1: probe failed; 2: cleanup failed.
int c039_av_probe(c039_transport *transport, uint16_t *decoder_id, int calibrate);
#endif
