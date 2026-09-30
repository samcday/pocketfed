CC ?= cc
CFLAGS ?= -O2 -g
CFLAGS += -std=gnu11 -Wall -Wextra -Werror
WRAP = -Wl,--wrap=glob,--wrap=globfree,--wrap=open,--wrap=close,--wrap=mmap,--wrap=munmap,--wrap=ioctl

.PHONY: all check clean
all: fpc-qsee-probe

fpc-qsee-probe: probe.c protocol.c qsee-transport.c sensor.c protocol.h qsee-transport.h sensor.h fpc1020.h
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ probe.c protocol.c qsee-transport.c sensor.c $(LDLIBS)
test-protocol: protocol.c test-protocol.c protocol.h
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ protocol.c test-protocol.c $(LDLIBS)
test-transport: qsee-transport.c test-transport.c qsee-transport.h
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ qsee-transport.c test-transport.c $(WRAP) $(LDLIBS)
test-gatekeeper: gatekeeper-protocol.c test-gatekeeper.c gatekeeper-protocol.h
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ gatekeeper-protocol.c test-gatekeeper.c $(LDLIBS)
test-sensor: sensor.c test-sensor.c sensor.h fpc1020.h
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ sensor.c test-sensor.c -Wl,--wrap=open,--wrap=close,--wrap=ioctl,--wrap=poll,--wrap=read,--wrap=clock_gettime $(LDLIBS)
check: test-protocol test-transport test-gatekeeper test-sensor
	./test-protocol
	./test-transport
	./test-gatekeeper
	./test-sensor
clean:
	rm -f fpc-qsee-probe test-protocol test-transport test-gatekeeper test-sensor
