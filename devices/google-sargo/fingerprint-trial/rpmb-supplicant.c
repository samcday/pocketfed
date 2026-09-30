// SPDX-License-Identifier: MIT
/* Temporary Sargo integration: same receiver as FS/GPFS; RPMB writes disabled.
 * Link against the already reviewed qsee-supplicant sources and transport.
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
#include <unistd.h>

static volatile sig_atomic_t stopping;
static int rpmb_fd = -1;
static struct sargo_rpmb_geometry geometry;
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
        major(st.st_rdev) != 504 || minor(st.st_rdev) != 0) {
        close(rpmb_fd);
        rpmb_fd = -1;
        return -1;
    }
    return 0;
}

static int read_only_transfer(void *context, bool write,
    const void *request, size_t request_frames,
    void *response, size_t response_frames)
{
    /* Independent guard: this executable has no mode that enables writes. */
    if (write || stopping)
        return -EPERM;
    return sargo_rpmb_mmc_transfer(context, false, request, request_frames,
                                  response, response_frames);
}

static int dispatch_rpmb(struct qs_store *store, void *memory, size_t size)
{
    (void)store;
    unsigned char *b = memory;
    if (!b || size < SARGO_RPMB_BUFFER)
        return -1;
    /* TEE allocation may be page-rounded; protocol capacity stays 25 KiB. */
    uint32_t cmd = get32(b), detail = 0, version = 0;
    if (cmd == 0x101)
        version = get32(b + 4);
    else if (cmd == 0x102 || cmd == 0x103) {
        detail = get32(b + 4);
        version = get32(b + 16);
    }
    int rc = sargo_rpmb_dispatch(b, SARGO_RPMB_BUFFER, &geometry, false,
                                read_only_transfer, &rpmb_fd);
    fprintf(stderr, "event=rpmb_callback cmd=%u detail=%u version_field=%u "
            "dispatch=%d reply_status=%d writes=disabled\n", cmd, detail,
            version, rc, rc ? -1 : (int32_t)get32(b + (cmd == 0x101 ? 8 : 4)));
    /* Never log frames, addresses, counters, nonces, MACs or record contents. */
    return rc;
}

static void ready(void *data)
{
    bool *registered = data;
    *registered = true;
    if (qs_notify("READY=1\nSTATUS=FS, GPFS and read-only RPMB registered"))
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
    if (argc != 2 || strcmp(argv[1], "--serve-read-only") || geteuid()) {
        fprintf(stderr, "Requires root and --serve-read-only.\n");
        return 2;
    }
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
    fprintf(stderr, "event=rpmb_geometry sectors_512=%u reliable_frames=%u writes=disabled\n",
            geometry.sectors_512, geometry.reliable_frames);
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
