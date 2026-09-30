/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _GNU_SOURCE
#include "auth-broker.h"
#include "auth-store.h"
#include "auth-backend.h"
#include "gatekeeper-protocol.h"

#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

_Static_assert(FPC_AUTH_HANDLE_SIZE == SARGO_GK_HANDLE_SIZE, "handle ABI");
_Static_assert(FPC_AUTH_TOKEN_SIZE == SARGO_GK_HAT_SIZE, "token ABI");

static volatile sig_atomic_t stopping;

#ifdef FPC_AUTH_TESTING
static const char *test_store_path;
#endif

static int open_store(struct auth_store *store)
{
#ifdef FPC_AUTH_TESTING
    if (test_store_path)
        return auth_store_open_test(store, test_store_path, getuid(), getgid());
#endif
    return auth_store_open(store);
}

static uint32_t read32(const unsigned char *p)
{
    uint32_t v;
    memcpy(&v, p, sizeof(v));
    return le32toh(v);
}

static uint64_t read64(const unsigned char *p)
{
    uint64_t v;
    memcpy(&v, p, sizeof(v));
    return le64toh(v);
}

static void write_status(struct fpc_auth_response *response, int status)
{
    uint32_t wire = htole32((uint32_t)(int32_t)status);
    if (status)
        explicit_bzero(response->token, sizeof(response->token));
    memcpy(response->status_le, &wire, sizeof(wire));
}

static int make_token(uint32_t uid, uint64_t challenge,
                      unsigned char token[FPC_AUTH_TOKEN_SIZE])
{
    struct auth_credential credential = { 0 };
    struct auth_store store = { .directory = -1, .lock = -1 };
    struct auth_backend backend = AUTH_BACKEND_INIT;
    uint32_t gatekeeper_uid;
    int rc;

    explicit_bzero(token, FPC_AUTH_TOKEN_SIZE);
    rc = sargo_gk_uid_for_linux(uid, &gatekeeper_uid);
    if (rc || !challenge)
        return -EINVAL;
    rc = open_store(&store);
    if (rc)
        goto out;
    rc = auth_store_load(&store, uid, &credential);
    if (rc)
        goto out;
    if (credential.gatekeeper_uid != gatekeeper_uid) {
        rc = -EUCLEAN;
        goto out;
    }
    rc = auth_backend_open(&backend, &stopping);
    if (rc)
        goto out;
    /* The shared codec binds challenge, password HAT type and SID to this
     * exact opaque handle. The FPC TA must still authenticate the HMAC.
     */
    rc = auth_backend_status(sargo_gk_verify(&backend.gk, gatekeeper_uid, challenge,
        credential.handle, sizeof(credential.handle),
        credential.secret, sizeof(credential.secret), token));
out:
    if (rc)
        explicit_bzero(token, FPC_AUTH_TOKEN_SIZE);
    auth_credential_clear(&credential);
    auth_backend_close(&backend);
    auth_store_close(&store);
    return rc;
}

static int provision(uint32_t uid)
{
    struct auth_credential credential = { 0 };
    struct auth_store store = { .directory = -1, .lock = -1 };
    struct auth_backend backend = AUTH_BACKEND_INIT;
    uint32_t mapped;
    size_t handle_len = 0;
    const char *phase = "opening state";
    int rc = sargo_gk_uid_for_linux(uid, &mapped);
    if (rc)
        return rc;
    /* Hold the machine-wide transaction lock during negotiation as well. */
    rc = open_store(&store);
    if (rc)
        goto out;
    phase = "checking unused native UID";
    rc = auth_store_check_new(&store, uid);
    if (rc)
        goto out;
    /* Prepare MUST NOT enroll or replace a secure credential. */
    phase = "preparing Keymaster";
    rc = auth_backend_open(&backend, &stopping);
    if (rc)
        goto out;
    if (stopping) {
        rc = -ECANCELED;
        goto out;
    }
    phase = "persisting provisioning intent";
    rc = auth_store_begin(&store, uid, &credential);
    if (rc)
        goto out;
    if (stopping) {
        rc = -ECANCELED;
        goto out;
    }
    /* The intent (including random secret) is fsynced before this call.
     * Any transport, TA, response-validation or persistence failure retains
     * the intent. There is no replacement or automatic retry path.
     */
    phase = "enrolling Gatekeeper credential";
    struct sargo_gk_result enrollment = sargo_gk_enroll_new(&backend.gk, mapped,
        credential.secret, sizeof(credential.secret),
        credential.handle, sizeof(credential.handle), &handle_len);
    rc = auth_backend_status(enrollment);
    if (rc)
        /* Status metadata only: never log credential, handle or reply bytes.
         * Keep the caller-facing errno mapping while preserving diagnosis of
         * this non-retryable, intent-bearing operation in the service journal.
         */
        fprintf(stderr, "Gatekeeper enrollment failed: transport=%d secure_status=%d.\n",
                enrollment.transport, enrollment.status);
    if (rc)
        goto out;
    if (handle_len != sizeof(credential.handle)) {
        rc = -EPROTO;
        goto out;
    }
    phase = "committing credential";
    rc = auth_store_commit(&store, &credential);
out:
    if (rc < 0)
        fprintf(stderr, "Provisioning stopped at %s: error=%d.\n", phase, rc);
    auth_credential_clear(&credential);
    auth_backend_close(&backend);
    auth_store_close(&store);
    return rc;
}

