/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _GNU_SOURCE
#include "qsee-transport.h"
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/tee.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

/* Simulated Linux TEE boundary: wrong backend, handle lifetime, ioctl errors,
 * zero-valued session IDs, plain requests and the recovered Sargo aux ABI.
 * No fake match is exposed to fprintd and no hardware is accessed.
 */
static struct allocation { unsigned char *bytes; size_t size; bool mapped; } memory[32];
static unsigned int next_memory, live_maps, live_fds, closes, invokes;
static bool fail_map, fail_allocate, remote_error, fail_invoke;

int __wrap_glob(const char *pattern, int flags,
                 int (*error)(const char *, int), glob_t *paths)
{
    (void)flags; (void)error;
    assert(!strcmp(pattern, "/dev/tee[0-9]*"));
    paths->gl_pathc = 2;
    paths->gl_pathv = calloc(3, sizeof(char *));
    assert(paths->gl_pathv);
    paths->gl_pathv[0] = strdup("/dev/tee0");
    paths->gl_pathv[1] = strdup("/dev/tee7");
    return 0;
}
void __wrap_globfree(glob_t *paths)
{
    for (size_t i = 0; i < paths->gl_pathc; i++) free(paths->gl_pathv[i]);
    free(paths->gl_pathv);
}
int __wrap_open(const char *path, int flags, ...)
{
    assert(flags == (O_RDWR | O_CLOEXEC));
    live_fds++;
    if (!strcmp(path, "/dev/tee0")) return 10;
    assert(!strcmp(path, "/dev/tee7"));
    return 11;
}
int __wrap_close(int fd)
{
    assert(live_fds);
    live_fds--;
    if (fd >= 100 && !memory[fd - 100].mapped) {
        free(memory[fd - 100].bytes);
        memory[fd - 100].bytes = NULL;
    }
    return 0;
}
void *__wrap_mmap(void *address, size_t size, int protection, int flags, int fd, off_t offset)
{
    (void)address;
    assert(protection == (PROT_READ | PROT_WRITE) && flags == MAP_SHARED && !offset);
    assert(fd >= 100 && memory[fd - 100].size == size);
    if (fail_map) { errno = ENOMEM; return MAP_FAILED; }
    memory[fd - 100].mapped = true;
    live_maps++;
    return memory[fd - 100].bytes;
}
int __wrap_munmap(void *address, size_t size)
{
    for (unsigned int i = 1; i <= next_memory; i++) {
        if (memory[i].bytes != address) continue;
        assert(memory[i].mapped && memory[i].size == size && live_maps);
        /* The library must erase command/token bytes before releasing SHM. */
        for (size_t j = 0; j < size; j++) assert(!memory[i].bytes[j]);
        free(memory[i].bytes);
        memory[i].bytes = NULL;
        memory[i].mapped = false;
        live_maps--;
        return 0;
    }
    abort();
}
int __wrap_ioctl(int fd, unsigned long operation, ...)
{
    va_list ap;
    va_start(ap, operation);
    void *argument = va_arg(ap, void *);
    va_end(ap);
    if (operation == TEE_IOC_VERSION) {
        struct tee_ioctl_version_data *version = argument;
        version->impl_id = fd == 10 ? 4 : 5;
        return 0;
    }
    assert(fd == 11);
    if (operation == TEE_IOC_SHM_ALLOC) {
        struct tee_ioctl_shm_alloc_data *request = argument;
        if (fail_allocate) { errno = ENOMEM; return -1; }
        assert(next_memory + 1 < 32);
        request->id = ++next_memory;
        request->size = (request->size + 4095) & ~UINT64_C(4095);
        memory[next_memory].size = request->size;
        memory[next_memory].bytes = malloc(request->size);
        assert(memory[next_memory].bytes);
        memset(memory[next_memory].bytes, 0xa5, request->size);
        live_fds++;
        return 100 + next_memory;
    }
    if (operation == TEE_IOC_OPEN_SESSION) {
        struct tee_ioctl_buf_data *buffer = argument;
        struct tee_ioctl_open_session_arg *request = (void *)(uintptr_t)buffer->buf_ptr;
        assert(buffer->buf_len == sizeof(*request) + sizeof(struct tee_ioctl_param));
        assert(request->num_params == 1);
        assert(!strcmp((char *)memory[request->params[0].c].bytes, "fpctzappfingerprint"));
        request->session = 0; /* A valid ID must not be confused with unopened. */
        request->ret = remote_error ? 0xffff0000u : 0;
        return 0;
    }
    if (operation == TEE_IOC_CLOSE_SESSION) {
        assert(((struct tee_ioctl_close_session_arg *)argument)->session == 0);
        closes++;
        return 0;
    }
    assert(operation == TEE_IOC_INVOKE);
    invokes++;
    if (fail_invoke) { errno = EIO; return -1; }
    struct tee_ioctl_buf_data *buffer = argument;
    struct tee_ioctl_invoke_arg *request = (void *)(uintptr_t)buffer->buf_ptr;
    assert(request->func == 0 && request->session == 0);
    assert(buffer->buf_len == sizeof(*request) + request->num_params * sizeof(struct tee_ioctl_param));
    struct tee_ioctl_param *p = request->params;
    assert(p[0].attr == TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INPUT);
    assert(p[1].attr == TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_OUTPUT);
    assert(p[1].a == 64 && p[0].c == p[1].c);
    unsigned char *response = memory[p[1].c].bytes + p[1].a;
    if (request->num_params == 4) {
        assert(p[0].b == 64 && p[1].b == 64);
        assert(p[2].attr == TEE_IOCTL_PARAM_ATTR_TYPE_VALUE_INPUT);
        assert(p[2].a == 4 && p[2].b == 8 && p[2].c == 0);
        assert(p[3].attr == TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INOUT);
        assert(p[3].b == 4096);
        unsigned char *outer = memory[p[0].c].bytes;
        assert(outer[0] == 0 && outer[1] == 16 && outer[2] == 0 && outer[3] == 0);
        for (unsigned int i = 4; i < 64; i++) assert(!outer[i]);
        unsigned char *auxiliary = memory[p[3].c].bytes;
        assert(auxiliary[0] == 10 && auxiliary[4] == 3);
        memset(auxiliary + 8, 0, 4);
        memset(response, 0, 64);
    } else {
        assert(request->num_params == 2);
        assert(p[0].b == 12 && p[1].b == 8);
        memset(response, 0x42, 8);
    }
    request->ret = remote_error ? 0xffff0000u : 0;
    return 0;
}

