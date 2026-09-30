/* SPDX-License-Identifier: LGPL-2.1-or-later */
#include "gatekeeper-protocol.h"
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum mode { ENROLL, VERIFY, TRANSPORT_ERROR, SECURE_ERROR, THROTTLED,
            INVALID_OFFSET, TRUNCATED, WRONG_CHALLENGE, WRONG_SID, WRONG_TYPE, EMPTY_REPLY };
static enum mode mode;
static unsigned calls;
static const unsigned char password[] = { 0x91, 0x02, 0x73, 0xf4, 0x85 };
static const unsigned char handle[SARGO_GK_HANDLE_SIZE] = {
    0, 0x28, 0x37, 0x46, 0x55, 0x64, 0x73, 0x82, 0x91
};
static const uint64_t challenge = UINT64_C(0x0102030405060708);

static void put32(unsigned char *p, uint32_t n)
{
    for (unsigned i = 0; i < 4; ++i) p[i] = n >> (8 * i);
}

static void put64(unsigned char *p, uint64_t n)
{
    for (unsigned i = 0; i < 8; ++i) p[i] = n >> (8 * i);
}

static int exchange(void *context, const void *request, size_t request_len,
                     void *reply, size_t reply_len)
{
    const unsigned char *q = request;
    unsigned char *r = reply;
    bool enrolling = mode == ENROLL;
    /* Recovered serializer shape: separate fixed 32-byte headers, 32-bit UID,
     * direct little-endian challenge and offset-length pairs. */
    const unsigned char enroll_header[32] = {
        0x01, 0x10, 0, 0, 0x12, 0x34, 0x56, 0x70,
        0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
        0x20, 0, 0, 0, 5, 0, 0, 0
    };
    const unsigned char verify_header[32] = {
        0x02, 0x10, 0, 0, 0x12, 0x34, 0x56, 0x70,
        8, 7, 6, 5, 4, 3, 2, 1,
        0x20, 0, 0, 0, 58, 0, 0, 0, 0x5a, 0, 0, 0, 5, 0, 0, 0
    };
    assert(context == &calls);
    ++calls;
    assert(request_len + reply_len == SARGO_GK_BUFFER_SIZE);
    assert(request_len == (enrolling ? 37u : 95u));
    assert(!memcmp(q, enrolling ? enroll_header : verify_header, 32));
    if (enrolling) {
        assert(!memcmp(q + 32, password, sizeof(password)));
    } else {
        assert(!memcmp(q + 32, handle, sizeof(handle)));
        assert(!memcmp(q + 90, password, sizeof(password)));
    }
    if (mode == TRANSPORT_ERROR) return -EIO;
    if (mode == EMPTY_REPLY) return 0;
    put32(r, mode == SECURE_ERROR ? (uint32_t)-30 : mode == THROTTLED ? 17u : 0u);
    put32(r + 4, mode == INVALID_OFFSET ? 4u : 12u);
    put32(r + 8, mode == TRUNCATED ? (uint32_t)reply_len :
                 enrolling ? sizeof(handle) : SARGO_GK_HAT_SIZE);
    if (enrolling) {
        memcpy(r + 12, handle, sizeof(handle));
    } else {
        r[12] = 0;
        put64(r + 13, mode == WRONG_CHALLENGE ? challenge - 1 : challenge);
        put64(r + 21, UINT64_C(0x9182736455463728) + (mode == WRONG_SID));
        r[40] = mode == WRONG_TYPE ? 2 : 1; /* BE32 password type at HAT+25 */
        memset(r + 12 + 37, 0xa5, 32); /* synthetic MAC; never used on a TA */
    }
    return 0;
}

static bool zero(const void *p, size_t n)
{
    const unsigned char *b = p;
    for (size_t i = 0; i < n; ++i) if (b[i]) return false;
    return true;
}

static const unsigned char get_version_wire[] = { 0x00, 0x02, 0, 0 };
static const unsigned char set_version_wire[] = {
    0x07, 0x02, 0, 0, 4, 0, 0, 0, 5, 0, 0, 0,
    4, 0, 0, 0, 5, 0, 0, 0, 0, 0, 0, 0
};

