/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _GNU_SOURCE
#define FPC_AUTH_NO_MAIN
#include "auth-broker.c"

#include <assert.h>
#include <dirent.h>
#include <sys/wait.h>

static unsigned int fail_sync;
static unsigned int fail_write;
static bool fail_unlink;
enum fake_backend_mode { BACKEND_ABSENT, BACKEND_OK, ENROLL_ERROR, VERIFY_ERROR,
    VERIFY_THROTTLE, WRONG_TOKEN, VERSION_ERROR };
static enum fake_backend_mode fake_backend;
static unsigned int backend_opens, backend_closes, backend_enrolls, backend_verifies;
static unsigned char enrolled_secret[FPC_AUTH_SECRET_SIZE];

int __real_fsync(int fd);
ssize_t __real_write(int fd, const void *buffer, size_t size);
int __real_unlinkat(int fd, const char *name, int flags);

int __wrap_unlinkat(int fd, const char *name, int flags)
{
    if (fail_unlink) {
        fail_unlink = false;
        errno = EIO;
        return -1;
    }
    return __real_unlinkat(fd, name, flags);
}

int __wrap_fsync(int fd)
{
    if (fail_sync && --fail_sync == 0) {
        errno = EIO;
        return -1;
    }
    return __real_fsync(fd);
}

ssize_t __wrap_write(int fd, const void *buffer, size_t size)
{
    if (fail_write && --fail_write == 0) {
        errno = EIO;
        return -1;
    }
    if (fail_write && size > 7)
        size = 7;
    return __real_write(fd, buffer, size);
}

static bool zero_bytes(const void *buffer, size_t size)
{
    const unsigned char *p = buffer;
    while (size--)
        if (*p++)
            return false;
    return true;
}

static void temporary(char path[64])
{
    strcpy(path, "/tmp/pocketfed-fpc-auth-test-XXXXXX");
    assert(mkdtemp(path));
    assert(chmod(path, 0700) == 0);
}

static void cleanup(const char *path)
{
    DIR *directory = opendir(path);
    struct dirent *entry;
    assert(directory);
    while ((entry = readdir(directory))) {
        struct stat st;
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
            continue;
        assert(fstatat(dirfd(directory), entry->d_name, &st, AT_SYMLINK_NOFOLLOW) == 0);
        assert(unlinkat(dirfd(directory), entry->d_name,
                         S_ISDIR(st.st_mode) ? AT_REMOVEDIR : 0) == 0);
    }
    closedir(directory);
    assert(rmdir(path) == 0);
}

static void fixture_write(struct auth_store *store, const char *name,
                           const void *buffer, size_t size)
{
    int fd = openat(store->directory, name, O_CREAT | O_WRONLY | O_TRUNC | O_CLOEXEC, 0600);
    assert(fd >= 0);
    assert(write(fd, buffer, size) == (ssize_t)size);
    assert(close(fd) == 0);
}

static void fake_handle(struct auth_credential *credential)
{
    /* Unit-test data only. This is never sent to a TA or installed as state. */
    memset(credential->handle, 0x42, sizeof(credential->handle));
    credential->handle[0] = 0;
}

