/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "protocol.h"
#include <errno.h>
#include <limits.h>
#include <stdlib.h>
#include <string.h>

uint32_t fpc_get_le32(const void *src)
{
    const uint8_t *p = src;
    return (uint32_t)p[0] | (uint32_t)p[1] << 8 |
           (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}
uint64_t fpc_get_le64(const void *src)
{
    const uint8_t *p = src;
    return fpc_get_le32(p) | (uint64_t)fpc_get_le32(p + 4) << 32;
}
void fpc_put_le32(void *dst, uint32_t value)
{
    uint8_t *p = dst;
    for (unsigned i = 0; i != 4; ++i) p[i] = (uint8_t)(value >> (8 * i));
}
void fpc_put_le64(void *dst, uint64_t value)
{
    uint8_t *p = dst;
    fpc_put_le32(p, (uint32_t)value);
    fpc_put_le32(p + 4, (uint32_t)(value >> 32));
}
static void wipe(void *ptr, size_t len)
{
    volatile uint8_t *p = ptr;
    while (len--) *p++ = 0;
}
static struct fpc_result invalid(int error)
{
    return (struct fpc_result){error, INT32_MIN, INT32_MIN};
}
bool fpc_result_ok(struct fpc_result r)
{
    return r.transport == 0 && r.outer == 0 && r.command == 0;
}
bool fpc_identify_matched(const struct fpc_identify_result *r)
{
    return r && fpc_result_ok(r->result) && r->template_id != 0 &&
           r->decision == 1;
}
int fpc_outer_encode(void *request, size_t capacity, uint32_t len, uint64_t pa)
{
    if (!request || capacity < FPC_QSEE_OUTER_SIZE || len < 12 ||
        len > FPC_QSEE_MAX_AUX_SIZE) return -EINVAL;
    memset(request, 0, FPC_QSEE_OUTER_SIZE);
    fpc_put_le32(request, len);
    fpc_put_le64((uint8_t *)request + FPC_QSEE_AUX_POINTER_OFFSET, pa);
    return 0;
}
static void init(uint8_t *b, size_t len, uint32_t target, uint32_t command)
{
    memset(b, 0, len);
    fpc_put_le32(b, target);
    fpc_put_le32(b + 4, command);
    fpc_put_le32(b + 8, (uint32_t)INT32_MIN);
}
static struct fpc_result exchange(struct fpc_protocol *p, uint8_t *b, size_t n)
{
    struct fpc_result r = invalid(-EINVAL);
    if (!p || !p->exchange || !b || n < 12) return r;
    r.transport = p->exchange(p->ctx, b, n, &r.outer);
    if (!r.transport && !r.outer) r.command = (int32_t)fpc_get_le32(b + 8);
    return r;
}
struct fpc_result fpc_sensor(struct fpc_protocol *p,
                             enum fpc_sensor_command cmd, uint32_t *detail)
{
    uint8_t b[FPC_SENSOR_COMMAND_SIZE];
    if ((unsigned)cmd > FPC_SENSOR_OTP_INFO) return invalid(-EINVAL);
    init(b, sizeof b, FPC_TARGET_SENSOR, cmd);
    struct fpc_result r = exchange(p, b, sizeof b);
    if (detail) *detail = (!r.transport && !r.outer) ? fpc_get_le32(b + 12) : 0;
    return r;
}
struct fpc_result fpc_bio(struct fpc_protocol *p, enum fpc_bio_command cmd,
                          uint32_t *parameter)
{
    uint8_t b[FPC_BIO_COMMAND_SIZE];
    if ((unsigned)cmd > FPC_BIO_GET_DB_ID || cmd == 5) return invalid(-EINVAL);
    init(b, sizeof b, FPC_TARGET_BIO, cmd);
    fpc_put_le32(b + 12, parameter ? *parameter : 0);
    struct fpc_result r = exchange(p, b, sizeof b);
    if (parameter && !r.transport && !r.outer) *parameter = fpc_get_le32(b + 12);
    return r;
}
struct fpc_result fpc_get_template_ids(struct fpc_protocol *p,
                                      uint32_t ids[FPC_MAX_TEMPLATES], uint32_t *count)
{
    uint8_t b[FPC_BIO_COMMAND_SIZE];
    if (!ids || !count) return invalid(-EINVAL);
    *count = 0;
    memset(ids, 0, FPC_MAX_TEMPLATES * sizeof *ids);
    init(b, sizeof b, FPC_TARGET_BIO, FPC_BIO_GET_TEMPLATE_IDS);
    fpc_put_le32(b + 12, FPC_MAX_TEMPLATES);
    struct fpc_result r = exchange(p, b, sizeof b);
    if (fpc_result_ok(r)) {
        uint32_t n = fpc_get_le32(b + 12);
        if (n > FPC_MAX_TEMPLATES) return invalid(-EPROTO);
        for (uint32_t i = 0; i < n; ++i) ids[i] = fpc_get_le32(b + 16 + i * 4);
        *count = n;
    }
    return r;
}
struct fpc_identify_result fpc_identify(struct fpc_protocol *p)
{
    uint8_t b[FPC_BIO_COMMAND_SIZE];
    struct fpc_identify_result result = {0};
    init(b, sizeof b, FPC_TARGET_BIO, FPC_BIO_IDENTIFY);
    result.result = exchange(p, b, sizeof b);
    if (fpc_result_ok(result.result)) {
        result.template_id = fpc_get_le32(b + 12);
        for (unsigned i = 0; i < 6; ++i)
            result.diagnostic[i] = fpc_get_le32(b + 16 + i * 4);
        result.decision = result.diagnostic[3];
    }
    return result;
}
struct fpc_result fpc_get_database_id(struct fpc_protocol *p, uint64_t *id)
{
    uint8_t b[FPC_BIO_COMMAND_SIZE];
    if (!id) return invalid(-EINVAL);
    *id = 0;
    init(b, sizeof b, FPC_TARGET_BIO, FPC_BIO_GET_DB_ID);
    struct fpc_result r = exchange(p, b, sizeof b);
    if (fpc_result_ok(r)) *id = fpc_get_le64(b + 16);
    return r;
}
static struct fpc_result payload(struct fpc_protocol *p, uint32_t target,
                                 uint32_t command, const void *data, size_t len,
                                 void *output)
{
    if ((!data && !output && len) || len > FPC_QSEE_MAX_AUX_SIZE - 16)
        return invalid(-EINVAL);
    size_t n = len + 16;
    if (n < 24) n = 24; /* Hardware-auth handler minimum. */
    uint8_t *b = calloc(1, n);
    if (!b) return invalid(-ENOMEM);
    init(b, n, target, command);
    fpc_put_le32(b + 12, (uint32_t)len);
    if (data && len) memcpy(b + 16, data, len);
    struct fpc_result r = exchange(p, b, n);
    if (output && fpc_result_ok(r)) memcpy(output, b + 16, len);
    wipe(b, n);
    free(b);
    return r;
}
struct fpc_result fpc_database_file(struct fpc_protocol *p, bool store, const char *path)
{
    if (!path || !*path) return invalid(-EINVAL);
    size_t n = strlen(path);
    if (n >= FPC_QSEE_MAX_AUX_SIZE - 16) return invalid(-ENAMETOOLONG);
    return payload(p, FPC_TARGET_FS, store ? 12 : 11, path, n + 1, NULL);
}
struct fpc_result fpc_auth_challenge(struct fpc_protocol *p, bool enrol, uint64_t *value)
{
    uint8_t b[24];
    if (!value) return invalid(-EINVAL);
    init(b, sizeof b, FPC_TARGET_AUTH,
         enrol ? FPC_AUTH_GET_ENROL_CHALLENGE : FPC_AUTH_SET_AUTH_CHALLENGE);
    if (!enrol) fpc_put_le64(b + 16, *value);
    struct fpc_result r = exchange(p, b, sizeof b);
    if (fpc_result_ok(r) && enrol) *value = fpc_get_le64(b + 16);
    return r;
}
struct fpc_result fpc_auth_import_key(struct fpc_protocol *p, const void *key, size_t n)
{
    if (!key || !n) return invalid(-EINVAL);
    return payload(p, FPC_TARGET_AUTH, FPC_AUTH_IMPORT_WRAPPED_KEY, key, n, NULL);
}
struct fpc_result fpc_auth_authorize_enrol(struct fpc_protocol *p, const uint8_t hat[FPC_HAT_SIZE])
{
    if (!hat) return invalid(-EINVAL);
    return payload(p, FPC_TARGET_AUTH, FPC_AUTH_AUTHORIZE_ENROL, hat, FPC_HAT_SIZE, NULL);
}
struct fpc_result fpc_auth_get_result(struct fpc_protocol *p, uint8_t hat[FPC_HAT_SIZE])
{
    if (!hat) return invalid(-EINVAL);
    memset(hat, 0, FPC_HAT_SIZE);
    return payload(p, FPC_TARGET_AUTH, FPC_AUTH_GET_AUTH_RESULT, NULL, FPC_HAT_SIZE, hat);
}
struct fpc_result fpc_auth_enrol_timeout(struct fpc_protocol *p, uint32_t seconds, bool start)
{
    uint8_t b[24];
    init(b, sizeof b, FPC_TARGET_AUTH, FPC_AUTH_CHECK_ENROL_TIMEOUT);
    fpc_put_le32(b + 12, seconds);
    b[16] = start;
    fpc_put_le32(b + 20, (uint32_t)INT32_MIN);
    struct fpc_result r = exchange(p, b, sizeof b);
    /* Unlike other commands, this handler writes the result at offset20. */
    if (!r.transport && !r.outer) r.command = (int32_t)fpc_get_le32(b + 20);
    return r;
}
void fpc_keymaster_key_request(uint8_t b[FPC_QSEE_OUTER_SIZE])
{
    memset(b, 0, FPC_QSEE_OUTER_SIZE);
    fpc_put_le32(b, 0x205);
    fpc_put_le32(b + 4, 2);
}
int fpc_keymaster_key_response(const void *response, size_t n,
                               const void **key, size_t *len)
{
    const uint8_t *b = response;
    if (key) *key = NULL;
    if (len) *len = 0;
    if (!b || !key || !len || n < 12) return -EINVAL;
    if (fpc_get_le32(b)) return -EACCES;
    uint32_t offset = fpc_get_le32(b + 4), size = fpc_get_le32(b + 8);
    if (offset < 12 || !size || offset > n || size > n - offset) return -EPROTO;
    *key = b + offset;
    *len = size;
    return 0;
}
