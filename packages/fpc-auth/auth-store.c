/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define _GNU_SOURCE
#include "auth-store.h"
#include "gatekeeper-protocol.h"

#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#include <sys/file.h>
#include <sys/random.h>
#include <sys/stat.h>
#include <unistd.h>

#define RECORD_VERSION 1u
#define RECORD_INTENT 1u
#define RECORD_COMPLETE 2u

/* Byte arrays avoid ABI padding and host endian dependencies. Both records
 * contain the random credential, so an ambiguous enrollment retains recovery
 * material. The handle is opaque; an intent's handle is all zero.
 */
struct disk_record {
    unsigned char magic[8];
    unsigned char version[4];
    unsigned char kind[4];
    unsigned char linux_uid[4];
    unsigned char gatekeeper_uid[4];
    unsigned char secret[FPC_AUTH_SECRET_SIZE];
    unsigned char handle[FPC_AUTH_HANDLE_SIZE];
    unsigned char reserved[14];
};
_Static_assert(sizeof(struct disk_record) == 160, "credential file format");

static uint32_t load32(const unsigned char *p)
{
    uint32_t v;
    memcpy(&v, p, sizeof(v));
    return le32toh(v);
}

static void save32(unsigned char *p, uint32_t v)
{
    v = htole32(v);
    memcpy(p, &v, sizeof(v));
}

static bool all_zero(const unsigned char *p, size_t size)
{
    unsigned char bits = 0;
    while (size--)
        bits |= *p++;
    return bits == 0;
}

void auth_credential_clear(struct auth_credential *credential)
{
    if (credential)
        explicit_bzero(credential, sizeof(*credential));
}

static int check_directory(int fd, uid_t owner, gid_t group, bool final)
{
    struct stat st;
    if (fstat(fd, &st))
        return -errno;
    if (!S_ISDIR(st.st_mode) || st.st_uid != owner || st.st_gid != group ||
        (final ? (st.st_mode & 07777) != 0700 : (st.st_mode & 0022) != 0))
        return -EPERM;
    return 0;
}

static int check_regular(int fd, uid_t owner, gid_t group, off_t size)
{
    struct stat st;
    if (fstat(fd, &st))
        return -errno;
    if (!S_ISREG(st.st_mode) || st.st_uid != owner || st.st_gid != group ||
        (st.st_mode & 07777) != 0600 || st.st_nlink != 1)
        return -EPERM;
    if (size >= 0 && st.st_size != size)
        return -EUCLEAN;
    return 0;
}

static void store_init(struct auth_store *store)
{
    *store = (struct auth_store){ .directory = -1, .lock = -1 };
}

void auth_store_close(struct auth_store *store)
{
    if (!store)
        return;
    if (store->lock >= 0)
        close(store->lock);
    if (store->directory >= 0)
        close(store->directory);
    store_init(store);
}

static int lock_directory(struct auth_store *store, int directory,
                          uid_t owner, gid_t group)
{
    int rc;
    store->directory = directory;
    store->owner = owner;
    store->group = group;
    rc = check_directory(directory, owner, group, true);
    if (rc)
        goto fail;
    store->lock = openat(directory, ".lock",
        O_RDWR | O_CREAT | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK, 0600);
    if (store->lock < 0) {
        rc = -errno;
        goto fail;
    }
    rc = check_regular(store->lock, owner, group, 0);
    if (rc)
        goto fail;
    if (flock(store->lock, LOCK_EX | LOCK_NB)) {
        rc = errno == EWOULDBLOCK ? -EBUSY : -errno;
        goto fail;
    }
    return 0;
fail:
    auth_store_close(store);
    return rc;
}

