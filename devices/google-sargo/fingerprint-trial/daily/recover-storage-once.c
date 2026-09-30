/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Explicitly approved recovery only. The launcher and systemd unit bind this
 * executable to daily sam-sargo 994AY18RSD, after verified RPMB service startup.
 * Reuse the original random secret for UID 0x700003e8. No Android UID, loop,
 * automatic retry, receipt deletion, or substitution of another identity. */
#include "auth-store.c"
#include "auth-backend.h"
#include <signal.h>

#define DAILY_UID 1000u
static const char prior_name[] = "uid-1000.first-recovery-attempt";
static const char receipt_name[] = "uid-1000.storage-recovery-attempt";
static const char backup_name[] = "uid-1000.pre-storage-recovery.intent";
static const char prior_note[] = "One controlled recovery of this trial's unpublished native UID 0x700003e8.\nOriginal intent and secret retained. No automatic retry.\n";
static const char receipt_note[] = "One authenticated-storage recovery for sam-sargo 994AY18RSD UID 0x700003e8. Prior receipt and exact original intent retained. No retry.\n";
static volatile sig_atomic_t cancelled;
static void stop(int signal_number) { (void)signal_number; cancelled = 1; }

static int check_history(struct auth_store *store)
{
    int fd = openat(store->directory, prior_name,
                    O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return -errno;
    int rc = check_regular(fd, store->owner, store->group, sizeof prior_note - 1);
    char content[sizeof prior_note] = {0};
    if (!rc && (read(fd, content, sizeof content) != sizeof prior_note - 1 ||
                memcmp(content, prior_note, sizeof prior_note - 1))) rc = -EUCLEAN;
    close(fd);
    return rc;
}

/* A partial create/sync consumes this invocation; nothing is removed on error.
 * The intent snapshot is durable before any secure credential operation. */
static int retain_new(struct auth_store *store, const char *name,
                       const void *data, size_t length)
{
    int fd = openat(store->directory, name,
                   O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) return -errno;
    int rc = 0;
    if (write(fd, data, length) != (ssize_t)length || fsync(fd) ||
        fsync(store->directory)) rc = -EIO;
    close(fd);
    return rc;
}

static int recover_once(struct auth_store *store)
{
    struct disk_record record = {0};
    struct auth_credential credential = {0};
    struct auth_backend backend = AUTH_BACKEND_INIT;
    char intent[40], complete[40];
    int rc = check_history(store);
    if (rc) goto out;
    rc = names(DAILY_UID, intent, complete);
    if (rc) goto out;
    rc = exists(store, complete);
    if (rc) { rc = rc > 0 ? -EEXIST : rc; goto out; }
    rc = exists(store, backup_name);
    if (rc) { rc = rc > 0 ? -EEXIST : rc; goto out; }
    rc = read_record(store, intent, &record);
    if (rc) goto out;
    rc = decode(&record, RECORD_INTENT, DAILY_UID, &credential);
    if (rc) goto out;
    if (cancelled) { rc = -ECANCELED; goto out; }
    rc = retain_new(store, receipt_name, receipt_note, sizeof receipt_note - 1);
    if (rc) goto out;
    rc = retain_new(store, backup_name, &record, sizeof record);
    if (rc) goto out;
    rc = auth_backend_open(&backend, &cancelled);
    printf("recovery_backend_status=%d\n", rc); fflush(stdout);
    if (rc) goto out;
    if (cancelled) { rc = -ECANCELED; goto out; }
    size_t length = 0;
    struct sargo_gk_result result = sargo_gk_enroll_new(&backend.gk,
        credential.gatekeeper_uid, credential.secret, sizeof credential.secret,
        credential.handle, sizeof credential.handle, &length);
    printf("recovery_enroll_transport=%d secure_status=%d validated_handle_length=%zu\n",
           result.transport, result.status, length); fflush(stdout);
    rc = auth_backend_status(result);
    if (rc) goto out;
    if (length != sizeof credential.handle) { rc = -EPROTO; goto out; }
    rc = auth_store_commit(store, &credential);
    printf("recovery_commit_status=%d\n", rc); fflush(stdout);
out:
    auth_backend_close(&backend);
    auth_credential_clear(&credential);
    explicit_bzero(&record, sizeof record);
    return rc;
}

int main(int argc, char **argv)
{
    if (getuid() || geteuid() || argc != 2 ||
        strcmp(argv[1], "recover-storage-sam-sargo-994AY18RSD-uid-1000")) return 2;
    struct sigaction action = {.sa_handler = stop}; sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) return 1;
    struct auth_store store = {.directory = -1, .lock = -1};
    int rc = auth_store_open(&store);
    if (!rc) rc = recover_once(&store);
    auth_store_close(&store);
    printf("recovery_result=%d\n", rc);
    return rc < 0 ? 1 : 0;
}
