# SPDX-License-Identifier: MIT
PYTHON ?= /usr/bin/python3

.PHONY: all check clean
all: build/pocketfed_fpc.pp build/pocketfed_fpc_broker.pp

build/pocketfed_fpc.mod: pocketfed_fpc.te
	mkdir -p build
	checkmodule -M -m -o $@ $<

build/pocketfed_fpc.pp: build/pocketfed_fpc.mod pocketfed_fpc.fc
	semodule_package -o $@ -m $< -f pocketfed_fpc.fc

build/pocketfed_fpc_broker.mod: broker/pocketfed_fpc_broker.te
	mkdir -p build
	checkmodule -M -m -o $@ $<

build/pocketfed_fpc_broker.pp: build/pocketfed_fpc_broker.mod broker/pocketfed_fpc_broker.fc
	semodule_package -o $@ -m $< -f broker/pocketfed_fpc_broker.fc

clean:
	rm -rf build

# All compiler output stays in a temporary directory. No policy store is used.
check:
	$(PYTHON) test-policy.py --policy "$(POLICY)" --contexts "$(CONTEXTS)" $(if $(REPORT),--report "$(REPORT)")
