/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _GNU_SOURCE
#include "qsee-transport.h"

#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <glob.h>
#include <linux/tee.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>

/* Provisional ABI of the reviewed qcom-qseecom-tee kernel series. */
#define FPC_QSEECOM_IMPL_ID 5u
#define FPC_QSEE_APP_NAME_MAX 64u
#define FPC_QSEE_MAX_BUFFER (1024u * 1024u)

struct shared_memory {
    void *address;
    size_t size;
    int id;
};

static void shared_release(struct shared_memory *memory)
{
    if (memory->address) {
        /* Auxiliary commands can contain authentication tokens. */
        explicit_bzero(memory->address, memory->size);
        munmap(memory->address, memory->size);
    }
    memset(memory, 0, sizeof(*memory));
}

static int shared_allocate(int fd, size_t size, struct shared_memory *memory)
{
    struct tee_ioctl_shm_alloc_data request = { .size = size };
    int shared_fd = ioctl(fd, TEE_IOC_SHM_ALLOC, &request);
    int error;

    if (shared_fd < 0)
        return -errno;
    if (request.size < size || request.size > SIZE_MAX) {
        close(shared_fd);
        return -EOVERFLOW;
    }
    memory->address = mmap(NULL, request.size, PROT_READ | PROT_WRITE,
                           MAP_SHARED, shared_fd, 0);
    error = errno;
    close(shared_fd);
    if (memory->address == MAP_FAILED) {
        memory->address = NULL;
        return -error;
    }
    memory->size = request.size;
    memory->id = request.id;
    memset(memory->address, 0, memory->size);
    return 0;
}

static int open_client(void)
{
    glob_t paths = {0};
    int result = -ENODEV;

    if (glob("/dev/tee[0-9]*", GLOB_NOSORT, NULL, &paths)) {
        globfree(&paths);
        return -ENODEV;
    }
    for (size_t i = 0; i < paths.gl_pathc; i++) {
        struct tee_ioctl_version_data version = {0};
        int fd = open(paths.gl_pathv[i], O_RDWR | O_CLOEXEC);

        if (fd < 0) {
            if (errno == EACCES || errno == EPERM)
                result = -errno;
            continue;
        }
        if (!ioctl(fd, TEE_IOC_VERSION, &version) &&
            version.impl_id == FPC_QSEECOM_IMPL_ID &&
            !(version.gen_caps & TEE_GEN_CAP_PRIVILEGED)) {
            result = fd;
            break;
        }
        close(fd);
    }
    globfree(&paths);
    return result;
}

int fpc_qsee_open(struct fpc_qsee_session *session, const char *app_name)
{
    struct shared_memory name = {0};
    struct tee_ioctl_open_session_arg *request;
    struct tee_ioctl_buf_data buffer;
    const size_t size = sizeof(*request) + sizeof(struct tee_ioctl_param);
    size_t length;
    int result;

    if (!session || !app_name)
        return -EINVAL;
    if (session->opened)
        return -EBUSY;
    length = strnlen(app_name, FPC_QSEE_APP_NAME_MAX);
    if (!length || length >= FPC_QSEE_APP_NAME_MAX || strchr(app_name, '/'))
        return -EINVAL;
    memset(session, 0, sizeof(*session));
    session->fd = -1;
    request = calloc(1, size);
    if (!request)
        return -ENOMEM;
    result = open_client();
    if (result < 0)
        goto out;
    session->fd = result;
    result = shared_allocate(session->fd, FPC_QSEE_APP_NAME_MAX, &name);
    if (result)
        goto out;
    memcpy(name.address, app_name, length + 1);
    request->num_params = 1;
    request->params[0].attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INPUT;
    request->params[0].b = length + 1;
    request->params[0].c = name.id;
    buffer.buf_ptr = (uintptr_t)request;
    buffer.buf_len = size;
    if (ioctl(session->fd, TEE_IOC_OPEN_SESSION, &buffer)) {
        result = -errno;
        goto out;
    }
    if (request->ret) {
        result = -EREMOTEIO;
        goto out;
    }
    session->id = request->session;
    session->opened = true;
out:
    shared_release(&name);
    free(request);
    if (result) {
        if (session->fd >= 0)
            close(session->fd);
        session->fd = -1;
        session->id = 0;
        session->opened = false;
    }
    return result;
}

