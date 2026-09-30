/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Controlled live diagnostic: production codec/transport; no credentials. */
#include "gatekeeper-protocol.h"
#include "qsee-transport.h"
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>

static volatile sig_atomic_t stopping;
static void stop(int signal_number) { (void)signal_number; stopping = 1; }

static int exchange(void *context, const void *request, size_t request_len,
                    void *response, size_t response_len)
{
    if (stopping) return -ECANCELED;
    int rc = fpc_qsee_exchange(context, request, request_len, response,
                               response_len, NULL, 0, 0);
    if (rc) {
        printf("exchange request_length=%zu transport=%d\n", request_len, rc);
    } else if (request_len == SARGO_KM_GET_VERSION_REQUEST_SIZE) {
        struct sargo_km_version v;
        struct sargo_gk_result r = sargo_km_get_version_response(response, response_len, &v);
        printf("get_version transport=%d status=%d version=%u,%u,%u,%u\n",
               r.transport, r.status, v.ta_api_major, v.ta_api_minor, v.ta_major, v.ta_minor);
    } else {
        struct sargo_gk_result r = sargo_km_set_version_response(response, response_len);
        printf("set_version transport=%d status=%d\n", r.transport, r.status);
    }
    fflush(stdout);
    return rc;
}

int main(int argc, char **argv)
{
    if (argc != 2 || strcmp(argv[1], "--negotiate")) {
        fputs("Usage: keymaster-negotiate --negotiate\n", stderr);
        return 2;
    }
    struct sigaction action = { .sa_handler = stop };
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL)) return 1;
    struct fpc_qsee_session session = FPC_QSEE_SESSION_INIT;
    int rc = fpc_qsee_open(&session, "keymaster64");
    if (rc) { printf("attach transport=%d\n", rc); return 1; }
    struct sargo_gk gk = { .context = &session, .exchange = exchange };
    struct sargo_km_version version;
    struct sargo_gk_result result = sargo_km_negotiate(&gk, &version);
    fpc_qsee_close(&session);
    printf("negotiation transport=%d status=%d\n", result.transport, result.status);
    return result.transport || result.status ? 1 : 0;
}