static void process_request(const struct fpc_auth_request *request,
                            struct fpc_auth_response *response)
{
    int rc;
    memset(response, 0, sizeof(*response));
    if (memcmp(request->magic, FPC_AUTH_MAGIC, sizeof(request->magic)) ||
        read32(request->version_le) != FPC_AUTH_VERSION)
        rc = -EPROTO;
    else
        rc = make_token(read32(request->uid_le), read64(request->challenge_le),
                        response->token);
    write_status(response, rc);
}

static int64_t monotonic_ms(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now))
        return -errno;
    return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static int wait_io(int fd, short events, int64_t deadline)
{
    struct pollfd pfd = { .fd = fd, .events = events };
    for (;;) {
        int64_t now, left;
        int rc;
        if (stopping)
            return -ECANCELED;
        now = monotonic_ms();
        if (now < 0)
            return (int)now;
        left = deadline - now;
        if (left <= 0)
            return -ETIMEDOUT;
        rc = poll(&pfd, 1, left > INT_MAX ? INT_MAX : (int)left);
        if (rc < 0 && errno == EINTR)
            continue;
        if (rc < 0)
            return -errno;
        if (!rc)
            return -ETIMEDOUT;
        if (pfd.revents & POLLNVAL)
            return -EBADF;
        if (pfd.revents & (events | POLLHUP | POLLERR))
            return 0;
    }
}

static int transfer(int fd, void *buffer, size_t size, bool send_data,
                     int64_t deadline)
{
    size_t offset = 0;
    while (offset < size) {
        ssize_t n;
        int rc = wait_io(fd, send_data ? POLLOUT : POLLIN, deadline);
        if (rc)
            return rc;
        if (send_data)
            n = send(fd, (unsigned char *)buffer + offset, size - offset,
                     MSG_DONTWAIT | MSG_NOSIGNAL);
        else
            n = recv(fd, (unsigned char *)buffer + offset, size - offset,
                     MSG_DONTWAIT);
        if (n < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK))
            continue;
        if (n <= 0)
            return n < 0 ? -errno : -ECONNRESET;
        offset += (size_t)n;
    }
    return 0;
}

static bool credentials_are_root(const struct ucred *peer, socklen_t size)
{
    return size == sizeof(*peer) && peer->uid == 0 && peer->pid > 0;
}

static int root_peer(int fd)
{
    struct ucred peer = { 0 };
    socklen_t size = sizeof(peer);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &size))
        return -errno;
    return credentials_are_root(&peer, size) ? 0 : -EACCES;
}

