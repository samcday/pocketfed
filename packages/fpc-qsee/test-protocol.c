/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "protocol.h"
#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <string.h>

struct mock {
    unsigned calls;
    uint8_t request[128];
    size_t request_len;
    int transport;
    int32_t outer, command;
    uint32_t parameter, decision;
    bool omit_reply;
};
static int mock_exchange(void *ctx, void *aux, size_t len, int32_t *outer)
{
    struct mock *m = ctx;
    uint8_t *b = aux;
    assert(len <= sizeof m->request);
    ++m->calls;
    m->request_len = len;
    memcpy(m->request, b, len);
    if (!m->omit_reply) {
        *outer = m->outer;
        fpc_put_le32(b + 8, (uint32_t)m->command);
        fpc_put_le32(b + 12, m->parameter);
        if (len >= 32) fpc_put_le32(b + 28, m->decision);
    }
    return m->transport;
}
static void wire_bytes(void)
{
    uint8_t request[64];
    static const uint8_t expected[64] = {
        0x58, 0, 0, 0, 0x88, 0x77, 0x66, 0x55,
        0x44, 0x33, 0x22, 0x11,
    };
    assert(!fpc_outer_encode(request, sizeof request, 88,
                              UINT64_C(0x1122334455667788)));
    assert(!memcmp(request, expected, sizeof request));
    assert(fpc_outer_encode(request, 63, 88, 0) == -EINVAL);
    assert(fpc_outer_encode(request, sizeof request, 11, 0) == -EINVAL);
    assert(fpc_outer_encode(request, sizeof request, FPC_QSEE_MAX_AUX_SIZE + 1, 0) == -EINVAL);

    fpc_keymaster_key_request(request);
    static const uint8_t key_request[64] = {5, 2, 0, 0, 2};
    assert(!memcmp(request, key_request, sizeof request));

    struct mock m = {0};
    struct fpc_protocol p = {&m, mock_exchange};
    assert(fpc_result_ok(fpc_sensor(&p, FPC_SENSOR_WAKEUP_SETUP, NULL)));
    static const uint8_t sensor_request[88] = {10, 0, 0, 0, 3, 0, 0, 0, 0, 0, 0, 0x80};
    assert(m.request_len == sizeof sensor_request);
    assert(!memcmp(m.request, sensor_request, sizeof sensor_request));
    uint64_t challenge = UINT64_C(0x0123456789abcdef);
    assert(fpc_result_ok(fpc_auth_challenge(&p, false, &challenge)));
    static const uint8_t auth_request[24] = {
        3, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0x80, 0, 0, 0, 0,
        0xef, 0xcd, 0xab, 0x89, 0x67, 0x45, 0x23, 0x01,
    };
    assert(m.request_len == sizeof auth_request);
    assert(!memcmp(m.request, auth_request, sizeof auth_request));
}
static void match_requires_valid_reply(void)
{
    struct mock m = {.parameter = 42, .decision = 1};
    struct fpc_protocol p = {&m, mock_exchange};
    struct fpc_identify_result r = fpc_identify(&p);
    assert(fpc_identify_matched(&r));
    m.transport = -EIO;
    r = fpc_identify(&p);
    assert(!fpc_identify_matched(&r) && r.template_id == 0);
    m.transport = 0;
    m.outer = -201;
    r = fpc_identify(&p);
    assert(!fpc_identify_matched(&r) && r.result.command == INT32_MIN);
    m.outer = 0;
    m.command = -212;
    r = fpc_identify(&p);
    assert(!fpc_identify_matched(&r) && r.template_id == 0);
    m.command = 0x107;
    r = fpc_identify(&p);
    assert(!fpc_identify_matched(&r));
    m.command = 0;
    m.parameter = 0;
    r = fpc_identify(&p);
    assert(!fpc_identify_matched(&r));
    m.parameter = 42;
    for (unsigned d = 0; d <= 2; d += 2) {
        m.decision = d;
        r = fpc_identify(&p);
        assert(!fpc_identify_matched(&r));
    }
    m.omit_reply = true;
    r = fpc_identify(&p);
    assert(!fpc_identify_matched(&r));
    r = fpc_identify(NULL);
    assert(!fpc_identify_matched(&r));
    assert(!fpc_identify_matched(NULL));
}
static void reply_bounds(void)
{
    uint8_t response[32] = {0};
    const void *key = response;
    size_t n = 99;
    fpc_put_le32(response + 4, 12);
    fpc_put_le32(response + 8, 20);
    assert(!fpc_keymaster_key_response(response, sizeof response, &key, &n));
    assert(key == response + 12 && n == 20);
    static const uint32_t bad[][2] = {
        {0, 1}, {11, 1}, {12, 0}, {12, 21}, {32, 1},
        {33, 1}, {UINT32_MAX, 2}, {12, UINT32_MAX},
    };
    for (size_t i = 0; i < sizeof bad / sizeof *bad; ++i) {
        fpc_put_le32(response + 4, bad[i][0]);
        fpc_put_le32(response + 8, bad[i][1]);
        key = response;
        n = 99;
        assert(fpc_keymaster_key_response(response, sizeof response, &key, &n) == -EPROTO);
        assert(key == NULL && n == 0);
    }
    key = response;
    n = 99;
    assert(fpc_keymaster_key_response(response, 11, &key, &n) == -EINVAL);
    assert(key == NULL && n == 0);
    fpc_put_le32(response, (uint32_t)-30);
    assert(fpc_keymaster_key_response(response, sizeof response, &key, &n) == -EACCES);
    assert(key == NULL && n == 0);

    struct mock m = {.parameter = FPC_MAX_TEMPLATES + 1};
    struct fpc_protocol p = {&m, mock_exchange};
    uint32_t ids[FPC_MAX_TEMPLATES], count = 99;
    memset(ids, 0xff, sizeof ids);
    assert(fpc_get_template_ids(&p, ids, &count).transport == -EPROTO);
    assert(count == 0);
    for (unsigned i = 0; i < FPC_MAX_TEMPLATES; ++i) assert(ids[i] == 0);
    assert(fpc_get_le32(m.request + 12) == FPC_MAX_TEMPLATES);
    m.parameter = FPC_MAX_TEMPLATES;
    assert(fpc_result_ok(fpc_get_template_ids(&p, ids, &count)));
    assert(count == FPC_MAX_TEMPLATES);
    m.outer = -201;
    assert(!fpc_result_ok(fpc_get_template_ids(&p, ids, &count)) && count == 0);
}
int main(void)
{
    wire_bytes();
    match_requires_valid_reply();
    reply_bounds();
    puts("FPC protocol wire-format and rejection tests passed");
    return 0;
}
