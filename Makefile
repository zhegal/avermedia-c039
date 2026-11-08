CC = clang
CFLAGS = -std=c11 -O2 -Wall -Wextra -Wno-deprecated-declarations
FRAMEWORKS = -framework IOKit -framework CoreFoundation

all: build/c039-probe build/c039-host-probe

build:
	mkdir -p build

build/c039-probe: src/probe.c src/av_init.c src/av_init.h src/iso_probe.c src/iso_probe.h | build
	$(CC) $(CFLAGS) src/probe.c src/av_init.c src/iso_probe.c $(FRAMEWORKS) -o $@

build/test-av-init: tests/test_av_init.c src/av_init.c src/av_init.h | build
	$(CC) $(CFLAGS) -Isrc tests/test_av_init.c src/av_init.c -o $@

build/c039-host-probe: src/host_probe.m | build
	$(CC) $(CFLAGS) -fobjc-arc -fblocks $< $(FRAMEWORKS) -framework Foundation -framework IOUSBHost -o $@

test: all build/test-av-init
	./build/test-av-init > build/test-av-init.txt
	python3 -m unittest discover -s tests -v

.PHONY: all test
