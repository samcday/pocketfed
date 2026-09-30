CC ?= cc
CFLAGS ?= -O2 -g
FPC_QSEE_DIR ?= ../fpc-qsee
WARNINGS = -std=gnu11 -Wall -Wextra -Werror
SOURCES = auth-broker.c auth-store.c auth-backend.c $(FPC_QSEE_DIR)/gatekeeper-protocol.c $(FPC_QSEE_DIR)/qsee-transport.c
HEADERS = auth-store.h auth-backend.h $(FPC_QSEE_DIR)/auth-broker.h $(FPC_QSEE_DIR)/gatekeeper-protocol.h $(FPC_QSEE_DIR)/qsee-transport.h
WRAP = -Wl,--wrap=fsync,--wrap=write,--wrap=unlinkat
TEE_WRAP = -Wl,--wrap=glob,--wrap=globfree,--wrap=open,--wrap=close,--wrap=mmap,--wrap=munmap,--wrap=ioctl

.PHONY: all check clean
all: build/pocketfed-fpc-auth build/pocketfed-keymaster-startup

build:
	mkdir -p $@

build/pocketfed-fpc-auth: $(SOURCES) $(HEADERS) | build
	$(CC) $(CPPFLAGS) -I$(FPC_QSEE_DIR) $(CFLAGS) $(WARNINGS) $(LDFLAGS) -o $@ $(SOURCES) $(LDLIBS)

KEYMASTER_SOURCES = auth-backend.c $(FPC_QSEE_DIR)/gatekeeper-protocol.c $(FPC_QSEE_DIR)/protocol.c
KEYMASTER_HEADERS = $(HEADERS) $(FPC_QSEE_DIR)/protocol.h

build/pocketfed-keymaster-startup: keymaster-startup.c $(KEYMASTER_SOURCES) $(KEYMASTER_HEADERS) $(FPC_QSEE_DIR)/qsee-transport.c | build
	$(CC) $(CPPFLAGS) -I$(FPC_QSEE_DIR) $(CFLAGS) $(WARNINGS) $(LDFLAGS) -o $@ keymaster-startup.c $(KEYMASTER_SOURCES) $(FPC_QSEE_DIR)/qsee-transport.c $(LDLIBS)

build/test-keymaster-startup: test-keymaster-startup.c keymaster-startup.c $(KEYMASTER_SOURCES) $(KEYMASTER_HEADERS) | build
	$(CC) $(CPPFLAGS) -I$(FPC_QSEE_DIR) $(CFLAGS) $(WARNINGS) $(LDFLAGS) -o $@ test-keymaster-startup.c $(KEYMASTER_SOURCES) $(LDLIBS)

build/test-auth-store: test-auth-store.c $(SOURCES) $(HEADERS) | build
	$(CC) $(CPPFLAGS) -DFPC_AUTH_TESTING -I$(FPC_QSEE_DIR) $(CFLAGS) $(WARNINGS) $(LDFLAGS) -o $@ test-auth-store.c auth-store.c auth-backend.c $(FPC_QSEE_DIR)/gatekeeper-protocol.c $(WRAP) $(LDLIBS)

build/test-auth-backend: test-auth-backend.c auth-backend.c $(HEADERS) $(FPC_QSEE_DIR)/gatekeeper-protocol.c $(FPC_QSEE_DIR)/qsee-transport.c | build
	$(CC) $(CPPFLAGS) -I$(FPC_QSEE_DIR) $(CFLAGS) $(WARNINGS) $(LDFLAGS) -o $@ test-auth-backend.c auth-backend.c $(FPC_QSEE_DIR)/gatekeeper-protocol.c $(FPC_QSEE_DIR)/qsee-transport.c $(TEE_WRAP) $(LDLIBS)

check: all build/test-auth-store build/test-auth-backend build/test-keymaster-startup
	./build/test-auth-store
	./build/test-auth-backend
	./build/test-keymaster-startup
	./build/pocketfed-fpc-auth --help
	./build/pocketfed-keymaster-startup --help

clean:
	rm -rf build