int auth_store_open(struct auth_store *store)
{
    static const char *const components[] = { "var", "lib", "pocketfed-fpc-auth" };
    int fd, next, rc;
    if (!store)
        return -EINVAL;
    store_init(store);
    if (getuid() != 0 || geteuid() != 0 || getegid() != 0)
        return -EPERM;
    fd = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0)
        return -errno;
    rc = check_directory(fd, 0, 0, false);
    if (rc)
        goto fail;
    for (size_t i = 0; i < sizeof(components) / sizeof(components[0]); i++) {
        bool final = i == 2;
        if (final) {
            if (mkdirat(fd, components[i], 0700) && errno != EEXIST) {
                rc = -errno;
                goto fail;
            }
            /* Persist a newly created directory before provisioning state. */
            if (fsync(fd)) {
                rc = -errno;
                goto fail;
            }
        }
        next = openat(fd, components[i],
            O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
        if (next < 0) {
            rc = -errno;
            goto fail;
        }
        close(fd);
        fd = next;
        rc = check_directory(fd, 0, 0, final);
        if (rc)
            goto fail;
    }
    return lock_directory(store, fd, 0, 0);
fail:
    close(fd);
    return rc;
}

#ifdef FPC_AUTH_TESTING
int auth_store_open_test(struct auth_store *store, const char *path,
                         uid_t owner, gid_t group)
{
    int fd;
    store_init(store);
    fd = open(path, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0)
        return -errno;
    return lock_directory(store, fd, owner, group);
}
#endif

static int names(uint32_t uid, char intent[40], char complete[40])
{
    uint32_t mapped;
    int rc = sargo_gk_uid_for_linux(uid, &mapped);
    if (rc)
        return rc;
    snprintf(intent, 40, "uid-%u.intent", uid);
    snprintf(complete, 40, "uid-%u.credential", uid);
    return 0;
}

static int exists(struct auth_store *store, const char *name)
{
    struct stat st;
    if (!fstatat(store->directory, name, &st, AT_SYMLINK_NOFOLLOW))
        return 1;
    return errno == ENOENT ? 0 : -errno;
}

static int write_record(struct auth_store *store, const char *name,
                        const struct disk_record *record)
{
    size_t offset = 0;
    int fd = openat(store->directory, name,
        O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK, 0600);
    int rc;
    if (fd < 0)
        return -errno;
    rc = check_regular(fd, store->owner, store->group, 0);
    while (!rc && offset < sizeof(*record)) {
        ssize_t n = write(fd, (const unsigned char *)record + offset,
                          sizeof(*record) - offset);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            rc = n < 0 ? -errno : -EIO;
        else
            offset += (size_t)n;
    }
    if (!rc && fsync(fd))
        rc = -errno;
    if (close(fd) && !rc)
        rc = -errno;
    /* Never remove partial files, even if fsync fails. */
    if (!rc && fsync(store->directory))
        rc = -errno;
    return rc;
}