static void serve_connection(int fd)
{
    struct fpc_auth_request request = { 0 };
    struct fpc_auth_response response = { 0 };
    int64_t now = monotonic_ms();
    int rc;
    if (now < 0)
        return;
    /* A single absolute deadline bounds all socket reads and writes, so a
     * client cannot extend the window by sending one byte at a time.
     * A future synchronous secure-world call needs its own cancellation
     * design; this deadline does not claim to interrupt an in-flight SCM.
     */
    int64_t deadline = now + FPC_AUTH_TIMEOUT_MS;
    rc = root_peer(fd);
    if (!rc)
        rc = transfer(fd, &request, sizeof(request), false, deadline);
    if (!rc) {
        unsigned char extra;
        ssize_t n = recv(fd, &extra, 1, MSG_PEEK | MSG_DONTWAIT);
        if (n > 0)
            rc = -EPROTO;
        else if (n < 0 && errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            rc = -errno;
    }
    if (!rc && !stopping)
        process_request(&request, &response);
    else
        write_status(&response, rc ? rc : -ECANCELED);
    (void)transfer(fd, &response, sizeof(response), true, deadline);
    explicit_bzero(&request, sizeof(request));
    explicit_bzero(&response, sizeof(response));
}

static int parse_uid(const char *text, uint32_t *uid)
{
    uint64_t value = 0;
    if (!text || !*text)
        return -EINVAL;
    for (const unsigned char *p = (const unsigned char *)text; *p; p++) {
        if (*p < '0' || *p > '9')
            return -EINVAL;
        value = value * 10 + (*p - '0');
        if (value > SARGO_GK_MAX_LINUX_UID)
            return -EINVAL;
    }
    *uid = (uint32_t)value;
    return 0;
}

#ifndef FPC_AUTH_NO_MAIN
static void stop_handler(int signo)
{
    (void)signo;
    stopping = 1;
}

static int listening_socket(void)
{
    const char *pid = getenv("LISTEN_PID"), *fds = getenv("LISTEN_FDS");
    struct sockaddr_un address = { 0 };
    socklen_t size = sizeof(address);
    int type = 0, listening = 0, directory;
    struct stat st;
    char expected_pid[32];
    snprintf(expected_pid, sizeof(expected_pid), "%ld", (long)getpid());
    if (!pid || strcmp(pid, expected_pid) || !fds || strcmp(fds, "1"))
        return -EINVAL;
    unsetenv("LISTEN_PID");
    unsetenv("LISTEN_FDS");
    unsetenv("LISTEN_FDNAMES");
    if (getsockname(3, (struct sockaddr *)&address, &size) ||
        address.sun_family != AF_UNIX ||
        size != offsetof(struct sockaddr_un, sun_path) + sizeof(FPC_AUTH_SOCKET_PATH) ||
        memcmp(address.sun_path, FPC_AUTH_SOCKET_PATH, sizeof(FPC_AUTH_SOCKET_PATH)))
        return -EINVAL;
    size = sizeof(type);
    if (getsockopt(3, SOL_SOCKET, SO_TYPE, &type, &size) || type != SOCK_STREAM)
        return -EINVAL;
    size = sizeof(listening);
    if (getsockopt(3, SOL_SOCKET, SO_ACCEPTCONN, &listening, &size) || !listening)
        return -EINVAL;
    directory = open("/run/pocketfed-fpc-auth",
        O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (directory < 0)
        return -errno;
    if (fstat(directory, &st) || !S_ISDIR(st.st_mode) ||
        st.st_uid || st.st_gid || (st.st_mode & 07777) != 0700) {
        close(directory);
        return -EPERM;
    }
    if (fstatat(directory, "token.sock", &st, AT_SYMLINK_NOFOLLOW) ||
        !S_ISSOCK(st.st_mode) || st.st_uid || st.st_gid ||
        (st.st_mode & 07777) != 0600) {
        close(directory);
        return -EPERM;
    }
    close(directory);
    int flags = fcntl(3, F_GETFL);
    if (flags < 0 || fcntl(3, F_SETFL, flags | O_NONBLOCK) ||
        fcntl(3, F_SETFD, FD_CLOEXEC))
        return -errno;
    return 3;
}

static int serve(void)
{
    int listener = listening_socket();
    if (listener < 0)
        return listener;
    while (!stopping) {
        struct pollfd pfd = { .fd = listener, .events = POLLIN };
        int fd, rc = poll(&pfd, 1, -1);
        if (rc < 0 && errno == EINTR)
            continue;
        if (rc < 0)
            return -errno;
        if (pfd.revents & (POLLERR | POLLHUP | POLLNVAL))
            return -EIO;
        if (!(pfd.revents & POLLIN))
            continue;
        fd = accept4(listener, NULL, NULL, SOCK_CLOEXEC | SOCK_NONBLOCK);
        if (fd < 0 && (errno == EINTR || errno == EAGAIN))
            continue;
        if (fd < 0)
            return -errno;
        serve_connection(fd);
        close(fd);
    }
    return 0;
}

int main(int argc, char **argv)
{
    const struct rlimit no_core = { 0, 0 };
    struct sigaction action = { .sa_handler = stop_handler };
    uint32_t uid;
    int rc;
    if (argc == 2 && !strcmp(argv[1], "--help")) {
        puts("Usage: pocketfed-fpc-auth --serve\n"
             "       pocketfed-fpc-auth provision LINUX_UID\n"
             "Provisioning requires the reviewed kernel, ready listeners and resident keymaster64.");
        return 0;
    }
    if (getuid() || geteuid() || getegid()) {
        fputs("This service and provisioning command require root.\n", stderr);
        return 1;
    }
    umask(0077);
    if (setrlimit(RLIMIT_CORE, &no_core) || prctl(PR_SET_DUMPABLE, 0)) {
        fputs("Cannot disable credential-bearing core dumps.\n", stderr);
        return 1;
    }
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGTERM, &action, NULL) || sigaction(SIGINT, &action, NULL))
        return 1;
    if (argc == 2 && !strcmp(argv[1], "--serve")) {
        rc = serve();
        if (rc)
            fprintf(stderr, "Broker startup or listener failed: %s.\n", strerror(-rc));
    } else if (argc == 3 && !strcmp(argv[1], "provision") && !parse_uid(argv[2], &uid)) {
        rc = provision(uid);
        if (rc == AUTH_STORE_COMMITTED_CLEANUP_PENDING) {
            fputs("Credential committed. Intent cleanup could not be confirmed; preserve state for recovery. Do not provision again.\n",
                  stderr);
            rc = 0;
        }
        else if (rc)
            fprintf(stderr, "Provisioning failed: %s. Preserve any intent; do not retry or remove state.\n",
                    strerror(-rc));
        else
            puts("Native fingerprint service credential provisioned.");
    } else {
        fputs("Usage: pocketfed-fpc-auth --serve | provision LINUX_UID\n", stderr);
        return 2;
    }
    return rc ? 1 : 0;
}
#endif
