// SPDX-License-Identifier: MIT
#include "rpmb-protocol.c"
#include <assert.h>
#include <stdio.h>

static unsigned char buffer[SARGO_RPMB_BUFFER];
static struct sargo_rpmb_geometry geometry = {32768, 1};
static unsigned calls, fail_call, device_fail_call;
static uint16_t expected_type;
static unsigned expected_frames;

static void put16(unsigned char *p, uint16_t v)
{
    p[0] = v >> 8;
    p[1] = v;
}

static void setup(uint32_t command, unsigned count, unsigned type)
{
    memset(buffer, 0xa5, sizeof(buffer));
    put32(buffer, command);
    put32(buffer + 4, count);
    unsigned frames = command == READ ? 1 : count;
    put32(buffer + 8, frames * SARGO_RPMB_FRAME);
    put32(buffer + 12, 24);
    put32(buffer + 16, 2);
    put32(buffer + 20, geometry.reliable_frames);
    for (unsigned i = 0; i < frames; ++i) {
        unsigned char *f = buffer + 24 + i * SARGO_RPMB_FRAME;
        put16(f + 504, 0);
        put16(f + 506, command == READ ? count : geometry.reliable_frames);
        put16(f + 510, type);
    }
    expected_type = type;
    expected_frames = command == READ ? count : geometry.reliable_frames;
    calls = fail_call = device_fail_call = 0;
}

static int transfer(void *ctx, bool write, const void *req, size_t nr,
                    void *resp, size_t ns)
{
    const unsigned char *q = req;
    unsigned char *r = resp;
    assert(ctx == &geometry);
    assert(write == (expected_type == DATA_WRITE));
    assert(nr == (write ? expected_frames : 1));
    assert(ns == (write ? 1 : expected_frames));
    /* Request snapshot must survive zeroing of its overlapping reply buffer. */
    for (unsigned i = 0; i < nr; ++i) {
        assert(q[i * SARGO_RPMB_FRAME] == 0xa5);
        assert(be16(q + i * SARGO_RPMB_FRAME + 510) == expected_type);
    }
    ++calls;
    memset(r, 0x37, ns * SARGO_RPMB_FRAME);
    put16(r + 510, expected_type << 8);
    put16(r + 508, calls == device_fail_call ? 3 : 0);
    return calls == fail_call ? -1 : 0;
}

static void dispatch(bool writes, bool success, unsigned count)
{
    assert(!sargo_rpmb_dispatch(buffer, sizeof(buffer), &geometry, writes,
                                transfer, &geometry));
    assert(le32(buffer + 4) == (success ? 0 : UINT32_MAX));
    assert(calls == count);
    if (!success) {
        assert(!le32(buffer + 8) && !le32(buffer + 12));
        for (size_t i = RW_RESPONSE; i < sizeof(buffer); ++i)
            assert(!buffer[i]);
    }
}

