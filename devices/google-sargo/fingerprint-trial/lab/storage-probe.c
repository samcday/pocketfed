/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Fixed invalid verification, solely to observe the read-only storage path.
 * No real handle/password, enrollment, deletion, exported token or retry. */
#define _GNU_SOURCE
#include "auth-backend.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef PROBE_RUN
#define PROBE_RUN "sargo-fingerprint-lab-storage-probe-20260911"
#endif
static volatile sig_atomic_t cancelled;
static void stop(int n) { (void)n; cancelled = 1; }

static bool token(const char *line, const char *wanted)
{
    size_t length = strlen(wanted);
    while (*line) {
        while (isspace((unsigned char)*line)) ++line;
        const char *end = line;
        while (*end && !isspace((unsigned char)*end)) ++end;
        if ((size_t)(end - line) == length && !memcmp(line, wanted, length)) return true;
        line = end;
    }
    return false;
}

static bool identity(const char *line)
{
    return token(line, "androidboot.serialno=99NAY1AZG1") &&
        token(line, "pocketfed.root_mode=usb") &&
        token(line, "pocketfed.liveboot=" PROBE_RUN);
}

static int probe_once(int directory)
{
    struct auth_backend backend = AUTH_BACKEND_INIT;
    unsigned char handle[SARGO_GK_HANDLE_SIZE] = {0};
    unsigned char password[1] = {0}, hat[SARGO_GK_HAT_SIZE] = {0};
    int rc = -ECANCELED;
    if (cancelled) return rc;
    int fd = openat(directory, "storage-probe-attempt", O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return -errno;
    const char note[] = "One deliberately invalid verification for native lab UID 0x700004d2; no enrollment or retry.\n";
    if (write(fd, note, sizeof note - 1) != sizeof note - 1 || fsync(fd) || fsync(directory)) {
        close(fd); return -EIO;
    }
    close(fd);
    rc = auth_backend_open(&backend, &cancelled);
    printf("lab_probe_backend=%d\n", rc); fflush(stdout);
    if (cancelled) rc = -ECANCELED;
    if (rc) goto out;
    struct sargo_gk_result result = sargo_gk_verify(&backend.gk,
        0x700004d2, 1, handle, sizeof handle, password, sizeof password, hat);
    printf("lab_probe_transport=%d secure_status=%d synthetic_invalid_handle=true\n",
           result.transport, result.status); fflush(stdout);
    /* A negative/throttled verification is an observed diagnostic, never an
     * authentication success. An unexpected success is refused and wiped. */
    rc = result.transport ? result.transport : result.status ? 0 : -EPROTO;
out:
    auth_backend_close(&backend);
    explicit_bzero(hat, sizeof hat);
    explicit_bzero(handle, sizeof handle);
    explicit_bzero(password, sizeof password);
    return rc;
}

int main(int argc, char **argv)
{
    if (getuid() || geteuid() || argc != 2 || strcmp(argv[1], "inspect-storage-with-invalid-handle")) return 2;
    char line[8192];
    FILE *cmdline = fopen("/proc/cmdline", "re");
    if (!cmdline) return 2;
    bool allowed = fgets(line, sizeof line, cmdline) &&
        (strchr(line, '\n') || feof(cmdline)) && identity(line);
    fclose(cmdline);
    if (!allowed) return 2;
    struct sigaction action = {.sa_handler = stop}; sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) return 1;
    int directory = open("/run/pocketfed-keymaster", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    struct stat st;
    if (directory < 0) return 1;
    if (fstat(directory, &st) || st.st_uid || st.st_gid || (st.st_mode & 07777) != 0700) {
        close(directory); return 1;
    }
    int rc = probe_once(directory);
    close(directory);
    printf("lab_probe_result=%d\n", rc);
    return rc ? 1 : 0;
}
