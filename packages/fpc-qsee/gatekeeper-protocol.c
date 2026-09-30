/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _DEFAULT_SOURCE
#include "gatekeeper-protocol.h"

#include <endian.h>
#include <errno.h>
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#define GK_ENROLL 0x1001u
#define GK_VERIFY 0x1002u
#define GK_HEADER_SIZE 32u
#define GK_REPLY_SIZE 12u

static void put32(void *p, uint32_t value)
{
    value = htole32(value);
    memcpy(p, &value, sizeof(value));
}

static void put64(void *p, uint64_t value)
{
    value = htole64(value);
    memcpy(p, &value, sizeof(value));
}

static uint32_t get32(const void *p)
{
    uint32_t value;
    memcpy(&value, p, sizeof(value));
    return le32toh(value);
}

static uint64_t get64(const void *p)
{
    uint64_t value;
    memcpy(&value, p, sizeof(value));
    return le64toh(value);
}

void sargo_km_get_version_request(unsigned char request[SARGO_KM_GET_VERSION_REQUEST_SIZE])
{
    put32(request, 0x200u);
}

void sargo_km_set_version_request(unsigned char request[SARGO_KM_SET_VERSION_REQUEST_SIZE])
{
    static const uint32_t words[] = { 0x207u, 4u, 5u, 4u, 5u, 0u };
    for (size_t i = 0; i < sizeof(words) / sizeof(words[0]); ++i)
        put32(request + 4u * i, words[i]);
}

static struct sargo_gk_result version_status(const void *response, size_t length)
{
    struct sargo_gk_result result = { .transport = -EINVAL, .status = -1 };
    if (!response)
        return result;
    if (length < sizeof(uint32_t)) {
        result.transport = -EPROTO;
        return result;
    }
    result.transport = 0;
    result.status = (int32_t)get32(response);
    return result;
}

struct sargo_gk_result sargo_km_get_version_response(const void *response,
    size_t length, struct sargo_km_version *version)
{
    struct sargo_gk_result result = { .transport = -EINVAL, .status = -1 };
    const unsigned char *bytes = response;
    if (!version)
        return result;
    memset(version, 0, sizeof(*version));
    result = version_status(response, length);
    if (result.transport || result.status)
        return result;
    if (length < SARGO_KM_GET_VERSION_RESPONSE_SIZE) {
        result.transport = -EPROTO;
        return result;
    }
    version->ta_api_major = get32(bytes + 4);
    version->ta_api_minor = get32(bytes + 8);
    version->ta_major = get32(bytes + 12);
    version->ta_minor = get32(bytes + 16);
    return result;
}

struct sargo_gk_result sargo_km_set_version_response(const void *response,
    size_t length)
{
    return version_status(response, length);
}

int sargo_gk_uid_for_linux(uint32_t linux_uid, uint32_t *gatekeeper_uid)
{
    if (!gatekeeper_uid || linux_uid > SARGO_GK_MAX_LINUX_UID)
        return -EINVAL;
    *gatekeeper_uid = SARGO_GK_NATIVE_UID_BASE + linux_uid;
    return 0;
}

static bool native_uid(uint32_t uid)
{
    return (uid & ~SARGO_GK_MAX_LINUX_UID) == SARGO_GK_NATIVE_UID_BASE;
}

static bool valid_client(struct sargo_gk *gk, const void *password, size_t length)
{
    return gk && gk->exchange && password && length &&
           length <= SARGO_GK_MAX_PASSWORD;
}

/* Headers use offsets relative to their respective request/response buffers.
 * The HAL reserves one 0xa000-byte QSEECOM buffer, partitioned at the unpadded
 * request length. Use the same lengths even though TEE provides two memrefs.
 */
static struct sargo_gk_result transact(struct sargo_gk *gk,
    unsigned char *request, size_t request_len,
    unsigned char *response, const unsigned char **blob, size_t *blob_len)
{
    struct sargo_gk_result result = { .transport = -EINVAL, .status = -1 };
    size_t response_len = SARGO_GK_BUFFER_SIZE - request_len;
    uint32_t offset, length;

    *blob = NULL;
    *blob_len = 0;
    memset(response, 0, response_len);
    put32(response, UINT32_MAX);
    result.transport = gk->exchange(gk->context, request, request_len,
                                     response, response_len);
    if (result.transport)
        return result;
    result.status = (int32_t)get32(response);
    if (result.status)
        return result;
    offset = get32(response + 4);
    length = get32(response + 8);
    if (offset < GK_REPLY_SIZE || offset > response_len || !length ||
        length > response_len - offset) {
        result.transport = -EPROTO;
        return result;
    }
    *blob = response + offset;
    *blob_len = length;
    return result;
}

static void free_sensitive(void *p)
{
    if (p) {
        explicit_bzero(p, SARGO_GK_BUFFER_SIZE);
        free(p);
    }
}

struct sargo_gk_result sargo_km_negotiate(struct sargo_gk *gk,
    struct sargo_km_version *version)
{
    struct sargo_gk_result result = { .transport = -EINVAL, .status = -1 };
    struct sargo_km_version decoded;
    unsigned char *buffer;
    size_t request_len = SARGO_KM_GET_VERSION_REQUEST_SIZE;