static void round_trip(void)
{
    char path[64];
    struct auth_store store, second;
    struct auth_credential original, loaded, changed;
    struct stat st;
    temporary(path);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == 0);
    assert(auth_store_open_test(&second, path, getuid(), getgid()) == -EBUSY);
    assert(auth_store_load(&store, 1000, &loaded) == -ENOENT);
    assert(auth_store_begin(&store, 1000, &original) == 0);
    assert(original.linux_uid == 1000 && original.gatekeeper_uid == 0x700003e8);
    assert(!zero_bytes(original.secret, sizeof(original.secret)));
    assert(zero_bytes(original.handle, sizeof(original.handle)));
    assert(fstatat(store.directory, "uid-1000.intent", &st, AT_SYMLINK_NOFOLLOW) == 0);
    assert(st.st_size == 160 && (st.st_mode & 07777) == 0600 && st.st_nlink == 1);
    assert(auth_store_begin(&store, 1000, &loaded) == -EINPROGRESS);
    assert(auth_store_load(&store, 1000, &loaded) == -EINPROGRESS);
    assert(zero_bytes(&loaded, sizeof(loaded)));
    fake_handle(&original);
    changed = original;
    changed.secret[0] ^= 1;
    assert(auth_store_commit(&store, &changed) == -EUCLEAN);
    changed = original;
    changed.gatekeeper_uid ^= 1;
    assert(auth_store_commit(&store, &changed) == -EUCLEAN);
    assert(auth_store_commit(&store, &original) == 0);
    assert(fstatat(store.directory, "uid-1000.intent", &st, AT_SYMLINK_NOFOLLOW) == -1 && errno == ENOENT);
    assert(auth_store_load(&store, 1000, &loaded) == 0);
    assert(memcmp(&original, &loaded, sizeof(original)) == 0);
    assert(auth_store_begin(&store, 1000, &loaded) == -EEXIST);
    assert(auth_store_begin(&store, SARGO_GK_MAX_LINUX_UID + 1, &loaded) == -EINVAL);
    assert(auth_store_load(&store, SARGO_GK_MAX_LINUX_UID + 1, &loaded) == -EINVAL);
    auth_store_close(&store);
    assert(auth_store_open_test(&second, path, getuid(), getgid()) == 0);
    assert(auth_store_load(&second, 1000, &loaded) == 0);
    assert(memcmp(&original, &loaded, sizeof(original)) == 0);
    auth_store_close(&second);
    auth_credential_clear(&original);
    auth_credential_clear(&loaded);
    auth_credential_clear(&changed);
    cleanup(path);
    puts("PASS durable round trip, UID mapping, exclusive lock and duplicate/incomplete refusal");
}

static void unsafe_directories_and_lock(void)
{
    char path[64], link_path[80];
    struct auth_store store;
    int fd;
    temporary(path);
    assert(auth_store_open_test(&store, path, getuid() + 1, getgid()) == -EPERM);
    assert(auth_store_open_test(&store, path, getuid(), getgid() + 1) == -EPERM);
    assert(chmod(path, 0770) == 0);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == -EPERM);
    assert(chmod(path, 0700) == 0);
    snprintf(link_path, sizeof(link_path), "%s-link", path);
    assert(symlink(path, link_path) == 0);
    assert(auth_store_open_test(&store, link_path, getuid(), getgid()) < 0);
    assert(unlink(link_path) == 0);
    fd = open(path, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    assert(fd >= 0);
    assert(symlinkat("/dev/null", fd, ".lock") == 0);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == -ELOOP);
    assert(unlinkat(fd, ".lock", 0) == 0);
    assert(mkfifoat(fd, ".lock", 0600) == 0);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == -EPERM);
    assert(unlinkat(fd, ".lock", 0) == 0);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == 0);
    assert(fchmod(store.lock, 0644) == 0);
    auth_store_close(&store);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == -EPERM);
    assert(fchmodat(fd, ".lock", 0600, 0) == 0);
    assert(linkat(fd, ".lock", fd, "lock-alias", 0) == 0);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == -EPERM);
    assert(unlinkat(fd, "lock-alias", 0) == 0);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == 0);
    assert(ftruncate(store.lock, 1) == 0);
    auth_store_close(&store);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == -EUCLEAN);
    close(fd);
    cleanup(path);
    puts("PASS directory/lock ownership, mode, symlink, hardlink, FIFO and length checks");
}

