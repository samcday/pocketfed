/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Dedicated test-sargo experiment. The intent is durably retained on the host
 * before boot. Deliberate one-use read-path recovery of the recorded first failure.
 * Fixed UID and original secret; no loop, write enablement or record deletion. */
#include "auth-store.c"
#include "auth-backend.h"
#include <signal.h>
#include <ctype.h>

#define LAB_UID 1234u
#define LAB_RUN "sargo-fingerprint-lab-gatekeeper-rw0-20260911"
static volatile sig_atomic_t cancelled;
static void stop(int signal_number) { (void)signal_number; cancelled = 1; }

static bool token(const char *line, const char *wanted)
{
    size_t n = strlen(wanted);
    while (*line) {
        while (isspace((unsigned char)*line)) ++line;
        const char *end = line;
        while (*end && !isspace((unsigned char)*end)) ++end;
        if ((size_t)(end - line) == n && !memcmp(line, wanted, n)) return true;
        line = end;
    }
    return false;
}

static bool identity(const char *line)
{
    return token(line, "androidboot.serialno=99NAY1AZG1") &&
        token(line, "pocketfed.root_mode=usb") &&
        token(line, "pocketfed.liveboot=" LAB_RUN);
}

static const char history_note[] = "test-sargo 99NAY1AZG1 UID 0x700004d2: first gatekeeper-ro-20260911 attempt returned transport 0, secure -30, no handle; RPMB read version 0 rejected; original host intent and receipt retained.\n";

static int check_history(struct auth_store *store)
{
    int fd = openat(store->directory, "uid-1234.lab-prior-failure",
                    O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return -errno;
    int rc = check_regular(fd, store->owner, store->group, sizeof history_note - 1);
    char content[sizeof history_note] = {0};
    if (!rc && (read(fd, content, sizeof content) != sizeof history_note - 1 ||
                memcmp(content, history_note, sizeof history_note - 1))) rc = -EUCLEAN;
    close(fd);
    return rc;
}

static int enroll_once(struct auth_store *store)
{
    struct disk_record record = {0};
    struct auth_credential credential = {0};
    struct auth_backend backend = AUTH_BACKEND_INIT;
    char intent[40], complete[40];
    int fd = -1, rc = check_history(store);
    if (rc) goto out;
    rc = names(LAB_UID, intent, complete);
    if (rc) goto out;
    rc = exists(store, complete);
    if (rc) { rc = rc > 0 ? -EEXIST : rc; goto out; }
    rc = read_record(store, intent, &record);
    if (rc) goto out;
    rc = decode(&record, RECORD_INTENT, LAB_UID, &credential);
    if (rc) goto out;
    if (cancelled) { rc = -ECANCELED; goto out; }
    fd = openat(store->directory, "uid-1234.lab-rw0-recovery-attempt",
        O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) { rc = -errno; goto out; }
    const char note[] = "One RW-zero read-path recovery for test-sargo UID 0x700004d2. Original intent/history retained. No retry.\n";
    if (write(fd, note, sizeof note - 1) != sizeof note - 1 ||
        fsync(fd) || fsync(store->directory)) { rc = -EIO; goto out; }
    close(fd); fd = -1;
    rc = auth_backend_open(&backend, &cancelled);
    printf("lab_backend_status=%d\n", rc); fflush(stdout);
    if (rc) goto out;
    if (cancelled) { rc = -ECANCELED; goto out; }
    size_t length = 0;
    struct sargo_gk_result result = sargo_gk_enroll_new(&backend.gk,
        credential.gatekeeper_uid, credential.secret, sizeof credential.secret,
        credential.handle, sizeof credential.handle, &length);
    printf("lab_enroll_transport=%d secure_status=%d validated_handle_length=%zu\n",
           result.transport, result.status, length); fflush(stdout);
    rc = auth_backend_status(result);
    if (rc) goto out;
    if (length != sizeof credential.handle) { rc = -EPROTO; goto out; }
    rc = auth_store_commit(store, &credential);
    printf("lab_commit_status=%d\n", rc); fflush(stdout);
out:
    if (fd >= 0) close(fd);
    auth_backend_close(&backend);
    auth_credential_clear(&credential);
    explicit_bzero(&record, sizeof record);
    return rc;
}

int main(int argc, char **argv)
{
    if (getuid() || geteuid() || argc != 2 ||
        strcmp(argv[1], "recover-read-path-test-sargo-uid-1234")) return 2;
    char line[8192];
    FILE *cmdline = fopen("/proc/cmdline", "re");
    if (!cmdline) return 2;
    bool allowed = fgets(line, sizeof line, cmdline) &&
        (strchr(line, '\n') || feof(cmdline)) && identity(line);
    fclose(cmdline);
    if (!allowed) return 2;
    struct sigaction action = {.sa_handler = stop}; sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) return 1;
    struct auth_store store = {.directory = -1, .lock = -1};
    int rc = auth_store_open(&store);
    if (!rc) rc = enroll_once(&store);
    auth_store_close(&store);
    printf("lab_enroll_result=%d\n", rc);
    return rc < 0 ? 1 : 0;
}
