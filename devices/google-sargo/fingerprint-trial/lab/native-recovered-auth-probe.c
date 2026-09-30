/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Verify the recovered UID and the original fingerprint UID. No enrollment. */
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
        strcmp(argv[1], "--verify-recovered-lab-credentials")) return 2;
    /* Exact test serial, run, USB root and hashes are checked by the controller
     * and unit outside the intentionally confined production broker domain. */
    if (dprintf(STDERR_FILENO, "native_auth_stage=probe_started\n") < 0) return 3;
    struct sigaction action = {.sa_handler = stop};
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) return 1;
    struct auth_store store = {.directory = -1, .lock = -1};
    struct auth_backend backend = AUTH_BACKEND_INIT;
    struct auth_credential credentials[2] = {{0}};
    const unsigned uids[2] = {1000, 1234};
    unsigned char hat[SARGO_GK_HAT_SIZE] = {0};
    int rc = auth_store_open(&store);
    if (rc) goto out;
    for (unsigned i = 0; i < 2; ++i) {
        rc = auth_store_load(&store, uids[i], &credentials[i]);
        if (rc) goto out;
        if (credentials[i].linux_uid != uids[i] ||
            credentials[i].gatekeeper_uid != 0x70000000u + uids[i]) {
            rc = -EINVAL; goto out;
        }
    }
    int fd = openat(store.directory, "lab-recovered-auth-attempt-20260912",
                   O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) { rc = -errno; goto out; }
    const char note[] = "One verification each for test-sargo UIDs 1000 and 1234; no enrollment or retry.\n";
    if (write(fd, note, sizeof note - 1) != sizeof note - 1 || fsync(fd) || fsync(store.directory)) {
        close(fd); rc = -EIO; goto out;
    }
    close(fd);
    fprintf(stderr, "native_auth_stage=backend_open_begin\n");
    rc = auth_backend_open(&backend, &stopping);
    fprintf(stderr, "native_auth_stage=backend_open_end status=%d\n", rc);
    if (rc) goto out;
    for (unsigned i = 0; i < 2; ++i) {
        if (stopping) { rc = -ECANCELED; goto out; }
        const struct auth_credential *c = &credentials[i];
        fprintf(stderr, "native_auth_stage=verify_begin uid=%u\n", c->linux_uid);
        struct sargo_gk_result result = sargo_gk_verify(&backend.gk,
            c->gatekeeper_uid, 1, c->handle, sizeof c->handle,
            c->secret, sizeof c->secret, hat);
        fprintf(stderr, "native_auth_stage=verify_end uid=%u transport=%d secure_status=%d\n",
                c->linux_uid, result.transport, result.status);
        explicit_bzero(hat, sizeof hat);
        rc = auth_backend_status(result);
        if (rc) goto out;
    }
out:
    fprintf(stderr, "native_auth_stage=close_begin\n");
    auth_backend_close(&backend);
    for (unsigned i = 0; i < 2; ++i) auth_credential_clear(&credentials[i]);
    explicit_bzero(hat, sizeof hat);
    auth_store_close(&store);
    fprintf(stderr, "native_auth_stage=finished status=%d\n", rc);
    return rc ? 1 : 0;
}
