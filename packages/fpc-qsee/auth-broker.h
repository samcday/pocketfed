/* SPDX-License-Identifier: LGPL-2.1-or-later */
#ifndef FPC_AUTH_BROKER_H
#define FPC_AUTH_BROKER_H
#include <stdint.h>

#define FPC_AUTH_SOCKET_PATH "/run/pocketfed-fpc-auth/token.sock"
#define FPC_AUTH_MAGIC "FPCA"
#define FPC_AUTH_VERSION 1u
#define FPC_AUTH_TIMEOUT_MS 5000u
#define FPC_AUTH_TOKEN_SIZE 69u

/* One request/response per SOCK_STREAM connection, no native struct padding.
 * All integer arrays encode little endian. Only uid0 peers are accepted by
 * the client; the broker must restrict the socket to authorized root clients.
 * status is signed errno-style: zero success, nonzero failure. A failed
 * response must contain zero token bytes. Tokens and messages are never logged.
 */
struct fpc_auth_request {
    uint8_t magic[4];
    uint8_t version_le[4];
    uint8_t uid_le[4];
    uint8_t challenge_le[8];
};
struct fpc_auth_response {
    uint8_t status_le[4];
    uint8_t token[FPC_AUTH_TOKEN_SIZE];
};
_Static_assert(sizeof(struct fpc_auth_request) == 20, "FPC auth request ABI");
_Static_assert(sizeof(struct fpc_auth_response) == 73, "FPC auth response ABI");
#endif
