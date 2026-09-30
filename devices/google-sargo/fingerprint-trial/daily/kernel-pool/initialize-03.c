/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Daily INIT, allocation-only CMA baseline, then DEEP_SLEEP. No capture or credentials. */
#define _GNU_SOURCE
#include "protocol.h"
#include "qsee-transport.h"
#include "sensor.h"
#include <errno.h>
#include <fcntl.h>
#include <linux/dma-heap.h>
#include <sys/ioctl.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/utsname.h>
#include <unistd.h>

#define ROOT "/run/sargo-fingerprint-pool-20260913"
int main(int argc, char **argv)
{
    if (argc != 2 || geteuid() ||
        strcmp(argv[1], "--cpu=7")) return 2;
    int cpu = argv[1][6] - '0';
    struct utsname kernel;
    if (uname(&kernel) || strcmp(kernel.release, "7.1.2-0.pocketfed.sdm670.11.fc46.aarch64")) return 2;
    FILE *file = fopen("/proc/cmdline", "re");
    char *line = NULL;
    size_t size = 0;
    if (!file || getline(&line, &size, file) < 0) return 2;
    fclose(file);
    int serial = 0, other_serial = 0, run = 0, usb = 0;
    for (char *word = strtok(line, " \n"); word; word = strtok(NULL, " \n")) {
        run += !strcmp(word, "pocketfed.liveboot=sargo-fingerprint-pool-baseline-03-20260913") ||
               !strcmp(word, "pocketfed.liveboot=sargo-fingerprint-pool-reuse-03-20260913");
        usb += !strcmp(word, "pocketfed.root_mode=usb");
        if (!strncmp(word, "androidboot.serialno=", 21)) {
            if (!strcmp(word, "androidboot.serialno=994AY18RSD")) serial++;
            else other_serial++;
        }
    }
    free(line);
    if (serial != 1 || other_serial || run != 1 || usb != 1) return 2;
    const char *masks[] = { "/etc/systemd/system/fprintd.service",
                           "/etc/systemd/system/phosh-fingerprint-auth.socket" };
    for (unsigned int i = 0; i < sizeof(masks) / sizeof(masks[0]); i++) {
        char target[32] = {0};
        ssize_t length = readlink(masks[i], target, sizeof(target) - 1);
        if (length != 9 || strcmp(target, "/dev/null")) return 2;
    }
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
    printf("FPC_CPU_READY cpu=%d pid=%d disposable=true\n", sched_getcpu(), getpid());
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
        int heap = open("/dev/dma_heap/default_cma_region", O_RDONLY | O_CLOEXEC);
        if (heap < 0) status = -errno;
        printf("FPC_INIT_CMA_BEGIN count=1000 bytes=8192 cpu=%d\n", sched_getcpu());
        for (unsigned int i = 1; !status && i <= 1000; i++) {
            struct dma_heap_allocation_data allocation = {
                .len = 8192, .fd_flags = O_RDWR | O_CLOEXEC,
            };
            if (ioctl(heap, DMA_HEAP_IOCTL_ALLOC, &allocation)) {
                status = -errno;
                break;
            }
            close(allocation.fd);
            if (i % 100 == 0) printf("FPC_INIT_CMA_PROGRESS completed=%u\n", i);
            usleep(5000);
        }
        if (heap >= 0) close(heap);
        printf("FPC_INIT_CMA_END status=%d\n", status);
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
