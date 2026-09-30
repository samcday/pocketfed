/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Restore the retained lab credential after reboot and validate its HAT in FPC.
 * No Gatekeeper enrollment, fingerprint database access or sample collection. */
#define _GNU_SOURCE
#include "auth-store.h"
#include "auth-backend.h"
#include "protocol.h"
#include "sensor.h"
#include <ctype.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <unistd.h>

#define AUTH_RUN "sargo-fingerprint-lab-authorization-20260911"
static volatile sig_atomic_t cancelled;
static void stop(int n) { (void)n; cancelled = 1; }

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
        token(line, "pocketfed.liveboot=" AUTH_RUN);
}
static int command(const char *name, struct fpc_result r)
{
    printf("lab_%s transport=%d outer=%d command=%d\n", name, r.transport, r.outer, r.command);
    fflush(stdout);
    return fpc_result_ok(r) ? 0 : -EIO;
}
static int exchange(void *ctx, void *data, size_t n, int32_t *outer)
{
    return cancelled ? -ECANCELED : fpc_qsee_command(ctx, data, n, outer);
}
static int authorization_once(struct auth_store *store)
{
    struct auth_credential c = {0};
    struct auth_backend backend = AUTH_BACKEND_INIT;
    struct fpc_qsee_session fpc = FPC_QSEE_SESSION_INIT;
    struct fpc_protocol protocol = {.ctx=&fpc, .exchange=exchange};
    struct fpc_sensor_device sensor = {.fd=-1};
    unsigned char request[64] = {0}, response[960] = {0}, hat[69] = {0};
    bool initialized = false;
    uint64_t challenge = 0;
    int receipt = -1, rc = auth_store_load(store, 1234, &c);
    if (rc) goto out;
    if (c.linux_uid != 1234 || c.gatekeeper_uid != 0x700004d2) { rc=-EUCLEAN; goto out; }
    if (cancelled) { rc=-ECANCELED; goto out; }
    receipt = openat(store->directory, "uid-1234.lab-authorization-attempt",
        O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (receipt < 0) { rc=-errno; goto out; }
    const char note[] = "One post-reboot verification of retained test-sargo UID 0x700004d2 and FPC HAT authorization. No enrollment or retry.\n";
    if (write(receipt, note, sizeof note - 1) != sizeof note - 1 ||
        fsync(receipt) || fsync(store->directory)) { rc=-EIO; goto out; }
    close(receipt); receipt=-1;
    if (cancelled) { rc=-ECANCELED; goto out; }
    rc=fpc_sensor_open(&sensor, "/dev/fpc1020"); if (rc) goto out;
    rc=fpc_qsee_open(&fpc, FPC_QSEE_APP_NAME); if (rc) goto out;
    rc=fpc_sensor_reset(&sensor); if (rc) goto out;
    rc=command("sensor_initialize", fpc_sensor(&protocol, FPC_SENSOR_INIT, NULL)); if (rc) goto out;
    initialized=true;
    rc=command("sensor_sleep", fpc_sensor(&protocol, FPC_SENSOR_DEEP_SLEEP, NULL)); if (rc) goto out;
    initialized=false;
    rc=auth_backend_open(&backend, &cancelled);
    printf("lab_backend_status=%d\n",rc); fflush(stdout); if (rc) goto out;
    if (cancelled) { rc=-ECANCELED; goto out; }
    fpc_keymaster_key_request(request);
    rc=fpc_qsee_exchange(&backend.session, request, sizeof request, response, sizeof response, NULL, 0, 0);
    if (rc) goto out;
    const void *blob=NULL; size_t length=0;
    rc=fpc_keymaster_key_response(response, sizeof response, &blob, &length); if (rc) goto out;
    rc=command("wrapped_key_import", fpc_auth_import_key(&protocol, blob, length));
    explicit_bzero(response, sizeof response); if (rc) goto out;
    rc=command("enrollment_challenge", fpc_auth_challenge(&protocol, true, &challenge));
    if (rc) goto out;
    if (!challenge) { rc=-EPROTO; goto out; }
    if (cancelled) { rc=-ECANCELED; goto out; }
    struct sargo_gk_result r=sargo_gk_verify(&backend.gk, c.gatekeeper_uid, challenge,
        c.handle, sizeof c.handle, c.secret, sizeof c.secret, hat);
    printf("lab_verify transport=%d secure_status=%d\n",r.transport,r.status); fflush(stdout);
    rc=auth_backend_status(r); if (rc) goto out;
    puts("lab_hat validated_length=69 challenge_bound=true handle_sid_bound=true password_type=true");
    rc=command("fpc_authorize", fpc_auth_authorize_enrol(&protocol, hat));
out:
    explicit_bzero(hat, sizeof hat);
    explicit_bzero(response, sizeof response);
    explicit_bzero(request, sizeof request);
    auth_credential_clear(&c);
    auth_backend_close(&backend);
    if (initialized && command("sensor_cleanup", fpc_sensor(&protocol, FPC_SENSOR_DEEP_SLEEP, NULL)) && !rc) rc=-EIO;
    fpc_qsee_close(&fpc); fpc_sensor_close(&sensor);
    if (receipt >= 0) close(receipt);
    return rc;
}
int main(int argc, char **argv)
{
    if (getuid() || geteuid() || argc != 2 || strcmp(argv[1], "verify-retained-lab-credential") ||
        prctl(PR_SET_DUMPABLE, 0)) return 2;
    char line[8192]; FILE *f=fopen("/proc/cmdline", "re"); if (!f) return 2;
    bool allowed=fgets(line, sizeof line, f) && (strchr(line, '\n') || feof(f)) && identity(line);
    fclose(f); if (!allowed) return 2;
    struct sigaction action={.sa_handler=stop}; sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT,&action,NULL) || sigaction(SIGTERM,&action,NULL)) return 1;
    struct auth_store store={.directory=-1,.lock=-1};
    int rc=auth_store_open(&store); if (!rc) rc=authorization_once(&store);
    auth_store_close(&store);
    printf("lab_authorization_result=%d\n",rc);
    return rc ? 1 : 0;
}
