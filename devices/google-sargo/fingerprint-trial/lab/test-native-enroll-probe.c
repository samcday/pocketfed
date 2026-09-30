/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define FPC_AUTH_TESTING
#define main trial_main
#define sargo_gk_enroll_new mock_enroll
#include "native-enroll-probe.c"
#undef sargo_gk_enroll_new
#undef main
#include <assert.h>
#include <stdlib.h>

static unsigned calls, opens;
static bool fail_sync, fail_backend, bad_length;
static int secure_status;
int __real_fsync(int fd);
int __wrap_fsync(int fd) { if (fail_sync) { errno = EIO; return -1; } return __real_fsync(fd); }
int auth_backend_open(struct auth_backend *b, const volatile sig_atomic_t *s)
{ (void)b; assert(!*s); ++opens; return fail_backend ? -EIO : 0; }
void auth_backend_close(struct auth_backend *b) { (void)b; }
int auth_backend_status(struct sargo_gk_result r)
{ return r.transport ? r.transport : r.status ? -EACCES : 0; }
struct sargo_gk_result mock_enroll(struct sargo_gk *g, uint32_t uid,
    const void *secret, size_t n, void *handle, size_t cap, size_t *length)
{
    (void)g; assert(uid == 0x700003e8 && secret && n == 64 && cap == 58);
    ++calls;
    if (secure_status) { *length = 0; return (struct sargo_gk_result){0, secure_status}; }
    memset(handle, 0x53, cap); *length = bad_length ? 57 : cap;
    return (struct sargo_gk_result){0, 0};
}

int main(void)
{
    for (unsigned scenario = 0; scenario < 7; ++scenario) {
        char directory[] = "/tmp/fpc-lab-once-XXXXXX";
        assert(mkdtemp(directory));
        struct auth_store store = {.directory = -1, .lock = -1};
        struct auth_credential credential = {0};
        assert(!auth_store_open_test(&store, directory, getuid(), getgid()));
        if (scenario != 0) assert(!auth_store_begin(&store, LAB_UID, &credential));
        calls = opens = 0; fail_sync = scenario == 1; fail_backend = scenario == 2;
        secure_status = scenario == 3 ? -30 : 0; bad_length = scenario == 4;
        cancelled = scenario == 5;
        int result = enroll_once(&store);
        assert((result >= 0) == (scenario == 6));
        assert(calls == (scenario == 3 || scenario == 4 || scenario == 6));
        assert(opens == (scenario == 2 || scenario == 3 || scenario == 4 || scenario == 6));
        fail_sync = fail_backend = bad_length = false; secure_status = 0; cancelled = 0;
        if (scenario >= 1 && scenario != 5) {
            unsigned old = calls;
            assert(enroll_once(&store) < 0);
            assert(calls == old);
        }
        if (scenario == 6) assert(!auth_store_load(&store, LAB_UID, &credential));
        else if (scenario) assert(exists(&store, "uid-1000.intent") == 1);
        auth_credential_clear(&credential); auth_store_close(&store);
        /* These are synthetic credentials only. Keep failed-case receipts for
         * the test's lifetime, then remove exactly its known temporary files. */
        const char *files[] = {".lock", "uid-1000.intent", "uid-1000.credential", "uid-1000.lab-native-enroll-attempt-20260912"};
        for (unsigned i = 0; i < sizeof files / sizeof files[0]; ++i) {
            char path[160]; snprintf(path, sizeof path, "%s/%s", directory, files[i]); unlink(path);
        }
        assert(!rmdir(directory));
    }
    puts("PASS missing intent, failed receipt sync/backend, secure rejection, malformed handle, cancellation, durable success and replay refusal");
}