static void bad_credentials(void)
{
    char path[64];
    struct auth_store store;
    struct auth_credential original, loaded;
    unsigned char bytes[161], changed[160];
    int fd;
    temporary(path);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == 0);
    assert(auth_store_begin(&store, 7, &original) == 0);
    fake_handle(&original);
    assert(auth_store_commit(&store, &original) == 0);
    fd = openat(store.directory, "uid-7.credential", O_RDONLY | O_CLOEXEC);
    assert(fd >= 0 && read(fd, bytes, 160) == 160);
    close(fd);
    bytes[160] = 0;
    store.owner++;
    assert(auth_store_load(&store, 7, &loaded) == -EPERM);
    store.owner--;
    store.group++;
    assert(auth_store_load(&store, 7, &loaded) == -EPERM);
    store.group--;
    assert(fchmodat(store.directory, "uid-7.credential", 0644, 0) == 0);
    assert(auth_store_load(&store, 7, &loaded) == -EPERM);
    assert(fchmodat(store.directory, "uid-7.credential", 0600, 0) == 0);
    for (size_t length = 0; length <= 161; length++) {
        if (length == 160)
            continue;
        fixture_write(&store, "uid-7.credential", bytes, length);
        memset(&loaded, 0xa5, sizeof(loaded));
        assert(auth_store_load(&store, 7, &loaded) == -EUCLEAN);
        assert(zero_bytes(&loaded, sizeof(loaded)));
    }
    const size_t bad_offsets[] = { 0, 8, 12, 16, 20, 159 };
    for (size_t i = 0; i < sizeof(bad_offsets) / sizeof(bad_offsets[0]); i++) {
        memcpy(changed, bytes, sizeof(changed));
        changed[bad_offsets[i]] ^= 1;
        fixture_write(&store, "uid-7.credential", changed, sizeof(changed));
        assert(auth_store_load(&store, 7, &loaded) == -EUCLEAN);
    }
    memcpy(changed, bytes, sizeof(changed));
    memset(changed + 89, 0, 8); /* Handle SID, starting one byte into handle. */
    fixture_write(&store, "uid-7.credential", changed, sizeof(changed));
    assert(auth_store_load(&store, 7, &loaded) == -EUCLEAN);
    fixture_write(&store, "uid-7.credential", bytes, 160);
    assert(linkat(store.directory, "uid-7.credential", store.directory, "alias", 0) == 0);
    assert(auth_store_load(&store, 7, &loaded) == -EPERM);
    assert(unlinkat(store.directory, "alias", 0) == 0);
    assert(unlinkat(store.directory, "uid-7.credential", 0) == 0);
    assert(symlinkat("/dev/null", store.directory, "uid-7.credential") == 0);
    assert(auth_store_load(&store, 7, &loaded) == -ELOOP);
    assert(auth_store_begin(&store, 7, &loaded) == -EEXIST);
    assert(unlinkat(store.directory, "uid-7.credential", 0) == 0);
    assert(mkfifoat(store.directory, "uid-7.credential", 0600) == 0);
    assert(auth_store_load(&store, 7, &loaded) == -EPERM);
    assert(unlinkat(store.directory, "uid-7.credential", 0) == 0);
    assert(mkdirat(store.directory, "uid-7.credential", 0700) == 0);
    assert(auth_store_load(&store, 7, &loaded) == -EPERM);
    auth_store_close(&store);
    auth_credential_clear(&original);
    auth_credential_clear(&loaded);
    explicit_bzero(bytes, sizeof(bytes));
    explicit_bzero(changed, sizeof(changed));
    cleanup(path);
    puts("PASS credential metadata, every truncation, trailing byte, malformed header and zero SID rejection");
}

