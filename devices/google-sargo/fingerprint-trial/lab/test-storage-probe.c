/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define main probe_main
#define sargo_gk_verify mock_verify
#include "storage-probe.c"
#undef main
#undef sargo_gk_verify
#include <assert.h>
#include <stdlib.h>

static unsigned calls, opens;
static bool fail_sync, fail_backend;
static int secure_status, transport_status;
int __real_fsync(int fd);
int __wrap_fsync(int fd) { if (fail_sync) { errno = EIO; return -1; } return __real_fsync(fd); }
int auth_backend_open(struct auth_backend *b, const volatile sig_atomic_t *s)
{ (void)b; assert(!*s); ++opens; return fail_backend ? -EIO : 0; }
void auth_backend_close(struct auth_backend *b) { (void)b; }
struct sargo_gk_result mock_verify(struct sargo_gk *g, uint32_t uid, uint64_t challenge,
    const void *handle, size_t n, const void *password, size_t m, unsigned char hat[SARGO_GK_HAT_SIZE])
{
    (void)g; assert(uid == 0x700004d2 && challenge == 1 && n == 58 && m == 1);
    for (size_t i = 0; i < n; ++i) assert(!((const unsigned char *)handle)[i]);
    assert(!*(const unsigned char *)password);
    ++calls; memset(hat, 0x53, SARGO_GK_HAT_SIZE);
    return (struct sargo_gk_result){transport_status, secure_status};
}
int main(void)
{
    assert(identity("androidboot.serialno=99NAY1AZG1 pocketfed.root_mode=usb pocketfed.liveboot=" PROBE_RUN));
    assert(!identity("androidboot.serialno=other pocketfed.root_mode=usb pocketfed.liveboot=" PROBE_RUN));
    assert(!identity("androidboot.serialno=99NAY1AZG1 pocketfed.root_mode=usb pocketfed.liveboot=other"));
    for (unsigned scenario = 0; scenario < 6; ++scenario) {
        char path[] = "/tmp/fpc-storage-probe-test-XXXXXX";
        assert(mkdtemp(path));
        int directory = open(path, O_RDONLY | O_DIRECTORY); assert(directory >= 0);
        calls = opens = 0; cancelled = scenario == 0;
        fail_sync = scenario == 1; fail_backend = scenario == 2;
        secure_status = scenario == 5 ? 0 : -30;
        transport_status = scenario == 3 ? -EIO : 0;
        int rc = probe_once(directory);
        assert((rc == 0) == (scenario == 4));
        assert(calls == (scenario >= 3));
        fail_sync = fail_backend = false; cancelled = 0;
        if (scenario) {
            unsigned old = calls;
            assert(probe_once(directory) < 0 && calls == old);
        }
        unlinkat(directory, "storage-probe-attempt", 0); close(directory);
        assert(!rmdir(path));
    }
    puts("PASS fixed identity and synthetic request; cancellation, receipt sync/backend/transport failure, rejection observation, unexpected success refusal and one-use guard");
}
