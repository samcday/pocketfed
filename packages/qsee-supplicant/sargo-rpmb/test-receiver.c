/* SPDX-License-Identifier: MIT */
#define main supplicant_main
#define sargo_rpmb_mmc_transfer mock_transfer
#include "main.c"
#undef main
#undef sargo_rpmb_mmc_transfer
#include <assert.h>

static unsigned calls, device_status, response_type = 0x300;
static int transport_status;
int mock_transfer(void *ctx, bool write, const void *request, size_t nr, void *response, size_t ns)
{
    const unsigned char *q = request; unsigned char *r = response;
    assert(ctx == &rpmb_fd && ns == 1 && nr == (write ? 2 : 1));
    assert(q[510] == 0 && q[511] == (write ? 3 : 2));
    memset(r, 0, 512);
    if (write) {
        r[510] = response_type >> 8; r[511] = response_type;
        r[508] = device_status >> 8; r[509] = device_status;
    } else r[510] = 2;
    ++calls;
    return write ? transport_status : 0;
}
static void put32(unsigned char *b, uint32_t x)
{ for (unsigned i = 0; i < 4; ++i) b[i] = x >> (8 * i); }
static void write_request(unsigned char *b, unsigned type)
{
    memset(b, 0, SARGO_RPMB_BUFFER);
    put32(b, 0x103); put32(b + 4, 2); put32(b + 8, 1024);
    put32(b + 12, 24); put32(b + 16, 0x100); put32(b + 20, 2);
    for (unsigned i = 0; i < 2; ++i) {
        b[24 + i * 512 + 507] = 2; b[24 + i * 512 + 511] = type;
    }
}
static void read_request(unsigned char *b)
{
    memset(b, 0, SARGO_RPMB_BUFFER);
    put32(b, 0x102); put32(b + 4, 1); put32(b + 8, 512);
    put32(b + 12, 24); b[24 + 511] = 2;
}
int main(void)
{
    unsigned char b[SARGO_RPMB_BUFFER + 4096] = {0};
    geometry = (struct sargo_rpmb_geometry){32768, 32}; rpmb_fd = 17;
    write_request(b, 3);
    assert(!dispatch_rpmb(NULL, b, sizeof b) && get32(b + 4) == UINT32_MAX && !calls);
    read_request(b);
    assert(!dispatch_rpmb(NULL, b, sizeof b) && !get32(b + 4) && calls == 1);
    policy.enabled = true;
    for (unsigned i = 0; i < 12; ++i) {
        write_request(b, 3);
        assert(!dispatch_rpmb(NULL, b, sizeof b) && !get32(b + 4) && calls == i + 2);
        assert(get32(b + 16) == 0x100 && !policy.failed);
    }
    unsigned previous = calls;
    write_request(b, 1); /* Key programming never reaches the adapter. */
    assert(!dispatch_rpmb(NULL, b, sizeof b) && get32(b + 4) == UINT32_MAX && calls == previous);
    for (unsigned failure = 0; failure < 3; ++failure) {
        policy.failed = false; transport_status = failure == 0 ? -EIO : 0;
        response_type = failure == 1 ? 0x200 : 0x300;
        device_status = failure == 2 ? 3 : 0;
        write_request(b, 3);
        assert(!dispatch_rpmb(NULL, b, sizeof b) && policy.failed && calls == previous + 1);
        assert((get32(b + 4) != 0) == (failure == 0));
        write_request(b, 3);
        assert(!dispatch_rpmb(NULL, b, sizeof b) && get32(b + 4) == UINT32_MAX && calls == previous + 1);
        read_request(b);
        assert(!dispatch_rpmb(NULL, b, sizeof b) && !get32(b + 4) && calls == previous + 2);
        previous = calls;
    }
    stopping = 1; read_request(b);
    assert(!dispatch_rpmb(NULL, b, sizeof b) && get32(b + 4) == UINT32_MAX && calls == previous);
    puts("PASS read-only mode, repeated signed writes, opaque field, key-program refusal, failure latch, post-failure reads and stopping");
}