static void interrupted_provisioning(void)
{
    char path[64];
    struct auth_store store;
    struct auth_credential original, loaded;
    struct stat st;
    temporary(path);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == 0);
    fixture_write(&store, "uid-1.intent", "x", 1);
    assert(auth_store_begin(&store, 1, &loaded) == -EINPROGRESS);
    assert(auth_store_load(&store, 1, &loaded) == -EINPROGRESS);
    for (unsigned int sync = 1; sync <= 2; sync++) {
        uint32_t uid = 10 + sync;
        fail_sync = sync;
        assert(auth_store_begin(&store, uid, &loaded) == -EIO);
        assert(fail_sync == 0 && zero_bytes(&loaded, sizeof(loaded)));
        assert(auth_store_begin(&store, uid, &loaded) == -EINPROGRESS);
    }
    fail_write = 2;
    assert(auth_store_begin(&store, 20, &loaded) == -EIO);
    assert(fail_write == 0 && zero_bytes(&loaded, sizeof(loaded)));
    assert(fstatat(store.directory, "uid-20.intent", &st, AT_SYMLINK_NOFOLLOW) == 0);
    assert(st.st_size == 7);
    assert(auth_store_begin(&store, 20, &loaded) == -EINPROGRESS);
    for (unsigned int sync = 1; sync <= 3; sync++) {
        uint32_t uid = 30 + sync;
        assert(auth_store_begin(&store, uid, &original) == 0);
        fake_handle(&original);
        fail_sync = sync;
        assert(auth_store_commit(&store, &original) ==
               (sync == 3 ? AUTH_STORE_COMMITTED_CLEANUP_PENDING : -EIO));
        assert(fail_sync == 0);
        assert(auth_store_begin(&store, uid, &loaded) == -EEXIST);
        assert(auth_store_load(&store, uid, &loaded) == (sync == 3 ? 0 : -EINPROGRESS));
        if (sync == 3)
            assert(memcmp(&original, &loaded, sizeof(original)) == 0);
        else
            assert(auth_store_commit(&store, &original) == -EEXIST);
    }
    assert(auth_store_begin(&store, 35, &original) == 0);
    fake_handle(&original);
    fail_unlink = true;
    assert(auth_store_commit(&store, &original) == AUTH_STORE_COMMITTED_CLEANUP_PENDING);
    assert(!fail_unlink);
    assert(auth_store_load(&store, 35, &loaded) == -EINPROGRESS);
    assert(auth_store_begin(&store, 35, &loaded) == -EEXIST);
    assert(fstatat(store.directory, "uid-35.intent", &st, AT_SYMLINK_NOFOLLOW) == 0);
    assert(auth_store_begin(&store, 40, &original) == 0);
    fake_handle(&original);
    fixture_write(&store, "uid-40.credential", "partial", 7);
    assert(auth_store_commit(&store, &original) == -EEXIST);
    assert(auth_store_load(&store, 40, &loaded) == -EINPROGRESS);
    assert(fstatat(store.directory, "uid-40.credential", &st, AT_SYMLINK_NOFOLLOW) == 0 && st.st_size == 7);
    auth_store_close(&store);
    auth_credential_clear(&original);
    auth_credential_clear(&loaded);
    cleanup(path);
    puts("PASS all three commit sync failures, unlink failure, durable commit warning and retained ambiguous intents");
}

static void test_put32(unsigned char *p, uint32_t v)
{
    v = htole32(v);
    memcpy(p, &v, sizeof(v));
}

static void test_put64(unsigned char *p, uint64_t v)
{
    v = htole64(v);
    memcpy(p, &v, sizeof(v));
}

/* Only the test binary provides this synthetic transport. The daemon links
 * qsee-transport.c, which opens the actual public TEE device. */