void fpc_qsee_close(struct fpc_qsee_session *session)
{
    if (!session)
        return;
    if (session->opened && session->fd >= 0) {
        struct tee_ioctl_close_session_arg request = { .session = session->id };
        ioctl(session->fd, TEE_IOC_CLOSE_SESSION, &request);
        close(session->fd);
    }
    session->fd = -1;
    session->id = 0;
    session->opened = false;
}

int fpc_qsee_exchange(struct fpc_qsee_session *session,
                      const void *request_data, size_t request_len,
                      void *response, size_t response_len,
                      void *auxiliary, size_t auxiliary_len,
                      uint32_t pointer_offset)
{
    struct shared_memory message = {0}, extra = {0};
    struct tee_ioctl_invoke_arg *request;
    struct tee_ioctl_buf_data buffer;
    size_t response_offset, size;
    unsigned int count = auxiliary ? 4 : 2;
    int result;

    if (!session || session->fd < 0 || !session->opened || !request_data ||
        !request_len || !response || !response_len ||
        request_len > FPC_QSEE_MAX_BUFFER || response_len > FPC_QSEE_MAX_BUFFER ||
        auxiliary_len > FPC_QSEE_MAX_BUFFER || (!!auxiliary != !!auxiliary_len))
        return -EINVAL;
    if (auxiliary && (pointer_offset > request_len ||
                      request_len - pointer_offset < sizeof(uint64_t)))
        return -EINVAL;
    response_offset = (request_len + 63) & ~(size_t)63;
    size = sizeof(*request) + count * sizeof(struct tee_ioctl_param);
    request = calloc(1, size);
    if (!request)
        return -ENOMEM;
    result = shared_allocate(session->fd, response_offset + response_len, &message);
    if (result)
        goto out;
    memcpy(message.address, request_data, request_len);
    request->session = session->id;
    request->num_params = count;
    request->params[0].attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INPUT;
    request->params[0].b = request_len;
    request->params[0].c = message.id;
    request->params[1].attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_OUTPUT;
    request->params[1].a = response_offset;
    request->params[1].b = response_len;
    request->params[1].c = message.id;
    if (auxiliary) {
        result = shared_allocate(session->fd, auxiliary_len, &extra);
        if (result)
            goto out;
        memcpy(extra.address, auxiliary, auxiliary_len);
        request->params[2].attr = TEE_IOCTL_PARAM_ATTR_TYPE_VALUE_INPUT;
        request->params[2].a = pointer_offset;
        request->params[2].b = sizeof(uint64_t);
        request->params[3].attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INOUT;
        request->params[3].b = auxiliary_len;
        request->params[3].c = extra.id;
    }
    buffer.buf_ptr = (uintptr_t)request;
    buffer.buf_len = size;
    if (ioctl(session->fd, TEE_IOC_INVOKE, &buffer)) {
        result = -errno;
        goto out;
    }
    if (request->ret) {
        result = -EREMOTEIO;
        goto out;
    }
    memcpy(response, (char *)message.address + response_offset, response_len);
    if (auxiliary)
        memcpy(auxiliary, extra.address, auxiliary_len);
out:
    shared_release(&extra);
    shared_release(&message);
    free(request);
    return result;
}

int fpc_qsee_command(void *context, void *command, size_t command_len,
                     int32_t *outer_status)
{
    unsigned char request[64] = {0}, response[64] = {0};
    unsigned char *auxiliary;
    size_t padded;
    uint32_t word;
    int result;

    if (!command || !command_len || !outer_status || command_len > FPC_QSEE_MAX_BUFFER)
        return -EINVAL;
    *outer_status = -1;
    padded = (command_len + 4095) & ~(size_t)4095;
    auxiliary = calloc(1, padded);
    if (!auxiliary)
        return -ENOMEM;
    memcpy(auxiliary, command, command_len);
    word = htole32((uint32_t)padded);
    memcpy(request, &word, sizeof(word));
    result = fpc_qsee_exchange(context, request, sizeof(request), response,
                               sizeof(response), auxiliary, padded, 4);
    if (!result) {
        memcpy(&word, response, sizeof(word));
        *outer_status = (int32_t)le32toh(word);
        memcpy(command, auxiliary, command_len);
    }
    explicit_bzero(auxiliary, padded);
    free(auxiliary);
    return result;
}
