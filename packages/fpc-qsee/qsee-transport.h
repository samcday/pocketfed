/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

/* Initialize with FPC_QSEE_SESSION_INIT or all zeroes. One caller at a time.
 * Close only after all exchanges have completed. Reopening requires a close.
 */
struct fpc_qsee_session {
    int fd;
    uint32_t id;
    bool opened;
};
#define FPC_QSEE_SESSION_INIT { .fd = -1, .id = 0, .opened = false }

/* Attaches to an already loaded app through the non-privileged TEE node. */
int fpc_qsee_open(struct fpc_qsee_session *session, const char *app_name);
void fpc_qsee_close(struct fpc_qsee_session *session);

/* Raw request/response for the legacy QSEECOM TEE backend. Negative errno.
 * auxiliary == NULL selects a plain exchange, e.g. the keymaster key export.
 * Otherwise, the kernel patches an unaligned LE64 address at pointer_offset.
 * The caller owns the application-specific request and response formats.
 */
int fpc_qsee_exchange(struct fpc_qsee_session *session,
                      const void *request, size_t request_len,
                      void *response, size_t response_len,
                      void *auxiliary, size_t auxiliary_len,
                      uint32_t pointer_offset);

/* Stock Sargo FPC wrapper: 64-byte request/response, LE32 auxiliary size and
 * LE64 auxiliary address at byte 4. It rounds the command buffer to 4096.
 * outer_status is distinct from the command status inside the auxiliary data.
 */
int fpc_qsee_command(void *context, void *command, size_t command_len,
                     int32_t *outer_status);
