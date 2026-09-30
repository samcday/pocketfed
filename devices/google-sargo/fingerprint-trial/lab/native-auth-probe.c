/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Verify the existing dedicated lab credential once; no enrollment or export. */
#define _GNU_SOURCE
#include "auth-backend.h"
#include "auth-store.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static void stop(int sig) { (void)sig; stopping = 1; }

int main(int argc, char **argv)
{
    if (getuid() || geteuid() || argc != 2 ||
        strcmp(argv[1], "--verify-existing-lab-credential")) return 2;
    /* The controller and unit check the exact device, USB root and run token.
     * The production broker domain intentionally cannot read /proc/cmdline.
     * Require working diagnostics before opening storage or calling the TEE. */
    if (dprintf(STDERR_FILENO, "native_auth_stage=probe_started\n") < 0) return 3;
    struct sigaction action = {.sa_handler = stop};
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) return 1;
    struct auth_store store = {.directory = -1, .lock = -1};
    struct auth_backend backend = AUTH_BACKEND_INIT;
    struct auth_credential credential = {0};
    unsigned char hat[SARGO_GK_HAT_SIZE] = {0};
    int rc = auth_store_open(&store);
    if (rc) goto out;
    rc = auth_store_load(&store, 1234, &credential);
    if (rc) goto out;
    if (credential.linux_uid != 1234 || credential.gatekeeper_uid != 0x700004d2) {
        rc = -EINVAL; goto out;
    }
    int fd = openat(store.directory, "lab-native-auth-v2-attempt-20260912",
                    O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) { rc = -errno; goto out; }
    const char note[] = "One existing-credential verification; no enrollment, export or automatic retry.\n";
    if (write(fd, note, sizeof note - 1) != sizeof note - 1 || fsync(fd) || fsync(store.directory)) {
        close(fd); rc = -EIO; goto out;
    }
    close(fd);
    fprintf(stderr, "native_auth_stage=backend_open_begin\n");
    rc = auth_backend_open(&backend, &stopping);
    fprintf(stderr, "native_auth_stage=backend_open_end status=%d\n", rc);
    if (rc || stopping) { if (!rc) rc = -ECANCELED; goto out; }
    fprintf(stderr, "native_auth_stage=verify_begin uid=1234\n");
    struct sargo_gk_result result = sargo_gk_verify(&backend.gk,
        credential.gatekeeper_uid, 1, credential.handle, sizeof credential.handle,
        credential.secret, sizeof credential.secret, hat);
    fprintf(stderr, "native_auth_stage=verify_end transport=%d secure_status=%d\n",
            result.transport, result.status);
    rc = auth_backend_status(result);
out:
    fprintf(stderr, "native_auth_stage=close_begin\n");
    auth_backend_close(&backend);
    auth_credential_clear(&credential);
    explicit_bzero(hat, sizeof hat);
    auth_store_close(&store);
    fprintf(stderr, "native_auth_stage=finished status=%d\n", rc);
    return rc ? 1 : 0;
}