int fpc_qsee_open(struct fpc_qsee_session *session, const char *name)
{
    assert(!session->opened && !strcmp(name, "keymaster64"));
    backend_opens++;
    if (fake_backend == BACKEND_ABSENT) return -ENODEV;
    session->fd = 77;
    session->id = 0;
    session->opened = true;
    return 0;
}
void fpc_qsee_close(struct fpc_qsee_session *session)
{
    if (session->opened) backend_closes++;
    *session = (struct fpc_qsee_session)FPC_QSEE_SESSION_INIT;
}
int fpc_qsee_exchange(struct fpc_qsee_session *session,
    const void *request, size_t request_len, void *response, size_t response_len,
    void *auxiliary, size_t auxiliary_len, uint32_t pointer_offset)
{
    const unsigned char *req = request;
    unsigned char *rsp = response;
    assert(session->opened && session->fd == 77);
    assert(request_len + response_len == SARGO_GK_BUFFER_SIZE);
    assert(!auxiliary && !auxiliary_len && !pointer_offset);
    memset(rsp, 0, response_len);
    switch (read32(req)) {
    case 0x200:
        assert(request_len == 4);
        test_put32(rsp + 4, 4);
        test_put32(rsp + 12, 4);
        test_put32(rsp + 16, fake_backend == VERSION_ERROR ? 166 : 165);
        return 0;
    case 0x207:
        assert(request_len == 24);
        assert(read32(req + 4) == 4 && read32(req + 8) == 5 &&
               read32(req + 12) == 4 && read32(req + 16) == 5 && !read32(req + 20));
        return 0;
    case 0x1001: {
        char intent[PATH_MAX];
        struct stat st;
        assert(test_store_path);
        assert(snprintf(intent, sizeof(intent), "%s/uid-1000.intent", test_store_path) < (int)sizeof(intent));
        assert(stat(intent, &st) == 0 && st.st_size == 160);
        assert(request_len == 96 && read32(req + 4) == 0x700003e8);
        assert(read32(req + 24) == 32 && read32(req + 28) == sizeof(enrolled_secret));
        backend_enrolls++;
        memcpy(enrolled_secret, req + 32, sizeof(enrolled_secret));
        if (fake_backend == ENROLL_ERROR) return -ETIMEDOUT;
        test_put32(rsp + 4, 12);
        test_put32(rsp + 8, SARGO_GK_HANDLE_SIZE);
        test_put64(rsp + 13, UINT64_C(0xaabbccdd12345678));
        return 0;
    }
    case 0x1002:
        assert(request_len == 154 && read32(req + 4) == 0x700003e8);
        assert(read32(req + 16) == 32 && read32(req + 20) == 58);
        assert(read32(req + 24) == 90 && read32(req + 28) == sizeof(enrolled_secret));
        assert(!memcmp(req + 90, enrolled_secret, sizeof(enrolled_secret)));
        backend_verifies++;
        if (fake_backend == VERIFY_ERROR) return -EIO;
        if (fake_backend == VERIFY_THROTTLE) { test_put32(rsp, 30000); return 0; }
        test_put32(rsp + 4, 12);
        test_put32(rsp + 8, SARGO_GK_HAT_SIZE);
        test_put64(rsp + 13, read64(req + 8) ^ (fake_backend == WRONG_TOKEN));
        test_put64(rsp + 21, UINT64_C(0xaabbccdd12345678));
        rsp[12 + 28] = 1; /* Big-endian HW_AUTH_PASSWORD. */
        memset(rsp + 12 + 37, 0x55, 32); /* Synthetic MAC, never used by hardware. */
        return 0;
    default: abort();
    }
}

static void request_fixture(struct fpc_auth_request *request)
{
    memcpy(request->magic, FPC_AUTH_MAGIC, 4);
    test_put32(request->version_le, FPC_AUTH_VERSION);
    test_put32(request->uid_le, 1000);
    test_put64(request->challenge_le, 0x123456789abcdef0ULL);
}

static void expect_status(const struct fpc_auth_request *request, int expected)
{
    struct fpc_auth_response response;
    memset(&response, 0xa5, sizeof(response));
    process_request(request, &response);
    assert((int32_t)read32(response.status_le) == expected);
    assert(zero_bytes(response.token, sizeof(response.token)));
}

