/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
#include <stdint.h>
#include <sys/types.h>

#define FPC_AUTH_STATE_PATH "/var/lib/pocketfed-fpc-auth"
#define FPC_AUTH_SECRET_SIZE 64u
#define FPC_AUTH_HANDLE_SIZE 58u

/* Positive commit result: the completed credential and its directory entry are
 * durable, but intent removal failed or its durability could not be confirmed.
 * The credential MUST NOT be enrolled again. Preserve state for recovery.
 */
#define AUTH_STORE_COMMITTED_CLEANUP_PENDING 1

struct auth_store {
    int directory;
    int lock;
    uid_t owner;
    gid_t group;
};

struct auth_credential {
    uint32_t linux_uid;
    uint32_t gatekeeper_uid;
    unsigned char secret[FPC_AUTH_SECRET_SIZE];
    unsigned char handle[FPC_AUTH_HANDLE_SIZE];
};

/* Fixed, root-owned state directory; holds an exclusive nonblocking flock.
 * The broker and provisioning CLI must use the same lock for each transaction.
 */
int auth_store_open(struct auth_store *store);
void auth_store_close(struct auth_store *store);
int auth_store_load(struct auth_store *store, uint32_t uid,
                    struct auth_credential *credential);
int auth_store_check_new(struct auth_store *store, uint32_t uid);

/* begin generates a random service credential and durably writes an exclusive
 * intent BEFORE any enrollment command. Neither call ever replaces a file.
 * Negative begin/commit failures retain an intent or partial credential: stop
 * and require explicit recovery. A positive commit result means durable success
 * with cleanup pending, as defined above. There is no separate cleanup API.
 */
int auth_store_begin(struct auth_store *store, uint32_t uid,
                     struct auth_credential *credential);
int auth_store_commit(struct auth_store *store,
                      const struct auth_credential *credential);
void auth_credential_clear(struct auth_credential *credential);

#ifdef FPC_AUTH_TESTING
/* Test builds only: final-directory checks remain enabled. Production exposes
 * no configurable path, ownership override, or relaxed ancestor traversal.
 */
int auth_store_open_test(struct auth_store *store, const char *path,
                         uid_t owner, gid_t group);
#endif
