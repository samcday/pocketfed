CC ?= cc
CFLAGS ?= -O2 -g
WARN = -std=c11 -Wall -Wextra -Werror
GIO_FLAGS = $(shell pkg-config --cflags --libs gio-2.0)
BUILD = build

.PHONY: all check clean
all: $(BUILD)/phosh-fingerprint-auth $(BUILD)/phosh-fingerprint-worker
$(BUILD):
	mkdir -p $@
$(BUILD)/phosh-fingerprint-auth: phosh-fingerprint-auth.c fingerprint-wire.h | $(BUILD)
	$(CC) $(CFLAGS) $(WARN) $< -o $@
$(BUILD)/phosh-fingerprint-worker: phosh-fingerprint-worker.c fingerprint-wire.h | $(BUILD)
	$(CC) $(CFLAGS) $(WARN) $< -o $@ -lpam
$(BUILD)/test-helper: test-helper.c phosh-fingerprint-worker.c fingerprint-wire.h | $(BUILD)
	$(CC) $(CFLAGS) $(WARN) $< -o $@
$(BUILD)/fake-helper: fake-helper.c | $(BUILD)
	$(CC) $(CFLAGS) $(WARN) $< -o $@
$(BUILD)/test-client: test-client.c fingerprint-auth.c fingerprint-auth.h $(BUILD)/fake-helper | $(BUILD)
	$(CC) $(CFLAGS) $(WARN) -DFINGERPRINT_HELPER_PATH='"$(abspath $(BUILD)/fake-helper)"' test-client.c fingerprint-auth.c -o $@ $(GIO_FLAGS)
check: all $(BUILD)/test-helper $(BUILD)/test-client
	./$(BUILD)/test-helper
	./$(BUILD)/test-client
clean:
	rm -f $(BUILD)/phosh-fingerprint-auth $(BUILD)/phosh-fingerprint-worker $(BUILD)/test-helper $(BUILD)/test-client $(BUILD)/fake-helper
