/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Synthetic Linux syscall boundary; never opens a device or calls real ioctl.
 * Build with sensor.c and linker --wrap for open, close, ioctl, poll, read,
 * clock_gettime. No elapsed-time sleeps or fingerprint hardware are used.
 */
#define _GNU_SOURCE
#include "sensor.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <time.h>
#include <unistd.h>

#define SENSOR_FD 50
#define CANCEL_FD 51

static struct snapshot_step {
    struct fpc1020_irq_event event;
    int error;
} snapshots[8];
static struct poll_step {
    int result, error, timeout, advance_ms;
    short sensor_events, cancel_events;
} polls[8];
static struct read_step {
    struct fpc1020_irq_event event;
    ssize_t count;
    int error;
} reads[8];
static unsigned n_snapshots, n_polls, n_reads, snapshot_pos, poll_pos, read_pos;
static unsigned cancel_checks, closes, resets, wake_calls;
static int64_t elapsed_ms;
static bool pre_cancel;

static void reset(void)
{
    memset(snapshots, 0, sizeof(snapshots));
    memset(polls, 0, sizeof(polls));
    memset(reads, 0, sizeof(reads));
    n_snapshots = n_polls = n_reads = snapshot_pos = poll_pos = read_pos = 0;
    cancel_checks = closes = resets = wake_calls = 0;
    elapsed_ms = 0;
    pre_cancel = false;
}

static void snapshot(unsigned level)
{
    assert(n_snapshots < 8);
    snapshots[n_snapshots].event.sequence = 100 + n_snapshots;
    snapshots[n_snapshots++].event.level = level;
}

static void event_poll(short sensor_events, short cancel_events, int timeout, int elapsed)
{
    assert(n_polls < 8);
    polls[n_polls++] = (struct poll_step) {
        .result = !!sensor_events + !!cancel_events,
        .timeout = timeout, .advance_ms = elapsed,
        .sensor_events = sensor_events, .cancel_events = cancel_events,
    };
}

static void event_read(unsigned level)
{
    assert(n_reads < 8);
    reads[n_reads] = (struct read_step) {
        .event = {.sequence = 900 + n_reads, .level = level},
        .count = sizeof(struct fpc1020_irq_event),
    };
    n_reads++;
}

int __wrap_open(const char *path, int flags, ...)
{
    assert(!strcmp(path, "/synthetic/fpc"));
    assert(flags == (O_RDWR | O_NONBLOCK | O_CLOEXEC));
    return SENSOR_FD;
}

int __wrap_close(int fd)
{
    assert(fd == SENSOR_FD);
    closes++;
    return 0;
}

int __wrap_ioctl(int fd, unsigned long operation, ...)
{
    assert(fd == SENSOR_FD);
    if (operation == FPC1020_IOC_RESET) {
        resets++;
        return 0;
    }
    va_list args;
    va_start(args, operation);
    void *output = va_arg(args, void *);
    va_end(args);
    if (operation == FPC1020_IOC_SET_WAKEUP) {
        assert(*(const __u32 *)output <= 1);
        wake_calls++;
        return 0;
    }
    assert(operation == FPC1020_IOC_GET_IRQ && snapshot_pos < n_snapshots);
    struct snapshot_step *step = &snapshots[snapshot_pos++];
    if (step->error) { errno = step->error; return -1; }
    memcpy(output, &step->event, sizeof(step->event));
    return 0;
}

int __wrap_clock_gettime(clockid_t clock, struct timespec *time)
{
    assert(clock == CLOCK_MONOTONIC);
    time->tv_sec = elapsed_ms / 1000;
    time->tv_nsec = elapsed_ms % 1000 * 1000000;
    return 0;
}

int __wrap_poll(struct pollfd *descriptors, nfds_t count, int timeout)
{
    if (count == 1) {
        assert(descriptors[0].fd == CANCEL_FD && !timeout);
        cancel_checks++;
        descriptors[0].revents = pre_cancel ? POLLIN : 0;
        return pre_cancel;
    }
    assert(count == 2 && poll_pos < n_polls);
    assert(descriptors[0].fd == SENSOR_FD && descriptors[0].events == POLLIN);
    assert(descriptors[1].fd == -1 || descriptors[1].fd == CANCEL_FD);
    struct poll_step *step = &polls[poll_pos++];
    assert(timeout == step->timeout);
    elapsed_ms += step->advance_ms;
    descriptors[0].revents = step->sensor_events;
    descriptors[1].revents = step->cancel_events;
    if (step->error) { errno = step->error; return -1; }
    return step->result;
}

