/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Dedicated test-sargo native UID 1000 experiment; no daily-phone state. The intent is durably retained on the host
 * before boot. This file exposes no retry/recovery or configurable UID. */
#include "auth-store.c"
#include "auth-backend.h"
#include <signal.h>

#define LAB_UID 1000u
static volatile sig_atomic_t cancelled;
static void stop(int signal_number) { (void)signal_number; cancelled = 1; }

static int enroll_once(struct auth_store *store)
{
    struct disk_record record = {0};
    struct auth_credential credential = {0};
    struct auth_backend backend = AUTH_BACKEND_INIT;
    char intent[40], complete[40];
    int fd = -1, rc = names(LAB_UID, intent, complete);
    if (rc) goto out;
    rc = exists(store, complete);
    if (rc) { rc = rc > 0 ? -EEXIST : rc; goto out; }
    rc = read_record(store, intent, &record);
    if (rc) goto out;
    rc = decode(&record, RECORD_INTENT, LAB_UID, &credential);
    if (rc) goto out;
    if (cancelled) { rc = -ECANCELED; goto out; }
    fd = openat(store->directory, "uid-1000.lab-native-enroll-attempt-20260912",
        O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) { rc = -errno; goto out; }
    const char note[] = "First test-sargo native UID 0x700003e8 attempt. Host intent retained. No retry.\n";
    if (write(fd, note, sizeof note - 1) != sizeof note - 1 ||
        fsync(fd) || fsync(store->directory)) { rc = -EIO; goto out; }
    close(fd); fd = -1;
    if (dprintf(STDERR_FILENO, "native_enroll_stage=backend_open_begin\n") < 0) { rc=-EIO; goto out; }
    rc = auth_backend_open(&backend, &cancelled);
    printf("lab_backend_status=%d\n", rc); fflush(stdout);
    if (rc) goto out;
    if (cancelled) { rc = -ECANCELED; goto out; }
    if (dprintf(STDERR_FILENO, "native_enroll_stage=enroll_begin\n") < 0) { rc=-EIO; goto out; }
    size_t length = 0;
    struct sargo_gk_result result = sargo_gk_enroll_new(&backend.gk,
        credential.gatekeeper_uid, credential.secret, sizeof credential.secret,
        credential.handle, sizeof credential.handle, &length);
    printf("lab_enroll_transport=%d secure_status=%d validated_handle_length=%zu\n",
           result.transport, result.status, length); fflush(stdout);
    rc = auth_backend_status(result);
    if (rc) goto out;
    if (length != sizeof credential.handle) { rc = -EPROTO; goto out; }
    fprintf(stderr, "native_enroll_stage=commit_begin\n");
    rc = auth_store_commit(store, &credential);
    printf("lab_commit_status=%d\n", rc); fflush(stdout);
out:
    if (fd >= 0) close(fd);
    fprintf(stderr, "native_enroll_stage=close_begin\n");
    auth_backend_close(&backend);
    auth_credential_clear(&credential);
    explicit_bzero(&record, sizeof record);
    return rc;
}

int main(int argc, char **argv)
{
    if (getuid() || geteuid() || argc != 2 ||
        strcmp(argv[1], "first-test-sargo-native-uid-1000")) return 2;
    /* The root controller and unit bind this to exact test serial and USB run.
     * The production broker domain does not read /proc/cmdline. */
    if (dprintf(STDERR_FILENO, "native_enroll_stage=probe_started\n") < 0) return 3;
    struct sigaction action = {.sa_handler = stop}; sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) return 1;
    struct auth_store store = {.directory = -1, .lock = -1};
    int rc = auth_store_open(&store);
    if (!rc) rc = enroll_once(&store);
    auth_store_close(&store);
    printf("lab_enroll_result=%d\n", rc);
    return rc < 0 ? 1 : 0;
}