    if (version)
        memset(version, 0, sizeof(*version));
    if (!gk || !gk->exchange || !version)
        return result;
    buffer = calloc(1, SARGO_GK_BUFFER_SIZE);
    if (!buffer) {
        result.transport = -ENOMEM;
        return result;
    }
    sargo_km_get_version_request(buffer);
    /* Detect a callback leaving caller output untouched. This is not a TA-write
     * detector: a transport that zero-fills its own staging can overwrite it. */
    put32(buffer + request_len, UINT32_MAX);
    result.transport = gk->exchange(gk->context, buffer, request_len,
        buffer + request_len, SARGO_GK_BUFFER_SIZE - request_len);
    if (result.transport)
        goto out;
    result = sargo_km_get_version_response(buffer + request_len,
        SARGO_GK_BUFFER_SIZE - request_len, &decoded);
    if (result.transport || result.status)
        goto out;
    if (decoded.ta_api_major != 4u || decoded.ta_api_minor != 0u ||
        decoded.ta_major != 4u || decoded.ta_minor != 165u) {
        result.transport = -EPROTO;
        goto out;
    }
    memset(buffer, 0, SARGO_GK_BUFFER_SIZE);
    request_len = SARGO_KM_SET_VERSION_REQUEST_SIZE;
    sargo_km_set_version_request(buffer);
    put32(buffer + request_len, UINT32_MAX);
    result.status = -1;
    result.transport = gk->exchange(gk->context, buffer, request_len,
        buffer + request_len, SARGO_GK_BUFFER_SIZE - request_len);
    if (result.transport)
        goto out;
    result = sargo_km_set_version_response(buffer + request_len,
        SARGO_GK_BUFFER_SIZE - request_len);
    if (!result.transport && !result.status)
        *version = decoded;
out:
    free_sensitive(buffer);
    return result;
}

struct sargo_gk_result sargo_gk_enroll_new(struct sargo_gk *gk, uint32_t uid,
    const void *password, size_t password_len,
    void *handle, size_t capacity, size_t *handle_len)
{
    struct sargo_gk_result result = { .transport = -EINVAL, .status = -1 };
    unsigned char *request = NULL, *response = NULL;
    const unsigned char *blob;
    size_t length, request_len;

    if (handle_len)
        *handle_len = 0;
    if (!native_uid(uid) || !valid_client(gk, password, password_len) || !handle ||
        capacity < SARGO_GK_HANDLE_SIZE ||
        capacity > SARGO_GK_MAX_HANDLE || !handle_len)
        return result;
    explicit_bzero(handle, capacity);
    request = calloc(1, SARGO_GK_BUFFER_SIZE);
    response = calloc(1, SARGO_GK_BUFFER_SIZE);
    if (!request || !response) {
        result.transport = -ENOMEM;
        goto out;
    }
    request_len = GK_HEADER_SIZE + password_len;
    put32(request, GK_ENROLL);
    put32(request + 4, uid);
    /* Old handle/password offset-length pairs intentionally remain zero. */
    put32(request + 24, GK_HEADER_SIZE);
    put32(request + 28, (uint32_t)password_len);
    memcpy(request + GK_HEADER_SIZE, password, password_len);
    result = transact(gk, request, request_len, response, &blob, &length);
    if (!result.transport && !result.status) {
        if (length != SARGO_GK_HANDLE_SIZE || !get64(blob + 1))
            result.transport = -EPROTO;
        else if (length > capacity)
            result.transport = -EOVERFLOW;
        else {
            memcpy(handle, blob, length);
            *handle_len = length;
        }
    }
out:
    free_sensitive(request);
    free_sensitive(response);
    return result;
}

int sargo_gk_check_token(const unsigned char token[SARGO_GK_HAT_SIZE],
                         uint64_t challenge)
{
    uint32_t type;
    if (!token || !challenge || token[0] || get64(token + 1) != challenge ||
        !get64(token + 9))
        return -EPROTO;
    memcpy(&type, token + 25, sizeof(type));
    if (be32toh(type) != 1u) /* HW_AUTH_PASSWORD */
        return -EPROTO;
    return 0;
}

struct sargo_gk_result sargo_gk_verify(struct sargo_gk *gk, uint32_t uid,
    uint64_t challenge, const void *handle, size_t handle_len,
    const void *password, size_t password_len,
    unsigned char token[SARGO_GK_HAT_SIZE])
{
    struct sargo_gk_result result = { .transport = -EINVAL, .status = -1 };
    unsigned char *request = NULL, *response = NULL;
    const unsigned char *blob;
    size_t length, password_offset, request_len;

    if (token)
        explicit_bzero(token, SARGO_GK_HAT_SIZE);
    if (!native_uid(uid) || !valid_client(gk, password, password_len) || !handle ||
        handle_len != SARGO_GK_HANDLE_SIZE || !token || !challenge)
        return result;
    request = calloc(1, SARGO_GK_BUFFER_SIZE);
    response = calloc(1, SARGO_GK_BUFFER_SIZE);
    if (!request || !response) {
        result.transport = -ENOMEM;
        goto out;
    }
    password_offset = GK_HEADER_SIZE + handle_len;
    request_len = password_offset + password_len;
    put32(request, GK_VERIFY);
    put32(request + 4, uid);
    put64(request + 8, challenge);
    put32(request + 16, GK_HEADER_SIZE);
    put32(request + 20, (uint32_t)handle_len);
    put32(request + 24, (uint32_t)password_offset);
    put32(request + 28, (uint32_t)password_len);
    memcpy(request + GK_HEADER_SIZE, handle, handle_len);
    memcpy(request + password_offset, password, password_len);
    result = transact(gk, request, request_len, response, &blob, &length);
    if (!result.transport && !result.status) {
        if (length != SARGO_GK_HAT_SIZE || get64(blob + 9) != get64((const unsigned char *)handle + 1))
            result.transport = -EPROTO;
        else if ((result.transport = sargo_gk_check_token(blob, challenge)) == 0)
            memcpy(token, blob, SARGO_GK_HAT_SIZE);
    }
out:
    free_sensitive(request);
    free_sensitive(response);
    return result;
}
