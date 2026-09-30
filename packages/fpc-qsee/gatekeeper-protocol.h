/* SPDX-License-Identifier: LGPL-2.1-or-later */
#pragma once
#include <stddef.h>
#include <stdint.h>

#define SARGO_GK_BUFFER_SIZE 0xa000u
#define SARGO_GK_MAX_HANDLE 4096u
#define SARGO_GK_HANDLE_SIZE 58u
#define SARGO_GK_MAX_PASSWORD 1024u
#define SARGO_GK_HAT_SIZE 69u
#define SARGO_GK_NATIVE_UID_BASE 0x70000000u
#define SARGO_GK_MAX_LINUX_UID 0x00ffffffu
#define SARGO_KM_GET_VERSION_REQUEST_SIZE 4u
#define SARGO_KM_SET_VERSION_REQUEST_SIZE 24u
#define SARGO_KM_GET_VERSION_RESPONSE_SIZE 20u

/* Application reservation outside AOSP Android 12 user/fake-user ranges.
 * The TA does not enforce this namespace or offer a safe existence query.
 * Provisioning must separately prevent replacement of an existing native ID.
 */
int sargo_gk_uid_for_linux(uint32_t linux_uid, uint32_t *gatekeeper_uid);

/* Stock Sargo Gatekeeper HAL, not the later Qualcomm CBOR protocol.
 * exchange returns negative errno; the secure application's status is separate.
 * A caller must establish/validate the keymaster transport before these calls.
 */
struct sargo_gk {
    void *context;
    int (*exchange)(void *context, const void *request, size_t request_len,
                    void *response, size_t response_len);
};

struct sargo_gk_result {
    int transport;
    int32_t status;
};

struct sargo_km_version {
    uint32_t ta_api_major;
    uint32_t ta_api_minor;
    uint32_t ta_major;
    uint32_t ta_minor;
};

void sargo_km_get_version_request(unsigned char request[SARGO_KM_GET_VERSION_REQUEST_SIZE]);
void sargo_km_set_version_request(unsigned char request[SARGO_KM_SET_VERSION_REQUEST_SIZE]);
struct sargo_gk_result sargo_km_get_version_response(const void *response,
    size_t response_len, struct sargo_km_version *version);
struct sargo_gk_result sargo_km_set_version_response(const void *response,
    size_t response_len);

/* Explicit, callback-only GET_VERSION/validate/SET_VERSION exchange. Does not
 * open a transport, load a TA, enroll a credential or retry. Only the exact
 * inspected TA version [4,0,4,165] permits SET_VERSION [0x207,4,5,4,5,0].
 * version is zeroed on failure. A successful call does NOT establish that the
 * TA applied these settings: SET_VERSION only takes effect once per loaded TA,
 * and subsequent calls silently retain the first configuration. GET_VERSION
 * does not read that configuration back. Callers must establish TA lifecycle
 * and readiness separately; no live backend currently calls this helper.
 */
struct sargo_gk_result sargo_km_negotiate(struct sargo_gk *gk,
    struct sargo_km_version *version);

/* New Linux-owned credentials only. This deliberately exposes no delete-all
 * or credential-replacement operation. It does not access Android handles.
 */
struct sargo_gk_result sargo_gk_enroll_new(struct sargo_gk *gk, uint32_t uid,
    const void *password, size_t password_len,
    void *handle, size_t capacity, size_t *handle_len);

struct sargo_gk_result sargo_gk_verify(struct sargo_gk *gk, uint32_t uid,
    uint64_t challenge, const void *handle, size_t handle_len,
    const void *password, size_t password_len,
    unsigned char token[SARGO_GK_HAT_SIZE]);

/* Structural checks only; the FPC TA verifies the token's HMAC. */
int sargo_gk_check_token(const unsigned char token[SARGO_GK_HAT_SIZE],
                         uint64_t challenge);
