CC ?= cc
CFLAGS ?= -O2 -g
CFLAGS += -std=gnu11 -Wall -Wextra -Werror
QSEE ?= ..
CPPFLAGS += -D_GNU_SOURCE -I$(QSEE)/include -I.
OUT ?= build
COMMON = $(addprefix $(QSEE)/src/,path.c services.c handle_db.c fs.c gpfs.c transport_qseecom.c notify.c)

.PHONY: all check
all: $(OUT)/qsee-sargo-rpmb

$(OUT):
	mkdir -p $@

$(OUT)/qsee-sargo-rpmb: main.c rpmb-protocol.c rpmb-mmc.c $(COMMON) write-policy.h sargo-device.h rpmb-protocol.h rpmb-mmc.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) main.c rpmb-protocol.c rpmb-mmc.c $(COMMON) -pthread $(LDLIBS) -o $@

$(OUT)/test-rpmb-protocol: test-rpmb-protocol.c rpmb-protocol.c rpmb-protocol.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) $< $(LDLIBS) -o $@

$(OUT)/test-rpmb-mmc: test-rpmb-mmc.c rpmb-mmc.c rpmb-mmc.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) $< $(LDLIBS) -o $@

$(OUT)/test-sargo-device: test-sargo-device.c sargo-device.h | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) $< $(LDLIBS) -o $@

$(OUT)/test-receiver: test-receiver.c main.c rpmb-protocol.c write-policy.h sargo-device.h $(COMMON) | $(OUT)
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) $< rpmb-protocol.c $(COMMON) -pthread $(LDLIBS) -o $@

check: $(OUT)/test-rpmb-protocol $(OUT)/test-rpmb-mmc $(OUT)/test-sargo-device $(OUT)/test-receiver
	$(OUT)/test-rpmb-protocol
	$(OUT)/test-rpmb-mmc
	$(OUT)/test-sargo-device
	$(OUT)/test-receiver
