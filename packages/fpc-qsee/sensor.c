/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _GNU_SOURCE
#include "sensor.h"
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdint.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

_Static_assert(sizeof(struct fpc1020_irq_event) == 16, "FPC event ABI");

int fpc_sensor_open(struct fpc_sensor_device *sensor, const char *path)
{
    if (!sensor || !path) return -EINVAL;
    sensor->fd = open(path, O_RDWR | O_NONBLOCK | O_CLOEXEC);
    return sensor->fd < 0 ? -errno : 0;
}
int fpc_sensor_wakeup(struct fpc_sensor_device *sensor, bool enable)
{
    __u32 value = enable;
    if (!sensor || sensor->fd < 0) return -EINVAL;
    return ioctl(sensor->fd, FPC1020_IOC_SET_WAKEUP, &value) ? -errno : 0;
}
void fpc_sensor_close(struct fpc_sensor_device *sensor)
{
    if (!sensor) return;
    if (sensor->fd >= 0) {
        fpc_sensor_wakeup(sensor, false);
        close(sensor->fd);
    }
    sensor->fd = -1;
}
int fpc_sensor_reset(struct fpc_sensor_device *sensor)
{
    if (!sensor || sensor->fd < 0) return -EINVAL;
    return ioctl(sensor->fd, FPC1020_IOC_RESET) ? -errno : 0;
}
int fpc_sensor_snapshot(struct fpc_sensor_device *sensor, struct fpc1020_irq_event *event)
{
    if (!sensor || sensor->fd < 0 || !event) return -EINVAL;
    memset(event, 0, sizeof(*event));
    if (ioctl(sensor->fd, FPC1020_IOC_GET_IRQ, event)) return -errno;
    return event->level > 1 || event->reserved ? -EPROTO : 0;
}
static int64_t monotonic_ms(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) return -1;
    return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}
int fpc_sensor_wait_high(struct fpc_sensor_device *sensor, int timeout_ms, int cancel_fd)
{
    struct pollfd descriptors[2] = {
        {.fd = sensor ? sensor->fd : -1, .events = POLLIN},
        {.fd = cancel_fd, .events = POLLIN},
    };
    struct fpc1020_irq_event event;
    int64_t start = monotonic_ms();
    if (!sensor || sensor->fd < 0 || timeout_ms < 0 || start < 0) return -EINVAL;
    for (;;) {
        int result;
        if (cancel_fd >= 0 && poll(&descriptors[1], 1, 0) > 0) return -ECANCELED;
        result = fpc_sensor_snapshot(sensor, &event);
        if (result) return result;
        if (event.level) return 1;
        int64_t now = monotonic_ms();
        if (now < 0) return -errno;
        int64_t remaining = timeout_ms - (now - start);
        if (remaining <= 0) return 0;
        result = poll(descriptors, 2, (int)remaining);
        if (result < 0) {
            if (errno == EINTR) continue;
            return -errno;
        }
        if (descriptors[1].revents) return -ECANCELED;
        if (descriptors[0].revents & (POLLERR | POLLHUP | POLLNVAL)) return -ENODEV;
        if (!result) return 0;
        /* Consume the edge notification; the snapshot above determines the
         * current level after any TA-driven transactions or falling edge. */
        ssize_t count = read(sensor->fd, &event, sizeof(event));
        if (count < 0 && (errno == EAGAIN || errno == EINTR)) continue;
        if (count < 0) return -errno;
        if (count != sizeof(event) || event.reserved || event.level > 1) return -EPROTO;
    }
}
