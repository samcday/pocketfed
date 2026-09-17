# SPDX-License-Identifier: GPL-2.0-only
# Wrapper for an out-of-tree build against a kernel-devel tree.
#   make KDIR=/usr/src/kernels/<release>

KDIR ?= /lib/modules/$(shell uname -r)/build
PWD := $(shell pwd)

all: modules

modules:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

.PHONY: all modules clean
