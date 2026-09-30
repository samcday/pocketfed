/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _DEFAULT_SOURCE
#include "auth-backend.h"
#include <errno.h>
#include <string.h>

static int exchange(void *context, const void *request, size_t request_len,
                     void *response, size_t response_len)
{
    struct auth_backend *backend = context;
    if (!backend || !backend->session.opened || !request || !response ||
        request_len < SARGO_KM_GET_VERSION_REQUEST_SIZE ||
        request_len >= SARGO_GK_BUFFER_SIZE ||
        response_len != SARGO_GK_BUFFER_SIZE - request_len)
        return -EINVAL;
    if (backend->stopping && *backend->stopping)
        return -ECANCELED;
    /* The kernel reconstructs the contiguous stock 0xa000-byte split from
     * these two exact memref lengths. Its local offset may be aligned. */
    return fpc_qsee_exchange(&backend->session, request, request_len,
                             response, response_len, NULL, 0, 0);
}

int auth_backend_status(struct sargo_gk_result result)
{
    if (result.transport)
        return result.transport < 0 ? result.transport : -EIO;
    if (result.status > 0)
        return -EAGAIN; /* Secure throttling is never automatically retried. */
    return result.status < 0 ? -EACCES : 0;
}

void auth_backend_close(struct auth_backend *backend)
{
    if (!backend)
        return;
    fpc_qsee_close(&backend->session);
    explicit_bzero(&backend->gk, sizeof(backend->gk));
    backend->stopping = NULL;
}

int auth_backend_open(struct auth_backend *backend,
                      const volatile sig_atomic_t *stopping)
{
    struct sargo_km_version version = {0};
    int rc;
    if (!backend)
        return -EINVAL;
    if (backend->session.opened)
        return -EBUSY;
    explicit_bzero(&backend->gk, sizeof(backend->gk));
    backend->stopping = stopping;
    if (stopping && *stopping) {
        rc = -ECANCELED;
        goto fail;
    }
    rc = fpc_qsee_open(&backend->session, "keymaster64");
    if (rc)
        goto fail;
    backend->gk.context = backend;
    backend->gk.exchange = exchange;
    rc = auth_backend_status(sargo_km_negotiate(&backend->gk, &version));
    explicit_bzero(&version, sizeof(version));
    if (rc)
        goto fail;
    return 0;
fail:
    auth_backend_close(backend);
    return rc;
}