static int read_record(struct auth_store *store, const char *name,
                       struct disk_record *record)
{
    int fd = openat(store->directory, name,
        O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    size_t offset = 0;
    int rc;
    memset(record, 0, sizeof(*record));
    if (fd < 0)
        return -errno;
    rc = check_regular(fd, store->owner, store->group, sizeof(*record));
    while (!rc && offset < sizeof(*record)) {
        ssize_t n = read(fd, (unsigned char *)record + offset,
                         sizeof(*record) - offset);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            rc = n < 0 ? -errno : -EUCLEAN;
        else
            offset += (size_t)n;
    }
    if (!rc)
        rc = check_regular(fd, store->owner, store->group, sizeof(*record));
    close(fd);
    if (rc)
        explicit_bzero(record, sizeof(*record));
    return rc;
}

static void encode(struct disk_record *record, uint32_t kind,
                    const struct auth_credential *credential)
{
    memset(record, 0, sizeof(*record));
    memcpy(record->magic, "FPCAUTH1", 8);
    save32(record->version, RECORD_VERSION);
    save32(record->kind, kind);
    save32(record->linux_uid, credential->linux_uid);
    save32(record->gatekeeper_uid, credential->gatekeeper_uid);
    memcpy(record->secret, credential->secret, sizeof(record->secret));
    if (kind == RECORD_COMPLETE)
        memcpy(record->handle, credential->handle, sizeof(record->handle));
}

static int decode(const struct disk_record *record, uint32_t kind, uint32_t uid,
                   struct auth_credential *credential)
{
    uint32_t mapped;
    if (sargo_gk_uid_for_linux(uid, &mapped) ||
        memcmp(record->magic, "FPCAUTH1", 8) ||
        load32(record->version) != RECORD_VERSION ||
        load32(record->kind) != kind || load32(record->linux_uid) != uid ||
        load32(record->gatekeeper_uid) != mapped ||
        !all_zero(record->reserved, sizeof(record->reserved)) ||
        (kind == RECORD_INTENT && !all_zero(record->handle, sizeof(record->handle))) ||
        (kind == RECORD_COMPLETE && all_zero(record->handle + 1, 8)))
        return -EUCLEAN;
    credential->linux_uid = uid;
    credential->gatekeeper_uid = mapped;
    memcpy(credential->secret, record->secret, sizeof(credential->secret));
    memcpy(credential->handle, record->handle, sizeof(credential->handle));
    return 0;
}

int auth_store_load(struct auth_store *store, uint32_t uid,
                    struct auth_credential *credential)
{
    struct disk_record record;
    char intent[40], complete[40];
    int rc;
    if (!store || store->lock < 0 || !credential)
        return -EINVAL;
    auth_credential_clear(credential);
    rc = names(uid, intent, complete);
    if (rc)
        return rc;
    rc = exists(store, intent);
    if (rc)
        return rc > 0 ? -EINPROGRESS : rc;
    rc = read_record(store, complete, &record);
    if (!rc)
        rc = decode(&record, RECORD_COMPLETE, uid, credential);
    explicit_bzero(&record, sizeof(record));
    if (rc)
        auth_credential_clear(credential);
    return rc;
}

int auth_store_check_new(struct auth_store *store, uint32_t uid)
{
    char intent[40], complete[40];
    int rc;
    if (!store || store->lock < 0)
        return -EINVAL;
    rc = names(uid, intent, complete);
    if (rc)
        return rc;
    rc = exists(store, complete);
    if (rc)
        return rc > 0 ? -EEXIST : rc;
    rc = exists(store, intent);
    if (rc)
        return rc > 0 ? -EINPROGRESS : rc;
    return 0;
}

int auth_store_begin(struct auth_store *store, uint32_t uid,
                     struct auth_credential *credential)
{
    struct disk_record record;
    char intent[40], complete[40];
    size_t offset = 0;
    int rc;
    if (!credential)
        return -EINVAL;
    auth_credential_clear(credential);
    rc = auth_store_check_new(store, uid);
    if (rc)
        return rc;
    rc = names(uid, intent, complete);
    if (rc)
        return rc;
    credential->linux_uid = uid;
    rc = sargo_gk_uid_for_linux(uid, &credential->gatekeeper_uid);
    while (!rc && offset < sizeof(credential->secret)) {
        ssize_t n = getrandom(credential->secret + offset,
                              sizeof(credential->secret) - offset, 0);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            rc = n < 0 ? -errno : -EIO;
        else
            offset += (size_t)n;
    }
    if (!rc) {
        encode(&record, RECORD_INTENT, credential);
        rc = write_record(store, intent, &record);
        explicit_bzero(&record, sizeof(record));
    }
    if (rc)
        auth_credential_clear(credential);
    return rc;
}

int auth_store_commit(struct auth_store *store,
                      const struct auth_credential *credential)
{
    struct disk_record record;
    struct auth_credential original = { 0 };
    char intent[40], complete[40];
    int rc;
    if (!store || store->lock < 0 || !credential ||
        all_zero(credential->handle + 1, 8))
        return -EINVAL;
    rc = names(credential->linux_uid, intent, complete);
    if (rc)
        return rc;
    rc = read_record(store, intent, &record);
    if (!rc)
        rc = decode(&record, RECORD_INTENT, credential->linux_uid, &original);
    if (!rc && (original.gatekeeper_uid != credential->gatekeeper_uid ||
                memcmp(original.secret, credential->secret, sizeof(original.secret))))
        rc = -EUCLEAN;
    if (!rc) {
        encode(&record, RECORD_COMPLETE, credential);
        rc = write_record(store, complete, &record);
    }
    /* Once write_record succeeds, the completed credential and its directory
     * entry are durable: subsequent cleanup cannot undo that commit. A crash
     * before durable intent removal can block use, but cannot permit reenroll.
     */
    if (!rc && (unlinkat(store->directory, intent, 0) || fsync(store->directory)))
        rc = AUTH_STORE_COMMITTED_CLEANUP_PENDING;
    explicit_bzero(&record, sizeof(record));
    auth_credential_clear(&original);
    return rc;
}