ssize_t __wrap_read(int fd, void *buffer, size_t count)
{
    assert(fd == SENSOR_FD && count == sizeof(struct fpc1020_irq_event));
    assert(read_pos < n_reads);
    struct read_step *step = &reads[read_pos++];
    if (step->error) { errno = step->error; return -1; }
    assert(step->count >= 0 && (size_t)step->count <= count);
    memcpy(buffer, &step->event, (size_t)step->count);
    return step->count;
}

static void expect_wait(int timeout, int cancel, int expected)
{
    struct fpc_sensor_device sensor = {.fd = SENSOR_FD};
    assert(fpc_sensor_wait_high(&sensor, timeout, cancel) == expected);
    assert(snapshot_pos == n_snapshots && poll_pos == n_polls && read_pos == n_reads);
}

int main(void)
{
    struct fpc_sensor_device sensor = {.fd = -1};
    reset();
    assert(!fpc_sensor_open(&sensor, "/synthetic/fpc"));
    assert(!fpc_sensor_reset(&sensor) && resets == 1);
    assert(!fpc_sensor_wakeup(&sensor, true));
    fpc_sensor_close(&sensor);
    fpc_sensor_close(&sensor);
    assert(closes == 1 && wake_calls == 2 && sensor.fd == -1);

    /* The API promises current-high, including timeout zero: no new edge is
     * implied, and no IRQ event or biometric identity is fabricated. */
    reset(); snapshot(1); expect_wait(0, -1, 1);
    assert(!poll_pos && !read_pos);

    /* An old high event is not current high. A falling level after the event
     * must lead to waiting/timeout, rather than advancing capture. */
    reset(); snapshot(0); snapshot(0);
    event_poll(POLLIN, 0, 100, 20); event_read(1);
    event_poll(0, 0, 80, 80);
    expect_wait(100, -1, 0);

    /* Conversely, a low historical read cannot suppress a later high GPIO. */
    reset(); snapshot(0); snapshot(1);
    event_poll(POLLIN, 0, 100, 20); event_read(0);
    expect_wait(100, -1, 1);

    reset(); pre_cancel = true;
    expect_wait(100, CANCEL_FD, -ECANCELED);
    assert(cancel_checks == 1 && !snapshot_pos);
    reset(); snapshot(0);
    event_poll(POLLIN, POLLIN, 100, 20);
    expect_wait(100, CANCEL_FD, -ECANCELED);
    assert(!read_pos);

    const short disconnects[] = {POLLHUP, POLLERR, POLLNVAL};
    for (size_t i = 0; i < sizeof(disconnects) / sizeof(disconnects[0]); i++) {
        reset(); snapshot(0); event_poll(disconnects[i], 0, 100, 20);
        expect_wait(100, -1, -ENODEV);
    }
    reset(); snapshot(0); event_poll(POLLIN, 0, 100, 20); event_read(0);
    reads[0].error = ENODEV;
    expect_wait(100, -1, -ENODEV);

    for (int malformed = 0; malformed < 4; malformed++) {
        reset(); snapshot(0); event_poll(POLLIN, 0, 100, 20); event_read(1);
        if (malformed == 0) reads[0].count = 8;
        if (malformed == 1) reads[0].count = 0;
        if (malformed == 2) reads[0].event.reserved = 1;
        if (malformed == 3) reads[0].event.level = 2;
        expect_wait(100, -1, -EPROTO);
    }
    reset(); snapshot(2); expect_wait(100, -1, -EPROTO);
    reset(); snapshot(1); snapshots[0].event.reserved = 1;
    expect_wait(100, -1, -EPROTO);
    reset(); snapshot(0); snapshots[0].error = EIO;
    expect_wait(100, -1, -EIO);

    const int retry_errors[] = {EINTR, EAGAIN};
    for (size_t i = 0; i < sizeof(retry_errors) / sizeof(retry_errors[0]); i++) {
        reset(); snapshot(0); snapshot(0);
        event_poll(POLLIN, 0, 100, 20); event_read(1);
        reads[0].error = retry_errors[i];
        event_poll(0, 0, 80, 80);
        expect_wait(100, -1, 0);
    }
    reset(); snapshot(0); snapshot(0);
    event_poll(0, 0, 100, 30); polls[0].error = EINTR;
    event_poll(0, 0, 70, 70);
    expect_wait(100, -1, 0);
    reset(); snapshot(0); event_poll(0, 0, 100, 100);
    expect_wait(100, -1, 0);
    reset(); snapshot(0); expect_wait(0, -1, 0);
    puts("sensor boundary: stale IRQ, current level, cancellation, disconnect, malformed event and deadline tests passed");
    return 0;
}
