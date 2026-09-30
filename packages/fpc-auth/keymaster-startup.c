/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _DEFAULT_SOURCE
#include "auth-backend.h"
#include "protocol.h"
#include "qsee-transport.h"
#include <errno.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

static volatile sig_atomic_t stopping;
static void stop(int signal_number) { (void)signal_number; stopping = 1; }

static int exchange(struct fpc_qsee_session *session, unsigned char *buffer,
                    size_t request_len, const char *label)
{
    if (stopping) return -ECANCELED;
    unsigned char *response = buffer + request_len;
    size_t response_len = SARGO_GK_BUFFER_SIZE - request_len;
    memset(response, 0, response_len);
    fpc_put_le32(response, UINT32_MAX);
    int rc = fpc_qsee_exchange(session, buffer, request_len, response,
                               response_len, NULL, 0, 0);
    printf("%s transport=%d", label, rc);
    if (!rc) {
        rc = (int32_t)fpc_get_le32(response);
        printf(" status=%d", rc);
    }
    puts(""); fflush(stdout);
    return rc;
}

static int wrapped_key(struct fpc_qsee_session *session, bool *uninitialized)
{
    if (uninitialized) *uninitialized = false;
    unsigned char request[64], response[960] = {0};
    fpc_keymaster_key_request(request);
    int rc = stopping ? -ECANCELED : fpc_qsee_exchange(session, request, sizeof request,
                                     response, sizeof response, NULL, 0, 0);
    printf("wrapped_key transport=%d", rc);
    if (!rc) {
        rc = (int32_t)fpc_get_le32(response);
        if (uninitialized && rc == -24) *uninitialized = true;
        printf(" status=%d", rc);
        if (!rc) {
            const void *blob; size_t length;
            rc = fpc_keymaster_key_response(response, sizeof response, &blob, &length);
            printf(" codec_status=%d validated_blob_length=%zu", rc, length);
        }
    }
    puts(""); fflush(stdout);
    explicit_bzero(request, sizeof request);
    explicit_bzero(response, sizeof response);
    return rc;
}

/* Idempotence is established by the resident TA's valid wrapped-key reply.
 * Only a real secure status -24 permits HMAC initialization. A transport error
 * with the same numeric value is not permission to derive a new key.
 */
static int initialize(void)
{
    struct auth_backend backend = AUTH_BACKEND_INIT;
    struct fpc_qsee_session *session = &backend.session;
    unsigned char buffer[SARGO_GK_BUFFER_SIZE] = {0}, params[64] = {0};
    int rc = auth_backend_open(&backend, &stopping);
    if (rc) goto out;
    /* Only bootstrap the positively observed uninitialized HMAC state. */
    bool uninitialized = false;
    rc = wrapped_key(session, &uninitialized);
    if (!uninitialized) {
        if (!rc) puts("hmac_state=already-ready");
        goto out;
    }
    explicit_bzero(buffer, sizeof buffer);
    fpc_put_le32(buffer, 0x20e);
    rc = exchange(session, buffer, 4, "get_hmac_parameters");
    if (rc) goto out;
    memcpy(params, buffer + 8, sizeof params);
    unsigned int present = 0;
    for (size_t i = 0; i < sizeof params; ++i) present |= params[i];
    if (!present) { rc = -EPROTO; goto out; }
    explicit_bzero(buffer, sizeof buffer);
    fpc_put_le32(buffer, 0x20f);
    fpc_put_le32(buffer + 4, 12); /* offset from request start */
    fpc_put_le32(buffer + 8, 1);  /* one 64-byte participant, from this TA */
    memcpy(buffer + 12, params, sizeof params);
    rc = exchange(session, buffer, 76, "compute_shared_hmac");
    if (rc) goto out;
    present = 0;
    for (size_t i = 0; i < 32; ++i) present |= buffer[80 + i];
    if (!present) { rc = -EPROTO; goto out; }
    puts("sharing_check_length=32 participants=1");
    rc = wrapped_key(session, NULL);
out:
    explicit_bzero(buffer, sizeof buffer);
    explicit_bzero(params, sizeof params);
    auth_backend_close(&backend);
    printf("initialization_status=%d\n", rc);
    return rc;
}

int main(int argc, char **argv)
{
    if (argc == 2 && !strcmp(argv[1], "--help")) {
        puts("Usage: pocketfed-keymaster-startup --initialize-single-participant");
        return 0;
    }
    if (argc != 2 || strcmp(argv[1], "--initialize-single-participant") || geteuid()) {
        fputs("Requires root and --initialize-single-participant.\n", stderr);
        return 2;
    }
    struct sigaction action = {.sa_handler = stop};
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL))
        return 1;
    return initialize() ? 1 : 0;
}