int main(void)
{
    memset(buffer, 0xa5, sizeof(buffer));
    put32(buffer, INIT); put32(buffer + 4, 2);
    assert(!sargo_rpmb_dispatch(buffer, sizeof(buffer), &geometry, false, NULL, NULL));
    assert(!le32(buffer + 8) && le32(buffer + 12) == 32768);
    assert(le32(buffer + 16) == 1 && le32(buffer + 20) == 3);
    for (size_t i = 24; i < sizeof(buffer); ++i) assert(!buffer[i]);

    setup(READ, 1, COUNTER); dispatch(false, true, 1);
    assert(le32(buffer + 8) == 512 && le32(buffer + 12) == 20);
    setup(READ, 49, DATA_READ); dispatch(false, true, 1);
    assert(le32(buffer + 8) == 49 * 512);
    assert(le32(buffer + 16) == 2);
    /* Measured callback: 34 read frames and zero in the RW version field.
     * This is a synthetic frame, never a copy of device storage traffic. */
    setup(READ, 34, DATA_READ); put32(buffer + 16, 0);
    dispatch(false, true, 1);
    assert(le32(buffer + 8) == 34 * 512 && le32(buffer + 16) == 0);
    /* Live SAM.008 declares 34 * 256 payload bytes, but sends one physical
     * request frame and expects 34 complete response frames. */
    setup(READ, 34, DATA_READ); put32(buffer + 16, 0); put32(buffer + 8, 8704);
    dispatch(false, true, 1);
    assert(le32(buffer + 8) == 34 * 512 && le32(buffer + 16) == 0);
    setup(READ, 1, DATA_READ); put32(buffer + 8, 256);
    dispatch(false, true, 1); assert(le32(buffer + 8) == 512);
    setup(READ, 1, DATA_READ); put32(buffer + 8, 256);
    put32(buffer + 12, sizeof(buffer) - 256); dispatch(false, false, 0);
    setup(READ, 34, DATA_READ); put32(buffer + 8, 8703);
    dispatch(false, false, 0);
    setup(READ, 34, DATA_READ); put32(buffer + 16, 0); fail_call = 1;
    dispatch(false, false, 1); assert(le32(buffer + 16) == 0);
    setup(WRITE, 1, DATA_WRITE); put32(buffer + 16, 0);
    dispatch(false, false, 0); assert(le32(buffer + 16) == 0);
    setup(READ, 1, DATA_READ); put32(buffer + 16, 1);
    dispatch(false, true, 1); assert(le32(buffer + 16) == 1);
    setup(READ, 1, DATA_READ); put32(buffer + 16, UINT32_MAX);
    dispatch(false, true, 1); assert(le32(buffer + 16) == UINT32_MAX);
    /* Measured initialization write: two physical frames, opaque field 0x100.
     * Authorization still independently decides whether it can be forwarded. */
    geometry.reliable_frames = 2;
    setup(WRITE, 2, DATA_WRITE); put32(buffer + 16, 0x100);
    dispatch(false, false, 0); assert(le32(buffer + 16) == 0x100);
    setup(WRITE, 2, DATA_WRITE); put32(buffer + 16, 0x100);
    dispatch(true, true, 1); assert(le32(buffer + 16) == 0x100);
    geometry.reliable_frames = 1;
    setup(READ, 2, COUNTER); dispatch(false, false, 0);
    setup(READ, 1, 1); dispatch(true, false, 0); /* Key programming forbidden. */
    setup(WRITE, 1, 1); dispatch(true, false, 0);
    setup(WRITE, 1, DATA_WRITE); dispatch(false, false, 0);
    setup(WRITE, 3, DATA_WRITE); dispatch(true, true, 3);
    setup(WRITE, 3, DATA_WRITE); fail_call = 2; dispatch(true, false, 2);
    setup(WRITE, 3, DATA_WRITE); device_fail_call = 2; dispatch(true, true, 2);
    assert(be16(buffer + 20 + 508) == 3);
    setup(READ, 1, COUNTER); fail_call = 1; dispatch(false, false, 1);

    geometry.reliable_frames = 32;
    setup(WRITE, 32, DATA_WRITE); dispatch(true, true, 1);
    setup(WRITE, 33, DATA_WRITE); dispatch(true, false, 0);
    setup(WRITE, 32, DATA_WRITE); put32(buffer + 20, 0); dispatch(true, false, 0);
    setup(WRITE, 32, DATA_WRITE); put32(buffer + 20, 33); dispatch(true, false, 0);
    setup(WRITE, 1, DATA_WRITE); put32(buffer + 20, 1);
    put16(buffer + 24 + 506, 1); expected_frames = 1; dispatch(true, true, 1);
    geometry.reliable_frames = 1;

    /* Every envelope field is untrusted, including integer overflow cases. */
    const unsigned fields[] = {0, 4, 8, 12};
    for (size_t i = 0; i < sizeof(fields) / sizeof(fields[0]); ++i) {
        setup(READ, 1, DATA_READ); put32(buffer + fields[i], UINT32_MAX);
        dispatch(false, false, 0);
    }
    setup(READ, 1, DATA_READ); put32(buffer + 4, 0); dispatch(false, false, 0);
    setup(READ, 1, DATA_READ); put32(buffer + 12, 20); dispatch(false, false, 0);
    setup(READ, 2, DATA_READ); put16(buffer + 24 + 504, 65535); dispatch(false, false, 0);
    setup(READ, 1, DATA_READ); put16(buffer + 24 + 506, 2); dispatch(false, false, 0);
    setup(WRITE, 1, DATA_WRITE); put16(buffer + 24 + 506, 2); dispatch(true, false, 0);
    setup(READ, 1, COUNTER); geometry.sectors_512 = 0; dispatch(false, false, 0);
    geometry.sectors_512 = 32768;
    for (size_t n = 0; n < INIT_RESPONSE; ++n)
        assert(sargo_rpmb_dispatch(buffer, n, &geometry, false, transfer, &geometry) == -1);
    puts("PASS RPMB framing, overlapping buffers, capacity bounds, write opt-in, permanent key-program refusal, batching and no retry after device/transport errors");
}
