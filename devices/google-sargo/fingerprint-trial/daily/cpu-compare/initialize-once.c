/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Daily-device INIT/DEEP_SLEEP only. No capture, database or credential API. */
#define _GNU_SOURCE
#include "protocol.h"
#include "qsee-transport.h"
#include "sensor.h"
#include <fcntl.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <unistd.h>

#define ROOT "/var/tmp/sargo-fingerprint-cpu-compare-20260913"
#define BOOT "0ac24861-f5de-4f09-8128-fd24c2f80070"

static int matching_file(const char *path, const char *expected)
{
    char line[128];
    FILE *file = fopen(path, "re");
    if (!file) return 0;
    int ok = fgets(line, sizeof(line), file) && !strcmp(line, expected);
    fclose(file);
    return ok;
}

int main(int argc, char **argv)
{
    if (argc != 2 || geteuid() ||
        (strcmp(argv[1], "--cpu=7") && strcmp(argv[1], "--cpu=1"))) return 2;
    int cpu = argv[1][6] - '0';
    struct utsname kernel;
    if (uname(&kernel) || strcmp(kernel.release, "7.1.2-0.pocketfed.sdm670.11.fc46.aarch64") ||
        !matching_file("/proc/sys/kernel/random/boot_id", BOOT "\n")) return 2;
    FILE *file = fopen("/proc/cmdline", "re");
    char *line = NULL;
    size_t size = 0;
    if (!file || getline(&line, &size, file) < 0) return 2;
    fclose(file);
    int serial = 0, other_serial = 0, fprintd_mask = 0, phosh_mask = 0;
    for (char *word = strtok(line, " \n"); word; word = strtok(NULL, " \n")) {
        if (!strncmp(word, "androidboot.serialno=", 21)) {
            if (!strcmp(word, "androidboot.serialno=994AY18RSD")) serial++;
            else other_serial++;
        }
        fprintd_mask += !strcmp(word, "systemd.mask=fprintd.service");
        phosh_mask += !strcmp(word, "systemd.mask=phosh-fingerprint-auth.socket");
    }
    free(line);
    if (serial != 1 || other_serial || fprintd_mask != 1 || phosh_mask != 1) return 2;
    cpu_set_t affinity;
    CPU_ZERO(&affinity);
    CPU_SET(cpu, &affinity);
    if (sched_setaffinity(0, sizeof(affinity), &affinity) ||
        sched_getaffinity(0, sizeof(affinity), &affinity) ||
        CPU_COUNT(&affinity) != 1 || !CPU_ISSET(cpu, &affinity)) return 2;
    char directory[160];
    snprintf(directory, sizeof(directory), ROOT "/cpu%d", cpu);
    struct stat st;
    if (lstat(ROOT, &st) || !S_ISDIR(st.st_mode) || st.st_uid || (st.st_mode & 0777) != 0700)
        return 2;
    int dir = open(directory, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (dir < 0 || fstat(dir, &st) || st.st_uid || (st.st_mode & 0777) != 0700) return 2;
    int receipt = openat(dir, "native-attempt", O_WRONLY | O_CREAT | O_EXCL |
                         O_CLOEXEC | O_NOFOLLOW, 0600);
    if (receipt < 0) return 2;
    if (fsync(receipt) || fsync(dir)) return 2;
    close(receipt);
    close(dir);
    setvbuf(stdout, NULL, _IOLBF, 0);
    printf("FPC_CPU_READY cpu=%d pid=%d boot=" BOOT "\n", sched_getcpu(), getpid());
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
    /* Only reached after synchronous secure calls return. Never kill/retry. */
    fpc_qsee_close(&session);
    fpc_sensor_close(&sensor);
    printf("FPC_CPU_FINISHED cpu=%d status=%d capture_started=false\n", sched_getcpu(), status);
    return status ? 1 : 0;
}