static void test_version_decoding(void)
{
    unsigned char request[sizeof(set_version_wire) + 1];
    unsigned char response[25] = { 0 };
    struct sargo_km_version version;
    struct sargo_gk_result result;

    memset(request, 0xa5, sizeof(request));
    sargo_km_get_version_request(request);
    assert(!memcmp(request, get_version_wire, sizeof(get_version_wire)));
    assert(request[4] == 0xa5);
    sargo_km_set_version_request(request);
    assert(!memcmp(request, set_version_wire, sizeof(set_version_wire)));
    assert(request[24] == 0xa5);

    /* Unaligned input and non-palindromic words detect host-endian/alignment
     * shortcuts. Decoding itself reports values; negotiation checks support. */
    put32(response + 5, UINT32_C(0x01020304));
    put32(response + 9, UINT32_C(0x11223344));
    put32(response + 13, UINT32_C(0x55667788));
    put32(response + 17, UINT32_C(0x91a2b3c4));
    result = sargo_km_get_version_response(response + 1, 20, &version);
    assert(!result.transport && !result.status);
    assert(version.ta_api_major == UINT32_C(0x01020304));
    assert(version.ta_api_minor == UINT32_C(0x11223344));
    assert(version.ta_major == UINT32_C(0x55667788));
    assert(version.ta_minor == UINT32_C(0x91a2b3c4));
    for (size_t n = 0; n < 20; ++n) {
        unsigned char *short_reply = calloc(n ? n : 1u, 1u);
        assert(short_reply);
        memset(&version, 0xa5, sizeof(version));
        result = sargo_km_get_version_response(short_reply, n, &version);
        assert(result.transport == -EPROTO && zero(&version, sizeof(version)));
        if (n < 4) {
            result = sargo_km_set_version_response(short_reply, n);
            assert(result.transport == -EPROTO);
        }
        free(short_reply);
    }
    result = sargo_km_get_version_response(response + 1, 24, &version);
    assert(!result.transport && !result.status); /* padded capacity is allowed */
    result = sargo_km_get_version_response(NULL, 20, &version);
    assert(result.transport == -EINVAL && zero(&version, sizeof(version)));
    result = sargo_km_get_version_response(response + 1, 20, NULL);
    assert(result.transport == -EINVAL);

    const int32_t statuses[] = { -30, 17, INT32_MIN, INT32_MAX };
    for (size_t i = 0; i < sizeof(statuses) / sizeof(statuses[0]); ++i) {
        put32(response + 1, (uint32_t)statuses[i]);
        memset(&version, 0xa5, sizeof(version));
        result = sargo_km_get_version_response(response + 1, 4, &version);
        assert(!result.transport && result.status == statuses[i]);
        assert(zero(&version, sizeof(version)));
        result = sargo_km_set_version_response(response + 1, 4);
        assert(!result.transport && result.status == statuses[i]);
    }
    put32(response + 1, 0);
    for (size_t n = 0; n < 4; ++n) {
        result = sargo_km_set_version_response(response + 1, n);
        assert(result.transport == -EPROTO);
    }
    result = sargo_km_set_version_response(response + 1, 4);
    assert(!result.transport && !result.status);
    result = sargo_km_set_version_response(response + 1, 24);
    assert(!result.transport && !result.status);
    result = sargo_km_set_version_response(NULL, 4);
    assert(result.transport == -EINVAL);
}

enum km_mode {
    KM_OK, KM_GET_IO, KM_GET_ERROR, KM_GET_THROTTLE, KM_GET_EMPTY,
    KM_BAD_API_MAJOR, KM_BAD_API_MINOR, KM_BAD_TA_MAJOR, KM_BAD_TA_MINOR,
    KM_GET_STATUS_ONLY, KM_SET_IO, KM_SET_ERROR, KM_SET_THROTTLE, KM_SET_EMPTY
};

struct km_fixture { enum km_mode mode; unsigned calls; };

static int version_exchange(void *context, const void *request, size_t request_len,
                            void *reply, size_t reply_len)
{
    struct km_fixture *f = context;
    const unsigned char *q = request;
    unsigned char *r = reply;
    bool get = f->calls++ == 0;
    assert(f->calls <= 2); /* one GET then at most one SET, never retry */
    assert(request_len == (get ? 4u : 24u));
    assert(request_len + reply_len == SARGO_GK_BUFFER_SIZE);
    assert(r == q + request_len);
    assert(!memcmp(q, get ? get_version_wire : set_version_wire, request_len));
    assert(r[0] == 0xff && r[1] == 0xff && r[2] == 0xff && r[3] == 0xff);
    assert(zero(r + 4, reply_len - 4));
    if ((get && f->mode == KM_GET_EMPTY) || (!get && f->mode == KM_SET_EMPTY))
        return 0;
    put32(r, 0);
    if (get) {
        if (f->mode == KM_GET_STATUS_ONLY)
            return 0;
        const uint32_t words[] = { 4, 0, 4, 165 };
        for (size_t i = 0; i < 4; ++i)
            put32(r + 4 + 4 * i, words[i] + (f->mode == KM_BAD_API_MAJOR + i));
    }
    if ((get && f->mode == KM_GET_IO) || (!get && f->mode == KM_SET_IO))
        return -EIO; /* even otherwise valid returned bytes must be ignored */
    if ((get && f->mode == KM_GET_ERROR) || (!get && f->mode == KM_SET_ERROR))
        put32(r, (uint32_t)-30);
    if ((get && f->mode == KM_GET_THROTTLE) || (!get && f->mode == KM_SET_THROTTLE))
        put32(r, 17);
    return 0;
}

