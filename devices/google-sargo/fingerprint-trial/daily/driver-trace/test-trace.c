/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _GNU_SOURCE
#include "trace.h"
#include <assert.h>
#include <string.h>

static char captured[256];
static size_t length;
static int failure;

ssize_t __wrap_write(int fd, const void *data, size_t count)
{
    assert(fd == STDERR_FILENO);
    assert(count < sizeof(captured));
    memcpy(captured, data, count);
    captured[count] = 0;
    length = count;
    errno = EBADF; /* Even a failed diagnostic sink must not alter a syscall error. */
    return failure ? -1 : (ssize_t)count;
}

int main(void)
{
    for (failure = 0; failure <= 1; failure++) {
        errno = ETIMEDOUT;
        fpc_trial_trace("tee.invoke.end", 0, 0, -ETIMEDOUT);
        assert(errno == ETIMEDOUT);
        assert(length > 0 && captured[length - 1] == '\n');
        assert(strstr(captured, "FPC_TRACE ") == captured);
        assert(strstr(captured, "tee.invoke.end a=0 b=0 status=-110\n"));
    }
    puts("trace sink success/failure both preserve errno and bounded metadata framing");
}
