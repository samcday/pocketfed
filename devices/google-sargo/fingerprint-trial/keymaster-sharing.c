/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _DEFAULT_SOURCE
#include "gatekeeper-protocol.h"
#include "protocol.h"
#include "qsee-transport.h"
#include <errno.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>

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

int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "--initialize-single-participant")) return 2;
    struct sigaction action = { .sa_handler = stop };
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) return 1;
    struct fpc_qsee_session session = FPC_QSEE_SESSION_INIT;
    unsigned char buffer[SARGO_GK_BUFFER_SIZE] = {0}, params[64] = {0};
    struct sargo_km_version version;
    int rc = fpc_qsee_open(&session, "keymaster64");
    if (rc) goto out;
    sargo_km_get_version_request(buffer);
    rc = exchange(&session, buffer, 4, "get_version");
    if (rc) goto out;
    struct sargo_gk_result result = sargo_km_get_version_response(buffer + 4,
        sizeof buffer - 4, &version);
    if (result.transport || result.status || version.ta_api_major != 4 ||
        version.ta_api_minor != 0 || version.ta_major != 4 || version.ta_minor != 165) {
        rc = -EPROTO; goto out;
    }
    /* Only bootstrap the positively observed uninitialized HMAC state. */
    bool uninitialized = false;
    rc = wrapped_key(&session, &uninitialized);
    if (!uninitialized) { if (!rc) rc = -EALREADY; goto out; }
    explicit_bzero(buffer, sizeof buffer);
    fpc_put_le32(buffer, 0x20e);
    rc = exchange(&session, buffer, 4, "get_hmac_parameters");
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
    rc = exchange(&session, buffer, 76, "compute_shared_hmac");
    if (rc) goto out;
    present = 0;
    for (size_t i = 0; i < 32; ++i) present |= buffer[80 + i];
    if (!present) { rc = -EPROTO; goto out; }
    puts("sharing_check_length=32 participants=1");
    rc = wrapped_key(&session, NULL);
out:
    explicit_bzero(buffer, sizeof buffer);
    explicit_bzero(params, sizeof params);
    fpc_qsee_close(&session);
    printf("initialization_status=%d\n", rc);
    return rc ? 1 : 0;
}
