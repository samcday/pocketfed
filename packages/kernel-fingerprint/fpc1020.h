/* SPDX-License-Identifier: GPL-2.0 WITH Linux-syscall-note */
#ifndef _UAPI_LINUX_FPC1020_H
#define _UAPI_LINUX_FPC1020_H

#include <linux/ioctl.h>
#include <linux/types.h>

/* Interrupt notification only; this is never a biometric match result. */
struct fpc1020_irq_event {
	__u64 sequence;
	__u32 level;
	__u32 reserved;
};

#define FPC1020_IOC_RESET		_IO('F', 0)
#define FPC1020_IOC_SET_WAKEUP	_IOW('F', 1, __u32)
/* Snapshot the current GPIO level and counter without consuming an event. */
#define FPC1020_IOC_GET_IRQ	_IOR('F', 2, struct fpc1020_irq_event)

#endif /* _UAPI_LINUX_FPC1020_H */
