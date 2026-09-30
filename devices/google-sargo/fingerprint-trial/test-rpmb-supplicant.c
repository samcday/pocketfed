// SPDX-License-Identifier: MIT
#define main supplicant_main
#define sargo_rpmb_mmc_transfer mock_transfer
#include "rpmb-supplicant.c"
#undef main
#undef sargo_rpmb_mmc_transfer
#include <assert.h>

static unsigned calls;
int mock_transfer(void *ctx, bool write, const void *request, size_t nr,
                   void *response, size_t ns)
{
    const unsigned char *q = request;
    unsigned char *r = response;
    assert(ctx == &rpmb_fd && !write && nr == 1 && ns == 1);
    assert(q[510] == 0 && q[511] == 2);
    memset(r, 0, 512);
    r[510] = 2;
    ++calls;
    return 0;
}

static void put32(unsigned char *b, uint32_t value)
{
    for (unsigned i = 0; i < 4; ++i) b[i] = value >> (i * 8);
}

int main(void)
{
    unsigned char b[SARGO_RPMB_BUFFER + 4096] = {0};
    geometry = (struct sargo_rpmb_geometry){32768, 32};
    rpmb_fd = 17;
    put32(b, 0x101); put32(b + 4, 2);
    assert(!dispatch_rpmb(NULL, b, sizeof(b)) && !get32(b + 8) && !calls);
    memset(b, 0, sizeof(b));
    put32(b, 0x102); put32(b + 4, 1); put32(b + 8, 512);
    put32(b + 12, 24); put32(b + 16, 2); b[24 + 511] = 2;
    assert(!dispatch_rpmb(NULL, b, sizeof(b)) && !get32(b + 4) && calls == 1);
    memset(b, 0, sizeof(b));
    put32(b, 0x103); put32(b + 4, 1); put32(b + 8, 512);
    put32(b + 12, 24); put32(b + 16, 2); put32(b + 20, 1);
    b[24 + 507] = 1; b[24 + 511] = 3;
    assert(!dispatch_rpmb(NULL, b, sizeof(b)) && get32(b + 4) == UINT32_MAX && calls == 1);
    for (size_t i = 20; i < SARGO_RPMB_BUFFER; ++i) assert(!b[i]);
    assert(read_only_transfer(&rpmb_fd, true, b, 1, b + 512, 1) == -EPERM && calls == 1);
    stopping = 1;
    assert(read_only_transfer(&rpmb_fd, false, b, 1, b + 512, 1) == -EPERM && calls == 1);
    assert(dispatch_rpmb(NULL, b, SARGO_RPMB_BUFFER - 1) == -1);
    puts("PASS combined-daemon RPMB dispatch, page-rounded capacity, both write guards and stop refusal");
}
