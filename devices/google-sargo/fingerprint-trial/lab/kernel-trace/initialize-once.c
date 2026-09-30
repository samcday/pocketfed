/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Same sensor/protocol/transport sources as the daily diagnostic libfprint.
 * Only reset, initialize and deep sleep; no DB, authentication or capture API.
 */
#define _GNU_SOURCE
#include "protocol.h"
#include "qsee-transport.h"
#include "sensor.h"
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "--initialize-once") || geteuid()) return 2;
    FILE *file = fopen("/proc/cmdline", "re");
    char *line = NULL;
    size_t size = 0;
    if (!file || getline(&line, &size, file) < 0) return 2;
    fclose(file);
    int serial = 0, run = 0, usb = 0;
    for (char *word = strtok(line, " \n"); word; word = strtok(NULL, " \n")) {
        serial += !strcmp(word, "androidboot.serialno=99NAY1AZG1");
        run += !strcmp(word, "pocketfed.liveboot=sargo-fingerprint-lab-kernel-trace-20260913");
        usb += !strcmp(word, "pocketfed.root_mode=usb");
    }
    free(line);
    if (serial != 1 || run != 1 || usb != 1) return 2;
    int receipt = open("/run/pocketfed-fingerprint-lab/kernel-init-attempt",
                       O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (receipt < 0) return 2;
    close(receipt);
    setvbuf(stdout, NULL, _IOLBF, 0);
    struct fpc_sensor_device sensor = { .fd = -1 };
    struct fpc_qsee_session session = FPC_QSEE_SESSION_INIT;
    struct fpc_protocol protocol = { .ctx = &session, .exchange = fpc_qsee_command };
    int status = fpc_sensor_open(&sensor, "/dev/fpc1020");
    if (!status) status = fpc_qsee_open(&session, FPC_QSEE_APP_NAME);
    if (!status) status = fpc_sensor_reset(&sensor);
    if (!status) {
        struct fpc_result result = fpc_sensor(&protocol, FPC_SENSOR_INIT, NULL);
        printf("FPC_INIT_RESULT transport=%d outer=%d command=%d\n",
               result.transport, result.outer, result.command);
        if (!fpc_result_ok(result)) status = -1;
    }
    if (!status) {
        struct fpc_result result = fpc_sensor(&protocol, FPC_SENSOR_DEEP_SLEEP, NULL);
        printf("FPC_SLEEP_RESULT transport=%d outer=%d command=%d\n",
               result.transport, result.outer, result.command);
        if (!fpc_result_ok(result)) status = -1;
    }
    /* Reached only after synchronous calls return. No timeout kill/retry. */
    fpc_qsee_close(&session);
    fpc_sensor_close(&sensor);
    printf("FPC_INIT_FINISHED status=%d capture_started=false\n", status);
    return status ? 1 : 0;
}
