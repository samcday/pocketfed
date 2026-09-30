// SPDX-License-Identifier: MIT
/* Optional Sargo listener: FS, GPFS and authenticated RPMB on one receiver.
 * Explicit activation only; no key programming or credential provisioning.
 */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "qsee_supplicant.h"
#include "notify.h"
#include "rpmb-protocol.h"
#include "rpmb-mmc.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <sys/prctl.h>
#include <unistd.h>
#include "sargo-device.h"
#include "write-policy.h"

static volatile sig_atomic_t stopping;
static int rpmb_fd = -1;
static struct sargo_rpmb_geometry geometry;
static struct sargo_write_policy policy;
static void stop_handler(int signo) { (void)signo; stopping = 1; }

static uint32_t get32(const unsigned char *b)
{
    return b[0] | (uint32_t)b[1] << 8 | (uint32_t)b[2] << 16 |
        (uint32_t)b[3] << 24;
}

static int read_attribute(const char *name, unsigned long *value)
{
    char path[128], buf[32], *end;
    snprintf(path, sizeof(path), "/sys/block/mmcblk0/device/%s", name);
    FILE *file = fopen(path, "re");
    if (!file)
        return -1;
    size_t n = fread(buf, 1, sizeof(buf) - 1, file);
    int failed = ferror(file) || !feof(file);
    fclose(file);
    if (failed || !n)
        return -1;
    buf[n] = 0;
    if (!isdigit((unsigned char)buf[0]))
        return -1;
    errno = 0;
    *value = strtoul(buf, &end, 0);
    if (errno || end == buf)
        return -1;
    while (isspace((unsigned char)*end)) ++end;
    return *end ? -1 : 0;
}

static int open_rpmb(void)
{
    struct stat st;
    unsigned long mult, enhanced, reliable;
    if (read_attribute("raw_rpmb_size_mult", &mult) ||
        read_attribute("enhanced_rpmb_supported", &enhanced) ||
        read_attribute("rel_sectors", &reliable) ||
        mult != 0x80 || enhanced != 1 || reliable != 1)
        return -1;
    geometry.sectors_512 = mult * 256;
    geometry.reliable_frames = 32;
    rpmb_fd = open("/dev/mmcblk0rpmb", O_RDWR | O_CLOEXEC | O_NOFOLLOW);
    if (rpmb_fd < 0)
        return -1;
    if (fstat(rpmb_fd, &st) || !S_ISCHR(st.st_mode) || st.st_uid ||
        st.st_gid || (st.st_mode & 0777) != 0600 ||
        sargo_rpmb_identity(&st)) {
        close(rpmb_fd);
        rpmb_fd = -1;
        return -1;
    }
    return 0;
}

static int checked_transfer(void *context, bool write,
    const void *request, size_t request_frames,
    void *response, size_t response_frames)
{
    bool failed_before = policy.failed;
    int rc = sargo_checked_transfer(&policy, stopping, sargo_rpmb_mmc_transfer,
        context, write, request, request_frames, response, response_frames);
    if (!failed_before && policy.failed)
        fprintf(stderr, "event=rpmb_writes_disabled reason=transport_or_device_write_failure\n");
    return rc;
}

static int dispatch_rpmb(struct qs_store *store, void *memory, size_t size)
{
    (void)store;
    unsigned char *b = memory;
    if (!b || size < SARGO_RPMB_BUFFER)
        return -1;
    /* TEE allocation may be page-rounded; protocol capacity stays 25 KiB. */
    uint32_t cmd = get32(b);
    int rc = sargo_rpmb_dispatch(b, SARGO_RPMB_BUFFER, &geometry, policy.enabled,
                                checked_transfer, &rpmb_fd);
    if (rc || (int32_t)get32(b + (cmd == 0x101 ? 8 : 4)))
        fprintf(stderr, "event=rpmb_request_failed command=%u dispatch=%d writes_disabled=%d\n",
                cmd, rc, policy.failed);
    /* Never log frames, addresses, counters, nonces, MACs or record contents. */
    return rc;
}

static void ready(void *data)
{
    bool *registered = data;
    *registered = true;
    if (qs_notify("READY=1\nSTATUS=FS, GPFS and Sargo RPMB registered"))
        fprintf(stderr, "event=notify_error errno=%d\n", errno);
}

int main(int argc, char **argv)
{
    struct qs_store store = {.root_fd = -1};
    bool registered = false;
    const struct qs_service services[] = {
        {QS_FS_SERVICE_ID, QS_FS_BUFFER_SIZE, qs_fs_dispatch, qs_fs_reset},
        {QS_GPFS_SERVICE_ID, QS_GPFS_BUFFER_SIZE, qs_gpfs_dispatch, NULL},
        {SARGO_RPMB_LISTENER, SARGO_RPMB_BUFFER, dispatch_rpmb, NULL},
    };
    if (argc != 2 || (strcmp(argv[1], "--serve-read-only") &&
                     strcmp(argv[1], "--serve-authenticated")) || geteuid()) {
        fprintf(stderr, "Requires root and --serve-read-only or --serve-authenticated.\n");
        return 2;
    }
    if (!sargo_compatible() || prctl(PR_SET_DUMPABLE, 0)) return 2;
    policy.enabled = !strcmp(argv[1], "--serve-authenticated");
    umask(0077);
    struct sigaction action = {.sa_handler = stop_handler};
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGTERM, &action, NULL) || sigaction(SIGINT, &action, NULL) ||
        open_rpmb()) {
        fprintf(stderr, "RPMB startup validation failed.\n");
        return 1;
    }
    if (qs_store_open(&store, "/var/lib/qsee-supplicant", 0600, 0700)) {
        close(rpmb_fd);
        return 1;
    }
    fprintf(stderr, "event=rpmb_ready sectors_512=%u reliable_frames=%u authenticated_writes=%d\n",
            geometry.sectors_512, geometry.reliable_frames, policy.enabled);
    int rc = qs_qseecom_transport.serve(&store, services,
        sizeof(services) / sizeof(services[0]), &stopping, ready, &registered);
    int error = rc ? errno : 0;
    if (registered)
        (void)qs_notify("STOPPING=1\nSTATUS=Listener services stopped");
    qs_store_close(&store);
    close(rpmb_fd);
    fprintf(stderr, "event=shutdown status=%d errno=%d stopping=%d\n", rc, error, stopping);
    /* One registration lifetime, no reconnect or startup retry. */
    return stopping && !rc ? 0 : 1;
}
