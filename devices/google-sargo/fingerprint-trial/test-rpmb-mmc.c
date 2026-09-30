// SPDX-License-Identifier: MIT
#include <assert.h>
#include <stdarg.h>
#define ioctl mock_ioctl
#include "rpmb-mmc.c"
#undef ioctl
#include <stdio.h>

static unsigned calls;
static bool expect_write, fail;
static size_t expect_frames;
static unsigned char request[32 * SARGO_RPMB_FRAME];
static unsigned char response[49 * SARGO_RPMB_FRAME];

int mock_ioctl(int fd, unsigned long operation, ...)
{
    va_list args;
    va_start(args, operation);
    struct mmc_ioc_multi_cmd *m = va_arg(args, void *);
    va_end(args);
    assert(fd == 17 && operation == MMC_IOC_MULTI_CMD && ++calls == 1);
    assert(m->num_of_cmds == (expect_write ? 3 : 2));
    for (size_t i = 0; i < m->num_of_cmds; ++i) {
        struct mmc_ioc_cmd *c = &m->cmds[i];
        bool last = i == m->num_of_cmds - 1;
        assert(c->opcode == (last ? 18 : 25));
        unsigned flags = last ? 0 : expect_write && !i ? 0x80000001u : 1;
        assert((unsigned)c->write_flag == flags && c->flags == 53);
        assert(!c->arg && !c->is_acmd && c->blksz == 512);
        assert(c->blocks == (expect_write ? (!i ? expect_frames : 1) :
                            (last ? expect_frames : 1)));
    }
    assert(m->cmds[0].data_ptr == (uintptr_t)request);
    assert(m->cmds[m->num_of_cmds - 1].data_ptr == (uintptr_t)response);
    if (expect_write) {
        const unsigned char *q = (void *)(uintptr_t)m->cmds[1].data_ptr;
        for (size_t i = 0; i < 512; ++i) assert(q[i] == (i == 511 ? 5 : 0));
    }
    memset(response, 0xab, sizeof(response));
    if (fail) { errno = EIO; return -1; }
    return 0;
}

static void run(bool write, unsigned type, size_t frames, bool error)
{
    int fd = 17;
    memset(request, 0, sizeof(request));
    memset(response, 0, sizeof(response));
    for (unsigned i = 0; i < 32; ++i) request[i * 512 + 511] = type;
    calls = 0; expect_frames = frames; expect_write = write; fail = error;
    int rc = sargo_rpmb_mmc_transfer(&fd, write, request, write ? frames : 1,
                                    response, write ? 1 : frames);
    bool valid = write ? type == 3 : type == 4 || (type == 2 && frames == 1);
    assert(calls == (valid ? 1 : 0));
    assert(rc == (!valid ? -EINVAL : error ? -EIO : 0));
    if (rc)
        for (size_t i = 0; i < (write ? 1 : frames) * 512; ++i) assert(!response[i]);
}

int main(void)
{
    run(false, 2, 1, false);
    run(false, 4, 49, false);
    run(true, 3, 32, false);
    run(true, 3, 1, true);
    run(false, 4, 2, true);
    run(false, 1, 1, false);
    run(true, 1, 1, false);
    run(false, 3, 1, false);
    run(false, 2, 2, false);
    puts("PASS fixed MMC opcodes, reliable-write flag, atomic read/write transaction layouts, permanent key-program refusal and no retry after failure");
}
