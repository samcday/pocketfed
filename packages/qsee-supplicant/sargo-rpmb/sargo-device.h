/* SPDX-License-Identifier: MIT */
#ifndef SARGO_DEVICE_H
#define SARGO_DEVICE_H
#include <limits.h>
#include <stdbool.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>

static bool sargo_compatible_data(const char *data, size_t size)
{
    bool found = false;
    if (!data || !size || size > 4096 || data[size - 1]) return false;
    for (size_t i = 0; i < size;) {
        size_t length = strnlen(data + i, size - i);
        if (!length || length == size - i) return false;
        if (length == sizeof("google,sargo") - 1 &&
            !memcmp(data + i, "google,sargo", length)) found = true;
        i += length + 1;
    }
    return found;
}

static inline bool sargo_compatible(void)
{
    char data[4097];
    FILE *f = fopen("/sys/firmware/devicetree/base/compatible", "re");
    if (!f) return false;
    size_t size = fread(data, 1, sizeof data, f);
    bool ok = !ferror(f) && feof(f) && sargo_compatible_data(data, size);
    fclose(f);
    return ok;
}

/* Character majors vary with initialization order. Bind the opened descriptor
 * to the kernel's named RPMB device and its actual mmcblk0 card parent. */
static int sargo_rpmb_identity_at(const struct stat *st, const char *rpmb_name,
                               const char *card_name, const char *char_root)
{
    char rpmb[PATH_MAX], card[PATH_MAX], parent[PATH_MAX];
    char name[PATH_MAX], resolved[PATH_MAX], value[64], *end;
    if (!S_ISCHR(st->st_mode) || !realpath(rpmb_name, rpmb) ||
        !realpath(card_name, card)) return -1;
    strcpy(parent, rpmb);
    char *slash = strrchr(parent, '/');
    if (!slash) return -1;
    *slash = 0;
    if (strcmp(parent, card)) return -1;
    int n = snprintf(name, sizeof name, "%s/dev", rpmb);
    if (n < 0 || (size_t)n >= sizeof name) return -1;
    FILE *f = fopen(name, "re");
    if (!f) return -1;
    size_t length = fread(value, 1, sizeof value - 1, f);
    int failed = ferror(f) || !feof(f);
    fclose(f);
    if (failed || !length || value[0] < '0' || value[0] > '9') return -1;
    value[length] = 0;
    unsigned long maj = strtoul(value, &end, 10);
    if (*end++ != ':' || *end < '0' || *end > '9') return -1;
    unsigned long min = strtoul(end, &end, 10);
    if (strcmp(end, "\n") || maj > UINT_MAX || min > UINT_MAX ||
        major(st->st_rdev) != maj || minor(st->st_rdev) != min) return -1;
    n = snprintf(name, sizeof name, "%s/%lu:%lu", char_root, maj, min);
    if (n < 0 || (size_t)n >= sizeof name || !realpath(name, resolved) ||
        strcmp(rpmb, resolved)) return -1;
    return 0;
}

static int sargo_rpmb_identity(const struct stat *st)
{
    return sargo_rpmb_identity_at(st, "/sys/bus/mmc_rpmb/devices/mmcblk0rpmb",
                               "/sys/block/mmcblk0/device", "/sys/dev/char");
}
#endif
