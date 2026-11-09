CC = clang
CFLAGS = -std=c11 -O2 -Wall -Wextra -Wno-deprecated-declarations
FRAMEWORKS = -framework IOKit -framework CoreFoundation

all: build/c039-probe build/c039-host-probe

build:
	mkdir -p build

build/c039-probe: src/probe.c src/av_init.c src/av_init.h src/iso_probe.c src/iso_probe.h src/video_standard.c src/video_standard.h | build
	$(CC) $(CFLAGS) src/probe.c src/av_init.c src/iso_probe.c src/video_standard.c $(FRAMEWORKS) -o $@

build/test-av-init: tests/test_av_init.c src/av_init.c src/av_init.h src/video_standard.c src/video_standard.h | build
	$(CC) $(CFLAGS) -Isrc tests/test_av_init.c src/av_init.c src/video_standard.c -o $@

build/c039-host-probe: src/host_probe.m | build
	$(CC) $(CFLAGS) -fobjc-arc -fblocks $< $(FRAMEWORKS) -framework Foundation -framework IOUSBHost -o $@

build/libc039-frame.dylib: src/frame_decoder.c src/frame_decoder.h | build
	$(CC) $(CFLAGS) -dynamiclib src/frame_decoder.c -o $@

build/test-native-frame: tests/test_frame_decoder.c src/frame_decoder.c src/frame_decoder.h | build
	$(CC) $(CFLAGS) -Isrc tests/test_frame_decoder.c src/frame_decoder.c -o $@

build/test-preview-audio: tests/test_preview_audio.c src/preview_audio.c src/preview_audio.h | build
	$(CC) $(CFLAGS) -Isrc tests/test_preview_audio.c src/preview_audio.c -o $@

build/C039Preview.app/Contents/MacOS/C039Preview: preview/Preview.swift preview/Bridge.h src/capture_device.c src/av_init.c src/iso_probe.c src/video_standard.c src/frame_decoder.c src/preview_audio.c $(wildcard src/*.h) tools/build_preview.py | build
	python3 tools/build_preview.py

build/c039-camera-smoke: tests/camera_smoke.c src/capture_device.c src/frame_decoder.c src/av_init.c src/video_standard.c src/iso_probe.c | build
	$(CC) $(CFLAGS) -Isrc tests/camera_smoke.c src/capture_device.c src/frame_decoder.c src/av_init.c src/video_standard.c src/iso_probe.c $(FRAMEWORKS) -o $@

test: all build/test-av-init build/libc039-frame.dylib build/test-native-frame build/test-preview-audio
	./build/test-av-init > build/test-av-init.txt
	./build/test-native-frame
	./build/test-preview-audio
	python3 -m unittest discover -s tests -v

.PHONY: all test