static void broker_requests(void)
{
    char path[64];
    struct fpc_auth_request request;
    struct fpc_auth_response response;
    struct ucred peer = { .pid = 123, .uid = 0, .gid = 1000 };
    struct auth_backend backend = AUTH_BACKEND_INIT;
    uint32_t uid;
    int pair[2];
    struct auth_store store;
    struct auth_credential credential;
    temporary(path);
    test_store_path = path;
    assert(credentials_are_root(&peer, sizeof(peer)));
    assert(!credentials_are_root(&peer, sizeof(peer) - 1));
    peer.uid = 1000;
    assert(!credentials_are_root(&peer, sizeof(peer)));
    peer.uid = 0;
    peer.pid = 0;
    assert(!credentials_are_root(&peer, sizeof(peer)));
    request_fixture(&request);
    expect_status(&request, -ENOENT);
    request.magic[0] ^= 1;
    expect_status(&request, -EPROTO);
    request_fixture(&request);
    test_put32(request.version_le, 2);
    expect_status(&request, -EPROTO);
    request_fixture(&request);
    test_put32(request.uid_le, SARGO_GK_MAX_LINUX_UID + 1);
    expect_status(&request, -EINVAL);
    request_fixture(&request);
    test_put64(request.challenge_le, 0);
    expect_status(&request, -EINVAL);
    assert(!backend_opens); /* Bad/missing state cannot reach Keymaster. */
    assert(provision(1000) == -ENODEV);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == 0);
    assert(auth_store_check_new(&store, 1000) == 0);
    assert(provision(1000) == -EBUSY);
    assert(auth_store_begin(&store, 1000, &credential) == 0);
    auth_store_close(&store);
    assert(provision(1000) == -EINPROGRESS);
    request_fixture(&request);
    expect_status(&request, -EINPROGRESS);
    assert(auth_store_open_test(&store, path, getuid(), getgid()) == 0);
    fake_handle(&credential);
    assert(auth_store_commit(&store, &credential) == 0);
    auth_store_close(&store);
    assert(provision(1000) == -EEXIST);
    expect_status(&request, -ENODEV);
    auth_credential_clear(&credential);
    assert(auth_backend_open(&backend, NULL) == -ENODEV && zero_bytes(&backend.gk, sizeof(backend.gk)));
    assert(auth_backend_status((struct sargo_gk_result){ -ETIMEDOUT, 0 }) == -ETIMEDOUT);
    assert(auth_backend_status((struct sargo_gk_result){ 1, 0 }) == -EIO);
    assert(auth_backend_status((struct sargo_gk_result){ 0, 30000 }) == -EAGAIN);
    assert(auth_backend_status((struct sargo_gk_result){ 0, -30 }) == -EACCES);
    assert(auth_backend_status((struct sargo_gk_result){ 0, 0 }) == 0);
    assert(parse_uid("0", &uid) == 0 && uid == 0);
    assert(parse_uid("16777215", &uid) == 0 && uid == SARGO_GK_MAX_LINUX_UID);
    const char *bad[] = { "", "-1", "+1", "1 ", " 1", "1x", "16777216", "999999999999999999999999999" };
    for (size_t i = 0; i < sizeof(bad) / sizeof(bad[0]); i++)
        assert(parse_uid(bad[i], &uid) == -EINVAL);
    assert(socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, pair) == 0);
    assert(root_peer(pair[0]) == (getuid() == 0 ? 0 : -EACCES));
    request_fixture(&request);
    assert(send(pair[1], &request, sizeof(request), MSG_NOSIGNAL) == sizeof(request));
    serve_connection(pair[0]);
    assert(recv(pair[1], &response, sizeof(response), MSG_WAITALL) == sizeof(response));
    assert((int32_t)read32(response.status_le) == (getuid() == 0 ? -ENODEV : -EACCES));
    assert(zero_bytes(response.token, sizeof(response.token)));
    close(pair[0]);
    close(pair[1]);
    test_store_path = NULL;
    cleanup(path);
    puts("PASS root peer credentials, wire protocol, zero-token failures and missing-backend refusal");
}

