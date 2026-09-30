/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _GNU_SOURCE
#include "auth-backend.h"
#include <assert.h>
#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/tee.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

/* Real adapter, codec and userspace transport; synthetic Linux TEE boundary.
 * Every mapping must be erased before release. No hardware is accessed. */
struct memory { unsigned char *bytes; size_t size; bool mapped; };
static struct memory memory[256];
static unsigned int next_memory, live_fds, live_maps, app_opens, app_closes, invokes;
static bool no_device, app_missing, bad_version, fail_map, wire_only, cancel_after_get;
static unsigned int fail_phase, remote_phase, secure_phase;
static int32_t secure_status;
static volatile sig_atomic_t stopping;
static unsigned char expected_request[SARGO_GK_BUFFER_SIZE];
static size_t expected_request_len;

static void put32(void *p, uint32_t v) { v = htole32(v); memcpy(p, &v, 4); }
static uint32_t get32(const void *p) { uint32_t v; memcpy(&v, p, 4); return le32toh(v); }

int __wrap_glob(const char *pattern, int flags,
                 int (*error)(const char *, int), glob_t *paths)
{
    (void)flags; (void)error;
    assert(!strcmp(pattern, "/dev/tee[0-9]*"));
    paths->gl_pathc = 1;
    paths->gl_pathv = calloc(2, sizeof(char *));
    assert(paths->gl_pathv);
    paths->gl_pathv[0] = strdup("/dev/tee1");
    assert(paths->gl_pathv[0]);
    return 0;
}
void __wrap_globfree(glob_t *paths)
{
    free(paths->gl_pathv[0]);
    free(paths->gl_pathv);
}
int __wrap_open(const char *path, int flags, ...)
{
    assert(!strcmp(path, "/dev/tee1") && flags == (O_RDWR | O_CLOEXEC));
    if (no_device) { errno = EACCES; return -1; }
    live_fds++;
    return 10;
}
int __wrap_close(int fd)
{
    assert(live_fds && (fd == 10 || fd >= 100));
    live_fds--;
    if (fd >= 100 && !memory[fd - 100].mapped) {
        free(memory[fd - 100].bytes);
        memory[fd - 100].bytes = NULL;
    }
    return 0;
}
void *__wrap_mmap(void *address, size_t size, int prot, int flags, int fd, off_t offset)
{
    assert(!address && !offset && prot == (PROT_READ | PROT_WRITE) && flags == MAP_SHARED);
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
        assert(memory[i].mapped && size == memory[i].size && live_maps);
        for (size_t j = 0; j < size; j++) assert(!memory[i].bytes[j]);
        free(memory[i].bytes);
        memset(&memory[i], 0, sizeof(memory[i]));
        live_maps--;
        return 0;
    }
    abort();
}
int __wrap_ioctl(int fd, unsigned long operation, ...)
{
    va_list args;
    va_start(args, operation);
    void *arg = va_arg(args, void *);
    va_end(args);
    assert(fd == 10);
    if (operation == TEE_IOC_VERSION) {
        ((struct tee_ioctl_version_data *)arg)->impl_id = 5;
        return 0;
    }
    if (operation == TEE_IOC_SHM_ALLOC) {
        struct tee_ioctl_shm_alloc_data *shm = arg;
        assert(next_memory + 1 < sizeof(memory) / sizeof(memory[0]));
        shm->id = ++next_memory;
        shm->size = (shm->size + 4095) & ~UINT64_C(4095);
        memory[next_memory].size = shm->size;
        memory[next_memory].bytes = malloc(shm->size);
        assert(memory[next_memory].bytes);
        memset(memory[next_memory].bytes, 0xa5, shm->size);
        live_fds++;
        return 100 + next_memory;
    }
    if (operation == TEE_IOC_CLOSE_SESSION) {
        assert(((struct tee_ioctl_close_session_arg *)arg)->session == 0);
        app_closes++;
        return 0;
    }
    struct tee_ioctl_buf_data *data = arg;
    if (operation == TEE_IOC_OPEN_SESSION) {
        struct tee_ioctl_open_session_arg *open = (void *)(uintptr_t)data->buf_ptr;
        assert(open->num_params == 1);
        assert(!strcmp((char *)memory[open->params[0].c].bytes, "keymaster64"));
        app_opens++;
        if (app_missing) { errno = ENOENT; return -1; }
        open->session = 0;
        return 0;
    }
    assert(operation == TEE_IOC_INVOKE);
    struct tee_ioctl_invoke_arg *invoke = (void *)(uintptr_t)data->buf_ptr;
    struct tee_ioctl_param *p = invoke->params;
    assert(invoke->num_params == 2 && !invoke->session && !invoke->func);
    assert(data->buf_len == sizeof(*invoke) + 2 * sizeof(*p));
    assert(p[0].attr == TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INPUT && !p[0].a);
    assert(p[1].attr == TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_OUTPUT && p[0].c == p[1].c);
    assert(p[0].b + p[1].b == SARGO_GK_BUFFER_SIZE);
    assert(p[1].a == ((p[0].b + 63) & ~UINT64_C(63)));
    unsigned char *req = memory[p[0].c].bytes;
    unsigned char *rsp = memory[p[1].c].bytes + p[1].a;
    for (size_t i = 0; i < p[1].b; i++) assert(!rsp[i]);
    invokes++;
    if (fail_phase == invokes) { errno = EIO; return -1; }
    if (remote_phase == invokes) { invoke->ret = 0xffff0000u; return 0; }
    if (wire_only) {
        assert(p[0].b == expected_request_len);
        assert(!memcmp(req, expected_request, expected_request_len));
        memset(rsp, 0x5a, p[1].b);
        return 0;
    }
    if (invokes == 1) {
        assert(p[0].b == 4 && get32(req) == 0x200);
        put32(rsp + 4, 4);
        put32(rsp + 12, 4);
        put32(rsp + 16, bad_version ? 166 : 165);
        if (cancel_after_get) stopping = 1;
    } else {
        const uint32_t words[] = { 0x207, 4, 5, 4, 5, 0 };
        assert(invokes == 2 && p[0].b == 24);
        for (size_t i = 0; i < 6; i++) assert(get32(req + i * 4) == words[i]);
    }
    if (secure_phase == invokes) put32(rsp, (uint32_t)secure_status);
    return 0;
}