static void test_negotiation(void)
{
    struct km_fixture fixture;
    struct sargo_gk client = { .context = &fixture, .exchange = version_exchange };
    struct sargo_km_version version;
    struct sargo_gk_result result;
    for (enum km_mode m = KM_OK; m <= KM_SET_EMPTY; ++m) {
        fixture = (struct km_fixture){ .mode = m };
        memset(&version, 0xa5, sizeof(version));
        result = sargo_km_negotiate(&client, &version);
        assert(fixture.calls == (m == KM_OK || m >= KM_SET_IO ? 2u : 1u));
        if (m == KM_OK) {
            assert(!result.transport && !result.status);
            assert(version.ta_api_major == 4 && version.ta_api_minor == 0 &&
                   version.ta_major == 4 && version.ta_minor == 165);
            continue;
        }
        assert(result.transport || result.status);
        assert(zero(&version, sizeof(version)));
        if (m == KM_GET_IO || m == KM_SET_IO)
            assert(result.transport == -EIO);
        else if (m == KM_GET_ERROR || m == KM_SET_ERROR)
            assert(!result.transport && result.status == -30);
        else if (m == KM_GET_THROTTLE || m == KM_SET_THROTTLE)
            assert(!result.transport && result.status == 17);
        else if (m == KM_GET_EMPTY || m == KM_SET_EMPTY)
            assert(!result.transport && result.status == -1);
        else
            assert(result.transport == -EPROTO);
    }
    unsigned before = fixture.calls;
    memset(&version, 0xa5, sizeof(version));
    result = sargo_km_negotiate(NULL, &version);
    assert(result.transport == -EINVAL && zero(&version, sizeof(version)));
    result = sargo_km_negotiate(&client, NULL);
    assert(result.transport == -EINVAL && fixture.calls == before);
    client.exchange = NULL;
    result = sargo_km_negotiate(&client, &version);
    assert(result.transport == -EINVAL && fixture.calls == before);
}

int main(void)
{
    struct sargo_gk gk = { .context = &calls, .exchange = exchange };
    struct sargo_gk_result r;
    unsigned char output[SARGO_GK_HAT_SIZE], enrolled[64];
    size_t length = 123;

    test_version_decoding();
    test_negotiation();

    mode = ENROLL;
    r = sargo_gk_enroll_new(&gk, 0x70563412, password, sizeof(password),
                            enrolled, sizeof(enrolled), &length);
    assert(!r.transport && !r.status && length == sizeof(handle));
    assert(!memcmp(enrolled, handle, length));
    assert(zero(enrolled + length, sizeof(enrolled) - length));

    mode = VERIFY;
    r = sargo_gk_verify(&gk, 0x70563412, challenge, handle, sizeof(handle),
                       password, sizeof(password), output);
    assert(!r.transport && !r.status && !sargo_gk_check_token(output, challenge));
    assert(sargo_gk_check_token(output, challenge + 1) == -EPROTO);
    output[0] = 1;
    assert(sargo_gk_check_token(output, challenge) == -EPROTO);

    for (mode = TRANSPORT_ERROR; mode <= EMPTY_REPLY; ++mode) {
        memset(output, 0xff, sizeof(output));
        r = sargo_gk_verify(&gk, 0x70563412, challenge, handle, sizeof(handle),
                           password, sizeof(password), output);
        assert(r.transport || r.status);
        assert(zero(output, sizeof(output)));
        if (mode == TRANSPORT_ERROR) assert(r.transport == -EIO);
        if (mode == SECURE_ERROR) assert(!r.transport && r.status == -30);
        if (mode == THROTTLED) assert(!r.transport && r.status == 17);
        if (mode == EMPTY_REPLY) assert(!r.transport && r.status == -1);
    }
    unsigned before = calls;
    uint32_t native;
    assert(!sargo_gk_uid_for_linux(1000, &native) && native == 0x700003e8);
    assert(sargo_gk_uid_for_linux(UINT32_MAX, &native) == -EINVAL);
    r = sargo_gk_enroll_new(&gk, 1000, password, sizeof(password),
                            enrolled, sizeof(enrolled), &length);
    assert(r.transport == -EINVAL && !length && calls == before);
    memset(output, 0xff, sizeof(output));
    r = sargo_gk_verify(&gk, 0x70563412, 0, handle, sizeof(handle),
                       password, sizeof(password), output);
    assert(r.transport == -EINVAL && zero(output, sizeof(output)) && calls == before);
    r = sargo_gk_verify(&gk, 0x70563412, challenge, handle, SARGO_GK_MAX_HANDLE + 1u,
                       password, sizeof(password), output);
    assert(r.transport == -EINVAL && calls == before);
    mode = ENROLL;
    before = calls;
    r = sargo_gk_enroll_new(&gk, 0x70563412, password, sizeof(password),
                            enrolled, sizeof(handle) - 1, &length);
    assert(r.transport == -EINVAL && !length && calls == before);
    puts("Sargo Keymaster negotiation, Gatekeeper framing and fail-closed response tests passed");
    return 0;
}
