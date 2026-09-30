/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
#include "gatekeeper-protocol.h"
#include "qsee-transport.h"
#include <signal.h>

struct auth_backend {
    struct fpc_qsee_session session;
    struct sargo_gk gk;
    const volatile sig_atomic_t *stopping;
};
#define AUTH_BACKEND_INIT { .session = FPC_QSEE_SESSION_INIT }

/* Attaches only to resident keymaster64, validates its version and performs
 * the recovered stock handshake. No firmware loading or credential mutation.
 * One synchronous caller owns this object; close only after calls return.
 * SET_VERSION success cannot read back or replace prior TA configuration.
 */
int auth_backend_open(struct auth_backend *backend,
                      const volatile sig_atomic_t *stopping);
void auth_backend_close(struct auth_backend *backend);
int auth_backend_status(struct sargo_gk_result result);