static void reset(void)
{
    assert(!live_fds && !live_maps);
    invokes = app_opens = app_closes = 0;
    no_device = app_missing = bad_version = fail_map = wire_only = cancel_after_get = false;
    fail_phase = remote_phase = secure_phase = 0;
    secure_status = 0;
    stopping = 0;
}
static void failure(int expected, unsigned int expected_invokes)
{
    struct auth_backend backend = AUTH_BACKEND_INIT;
    assert(auth_backend_open(&backend, &stopping) == expected);
    assert(!backend.session.opened && backend.session.fd == -1 && !backend.gk.exchange && !backend.gk.context);
    assert(invokes == expected_invokes && !live_maps && !live_fds);
    auth_backend_close(&backend);
}
int main(void)
{
    struct auth_backend backend = AUTH_BACKEND_INIT;
    reset();
    stopping = 1;
    failure(-ECANCELED, 0);
    assert(!app_opens);
    reset(); no_device = true; failure(-EACCES, 0);
    reset(); app_missing = true; failure(-ENOENT, 0);
    reset(); fail_map = true; failure(-ENOMEM, 0);
    reset(); bad_version = true; failure(-EPROTO, 1);
    assert(app_closes == 1);
    reset(); cancel_after_get = true; failure(-ECANCELED, 1);
    for (unsigned int phase = 1; phase <= 2; phase++) {
        reset(); fail_phase = phase; failure(-EIO, phase);
        reset(); remote_phase = phase; failure(-EREMOTEIO, phase);
        reset(); secure_phase = phase; secure_status = -30; failure(-EACCES, phase);
        reset(); secure_phase = phase; secure_status = 30000; failure(-EAGAIN, phase);
    }
    reset();
    assert(auth_backend_open(&backend, &stopping) == 0);
    assert(invokes == 2 && app_opens == 1 && !app_closes && live_fds == 1 && !live_maps);
    assert(auth_backend_open(&backend, &stopping) == -EBUSY && app_opens == 1);
    wire_only = true;
    const size_t lengths[] = { 4, 24, 96, 154, 95 };
    unsigned char *buffer = malloc(SARGO_GK_BUFFER_SIZE);
    assert(buffer);
    for (size_t j = 0; j < sizeof(lengths) / sizeof(lengths[0]); j++) {
        expected_request_len = lengths[j];
        for (size_t i = 0; i < expected_request_len; i++) expected_request[i] = (unsigned char)(i + 1);
        memcpy(buffer, expected_request, expected_request_len);
        memset(buffer + expected_request_len, 0xa5, SARGO_GK_BUFFER_SIZE - expected_request_len);
        assert(backend.gk.exchange(&backend, buffer, expected_request_len,
            buffer + expected_request_len, SARGO_GK_BUFFER_SIZE - expected_request_len) == 0);
        assert(!memcmp(buffer, expected_request, expected_request_len));
        for (size_t i = expected_request_len; i < SARGO_GK_BUFFER_SIZE; i++) assert(buffer[i] == 0x5a);
    }
    unsigned int before = invokes;
    const size_t bad_lengths[] = { 0, 1, 3, SARGO_GK_BUFFER_SIZE, SIZE_MAX };
    for (size_t i = 0; i < sizeof(bad_lengths) / sizeof(bad_lengths[0]); i++)
        assert(backend.gk.exchange(&backend, buffer, bad_lengths[i], buffer + 4, 20) == -EINVAL);
    assert(backend.gk.exchange(&backend, buffer, 4, buffer + 4, 20) == -EINVAL);
    stopping = 1;
    assert(backend.gk.exchange(&backend, buffer, 4, buffer + 4, SARGO_GK_BUFFER_SIZE - 4) == -ECANCELED);
    assert(invokes == before);
    auth_backend_close(&backend);
    auth_backend_close(&backend);
    assert(app_closes == 1 && !live_fds && !live_maps);
    explicit_bzero(buffer, SARGO_GK_BUFFER_SIZE);
    free(buffer);
    puts("PASS real Keymaster adapter/TEE framing, aliasing, cancellation, failures and erased SHM");
    return 0;
}
