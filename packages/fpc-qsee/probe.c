/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _GNU_SOURCE
#include "protocol.h"
#include "qsee-transport.h"
#include "sensor.h"
#include <errno.h>
#include <inttypes.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/signalfd.h>
#include <unistd.h>

static int report(const char *operation, struct fpc_result result)
{
    printf("%s transport=%d dispatcher=%" PRId32 " command=%" PRId32 "\n",
           operation, result.transport, result.outer, result.command);
    return fpc_result_ok(result) ? 0 : -1;
}
static void snapshot(struct fpc_sensor_device *sensor, const char *label)
{
    struct fpc1020_irq_event event;
    int result = fpc_sensor_snapshot(sensor, &event);
    if (result) printf("%s snapshot_error=%d\n", label, result);
    else printf("%s sequence=%" PRIu64 " level=%u\n", label,
                (uint64_t)event.sequence, event.level);
}
int main(int argc, char **argv)
{
    struct fpc_qsee_session session = FPC_QSEE_SESSION_INIT;
    struct fpc_protocol protocol = {.ctx = &session, .exchange = fpc_qsee_command};
    struct fpc_sensor_device sensor = {.fd = -1};
    bool initialized = false;
    int result = 1, seconds = 0, cancel_fd = -1;
    char *end;
    sigset_t mask;

    if (argc == 2 && !strcmp(argv[1], "--initialize")) {
        seconds = 0;
    } else if (argc == 3 && !strcmp(argv[1], "--touch-window")) {
        long value = strtol(argv[2], &end, 10);
        if (!*argv[2] || *end || value < 1 || value > 120) goto usage;
        seconds = (int)value;
    } else {
usage:
        fprintf(stderr, "usage: %s --initialize | --touch-window SECONDS(1..120)\n"
                        "Requires a COPR trial kernel and the loaded FPC TA.\n"
                        "Resets/initializes the sensor; never enrolls or authenticates.\n", argv[0]);
        return 2;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    sigemptyset(&mask);
    sigaddset(&mask, SIGINT);
    sigaddset(&mask, SIGTERM);
    if (sigprocmask(SIG_BLOCK, &mask, NULL)) goto out;
    cancel_fd = signalfd(-1, &mask, SFD_CLOEXEC | SFD_NONBLOCK);
    if (cancel_fd < 0) goto out;
    int error = fpc_sensor_open(&sensor, "/dev/fpc1020");
    if (error) { fprintf(stderr, "sensor open: %s\n", strerror(-error)); goto out; }
    error = fpc_qsee_open(&session, FPC_QSEE_APP_NAME);
    if (error) { fprintf(stderr, "TA attach: %s\n", strerror(-error)); goto out; }
    snapshot(&sensor, "before_reset");
    error = fpc_sensor_reset(&sensor);
    if (error) { fprintf(stderr, "sensor reset: %s\n", strerror(-error)); goto out; }
    if (report("initialize", fpc_sensor(&protocol, FPC_SENSOR_INIT, NULL))) goto out;
    initialized = true;
    snapshot(&sensor, "after_initialize");
    if (seconds) {
        error = fpc_sensor_wakeup(&sensor, true);
        if (error) { fprintf(stderr, "enable wake: %s\n", strerror(-error)); goto out; }
        if (report("finger_lost_setup", fpc_sensor(&protocol, FPC_SENSOR_FINGER_LOST_WAKEUP_SETUP, NULL))) goto out;
        puts("Remove your finger from the sensor.");
        error = fpc_sensor_wait_high(&sensor, seconds * 1000, cancel_fd);
        if (error != 1) { printf("finger_lost_wait=%d\n", error); goto out; }
        /* Stock HAL treats CHECK_FINGER_LOST as a query and ignores its
         * command result, but transport/dispatcher failure still stops us. */
        struct fpc_result lost = fpc_sensor(&protocol, FPC_SENSOR_CHECK_FINGER_LOST, NULL);
        report("check_finger_lost", lost);
        if (lost.transport || lost.outer) goto out;
        if (report("wakeup_setup", fpc_sensor(&protocol, FPC_SENSOR_WAKEUP_SETUP, NULL))) goto out;
        puts("Touch the sensor once. This observes capture readiness, not identity.");
        error = fpc_sensor_wait_high(&sensor, seconds * 1000, cancel_fd);
        if (error != 1) { printf("finger_wait=%d\n", error); goto out; }
        uint32_t detail = 0;
        if (report("qualify_capture", fpc_sensor(&protocol, FPC_SENSOR_QUALIFY_CAPTURE, &detail))) goto out;
        printf("capture_detail=%u\n", detail);
        snapshot(&sensor, "after_capture");
    }
    result = 0;
out:
    if (initialized && report("deep_sleep", fpc_sensor(&protocol, FPC_SENSOR_DEEP_SLEEP, NULL))) result = 1;
    fpc_qsee_close(&session);
    fpc_sensor_close(&sensor);
    if (cancel_fd >= 0) close(cancel_fd);
    return result;
}
