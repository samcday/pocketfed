/* SPDX-License-Identifier: MIT */
#define main supplicant_main
#define sargo_rpmb_mmc_transfer mock_transfer
#include "rpmb-supplicant.c"
#undef main
#undef sargo_rpmb_mmc_transfer
#include <assert.h>

static unsigned calls;
int mock_transfer(void *ctx, bool write, const void *request, size_t nr, void *response, size_t ns)
{
    const unsigned char *q = request; unsigned char *r = response;
    assert(ctx == &rpmb_fd && ns == 1 && nr == (write ? 2 : 1));
    assert(q[510] == 0 && q[511] == (write ? 3 : 2));
    memset(r, 0, 512); r[510] = write ? 3 : 2; ++calls; return 0;
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
int main(void)
{
    unsigned char b[SARGO_RPMB_BUFFER + 4096] = {0};
    geometry = (struct sargo_rpmb_geometry){32768, 32}; rpmb_fd = 17;
    write_request(b, 3);
    assert(!dispatch_rpmb(NULL, b, sizeof b) && get32(b + 4) == UINT32_MAX && !calls);
    writer_authorized = true;
    write_request(b, 3);
    assert(!dispatch_rpmb(NULL, b, sizeof b) && !get32(b + 4) && calls == 1 && writer_groups == 1);
    assert(get32(b + 16) == 0x100);
    write_request(b, 1); /* Key programming never reaches the adapter. */
    assert(!dispatch_rpmb(NULL, b, sizeof b) && get32(b + 4) == UINT32_MAX && calls == 1);
    stopping = 1; write_request(b, 3);
    assert(!dispatch_rpmb(NULL, b, sizeof b) && get32(b + 4) == UINT32_MAX && calls == 1);
    puts("PASS combined writer dispatch, identity authorization, opaque field, fixed group, key-program refusal and stop guard");
}