int main(void)
{
    struct fpc_qsee_session session = FPC_QSEE_SESSION_INIT;
    struct fpc_qsee_session unused = {0};
    unsigned char command[88] = {10, 0, 0, 0, 3, 0, 0, 0, 0xff};
    unsigned char request[12] = {0}, response[8];
    int32_t outer = -1;

    fpc_qsee_close(&unused); /* Closing an unused zero object must not close stdin. */
    assert(!live_fds && !closes && unused.fd == -1);
    assert(!fpc_qsee_open(&session, "fpctzappfingerprint"));
    assert(session.opened && !session.id && live_fds == 1 && !live_maps);
    assert(fpc_qsee_open(&session, "fpctzappfingerprint") == -EBUSY);
    assert(session.opened && session.fd == 11 && live_fds == 1 && !live_maps);
    assert(!fpc_qsee_command(&session, command, sizeof(command), &outer));
    assert(!outer && !command[8]);
    assert(!fpc_qsee_exchange(&session, request, sizeof(request), response,
                             sizeof(response), NULL, 0, 0));
    for (size_t i = 0; i < sizeof(response); i++) assert(response[i] == 0x42);
    unsigned int before = invokes;
    assert(fpc_qsee_exchange(&session, request, sizeof(request), response,
                            sizeof(response), command, sizeof(command), 5) == -EINVAL);
    assert(invokes == before);
    memset(response, 0x99, sizeof(response));
    remote_error = true;
    assert(fpc_qsee_exchange(&session, request, sizeof(request), response,
                            sizeof(response), NULL, 0, 0) == -EREMOTEIO);
    for (size_t i = 0; i < sizeof(response); i++) assert(response[i] == 0x99);
    remote_error = false;
    fail_invoke = true;
    assert(fpc_qsee_command(&session, command, sizeof(command), &outer) == -EIO);
    assert(outer == -1);
    fail_invoke = false;
    fpc_qsee_close(&session);
    fpc_qsee_close(&session);
    assert(closes == 1 && !live_fds && !live_maps);
    fail_allocate = true;
    assert(fpc_qsee_open(&session, "fpctzappfingerprint") == -ENOMEM);
    fail_allocate = false;
    fail_map = true;
    assert(fpc_qsee_open(&session, "fpctzappfingerprint") == -ENOMEM);
    fail_map = false;
    remote_error = true;
    assert(fpc_qsee_open(&session, "fpctzappfingerprint") == -EREMOTEIO);
    assert(!session.opened && session.fd == -1 && !live_fds && !live_maps);
    puts("transport ABI, cleanup and fail-closed tests: OK");
    return 0;
}
