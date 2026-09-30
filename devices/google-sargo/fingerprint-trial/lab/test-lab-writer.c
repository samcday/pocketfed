/* SPDX-License-Identifier: MIT */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "rpmb-mmc.h"
#include <assert.h>
#include <ctype.h>
#include <errno.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
static volatile sig_atomic_t stopping;
static unsigned calls;
static int failure;
#define sargo_rpmb_mmc_transfer fake_mmc
static int fake_mmc(void *ctx, bool write, const void *q, size_t nr, void *r, size_t ns)
{
    (void)ctx; assert(q && nr == 1 && r && ns == 1); ++calls;
    memset(r, 0, 512);
    ((unsigned char *)r)[510] = write ? 3 : 2;
    ((unsigned char *)r)[509] = failure == 2 ? 3 : 0;
    return failure == 1 ? -EIO : 0;
}
#include "lab-writer.h"
#undef sargo_rpmb_mmc_transfer

int main(void)
{
    assert(writer_identity_line("androidboot.serialno=99NAY1AZG1 pocketfed.root_mode=usb pocketfed.liveboot=" WRITER_RUN));
    assert(!writer_identity_line("androidboot.serialno=other pocketfed.root_mode=usb pocketfed.liveboot=" WRITER_RUN));
    assert(!writer_identity_line("androidboot.serialno=99NAY1AZG1 pocketfed.root_mode=ram pocketfed.liveboot=" WRITER_RUN));
    assert(!writer_identity()); /* Host/container is not the fixed liveboot. */
    unsigned char q[512] = {0}, r[512] = {0};
    assert(bounded_transfer(NULL, true, q, 1, r, 1) == -EPERM && !calls);
    writer_authorized = true;
    for (unsigned i = 0; i < 8; ++i) assert(!bounded_transfer(NULL, true, q, 1, r, 1));
    assert(writer_groups == 8 && calls == 8);
    assert(bounded_transfer(NULL, true, q, 1, r, 1) == -EPERM && calls == 8);
    assert(!bounded_transfer(NULL, false, q, 1, r, 1) && calls == 9);
    stopping = 1;
    assert(bounded_transfer(NULL, false, q, 1, r, 1) == -EPERM && calls == 9);
    stopping = 0;
    for (failure = 1; failure <= 2; ++failure) {
        writer_groups = 0; writer_failed = false;
        int rc = bounded_transfer(NULL, true, q, 1, r, 1);
        assert(rc == (failure == 1 ? -EIO : 0) && writer_failed && writer_groups == 1);
        unsigned before = calls;
        assert(bounded_transfer(NULL, true, q, 1, r, 1) == -EPERM && calls == before);
    }
    puts("PASS exact writer identity, authorization, eight-group cap, stopping and permanent write refusal after transport/device failure");
}