static void broker_credential_lifecycle(void)
{
    char path[64];
    struct fpc_auth_request request;
    struct fpc_auth_response response;
    unsigned int before;
    temporary(path);
    test_store_path = path;
    fake_backend = VERSION_ERROR;
    assert(provision(1000) == -EPROTO);
    struct auth_store store;
    assert(!auth_store_open_test(&store, path, getuid(), getgid()));
    assert(!auth_store_check_new(&store, 1000)); /* No intent before negotiation. */
    auth_store_close(&store);
    fake_backend = BACKEND_OK;
    assert(provision(1000) == 0 && backend_enrolls == 1);
    before = backend_opens;
    assert(provision(1000) == -EEXIST && backend_opens == before);
    request_fixture(&request);
    process_request(&request, &response);
    assert(!read32(response.status_le) && backend_verifies == 1);
    assert(!sargo_gk_check_token(response.token, read64(request.challenge_le)));
    const enum fake_backend_mode failures[] = { VERIFY_ERROR, VERIFY_THROTTLE, WRONG_TOKEN };
    const int errors[] = { -EIO, -EAGAIN, -EPROTO };
    for (size_t i = 0; i < sizeof(failures) / sizeof(failures[0]); i++) {
        fake_backend = failures[i];
        before = backend_verifies;
        expect_status(&request, errors[i]);
        assert(backend_verifies == before + 1); /* Never automatically retry. */
    }
    test_store_path = NULL;
    cleanup(path);

    temporary(path);
    test_store_path = path;
    fake_backend = ENROLL_ERROR;
    assert(provision(1000) == -ETIMEDOUT);
    before = backend_opens;
    assert(provision(1000) == -EINPROGRESS && backend_opens == before);
    expect_status(&request, -EINPROGRESS);
    assert(backend_opens == before);
    test_store_path = NULL;
    cleanup(path);
    explicit_bzero(enrolled_secret, sizeof(enrolled_secret));
    explicit_bzero(&response, sizeof(response));
    fake_backend = BACKEND_ABSENT;
    puts("PASS broker provisioning/token integration, retained ambiguous intent and no credential replacement");
}

static void socket_deadlines(void)
{
    int pair[2], status;
    unsigned char buffer[20] = { 0 };
    int64_t start, elapsed;
    pid_t child;
    assert(socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, pair) == 0);
    start = monotonic_ms();
    assert(transfer(pair[0], buffer, sizeof(buffer), false, start + 30) == -ETIMEDOUT);
    elapsed = monotonic_ms() - start;
    assert(elapsed >= 20 && elapsed < 1000);
    stopping = 1;
    assert(transfer(pair[0], buffer, sizeof(buffer), false, monotonic_ms() + 1000) == -ECANCELED);
    stopping = 0;
    assert(send(pair[1], "abc", 3, MSG_NOSIGNAL) == 3);
    assert(shutdown(pair[1], SHUT_WR) == 0);
    assert(transfer(pair[0], buffer, sizeof(buffer), false, monotonic_ms() + 1000) == -ECONNRESET);
    close(pair[1]);
    assert(transfer(pair[0], buffer, sizeof(buffer), true, monotonic_ms() + 1000) < 0);
    close(pair[0]);
    assert(socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, pair) == 0);
    child = fork();
    assert(child >= 0);
    if (!child) {
        const struct timespec delay = { .tv_nsec = 20000000 };
        close(pair[0]);
        for (size_t i = 0; i < sizeof(buffer); i++) {
            if (send(pair[1], "x", 1, MSG_NOSIGNAL) != 1)
                break;
            nanosleep(&delay, NULL);
        }
        close(pair[1]);
        _exit(0);
    }
    close(pair[1]);
    start = monotonic_ms();
    assert(transfer(pair[0], buffer, sizeof(buffer), false, start + 60) == -ETIMEDOUT);
    elapsed = monotonic_ms() - start;
    assert(elapsed >= 50 && elapsed < 1000);
    close(pair[0]);
    assert(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    puts("PASS absolute socket deadline, slow sender, cancellation, truncation and disconnected writer");
}

int main(void)
{
    umask(0077);
    round_trip();
    unsafe_directories_and_lock();
    bad_credentials();
    interrupted_provisioning();
    broker_requests();
    broker_credential_lifecycle();
    socket_deadlines();
    return 0;
}
