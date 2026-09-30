/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define FPC_AUTH_TESTING
#define main recovery_main
#include "recover-storage-once.c"
#undef main
#include <assert.h>
#include <stdlib.h>

static unsigned opens, calls, syncs, fail_sync_at;
static bool fail_backend, cancel_backend, reject, malformed;
static unsigned char expected_secret[64];
int __real_fsync(int fd);
int __wrap_fsync(int fd)
{
    if (++syncs == fail_sync_at) { errno = EIO; return -1; }
    return __real_fsync(fd);
}
static int exchange(void *ctx, const void *request, size_t n, void *response, size_t m)
{
    (void)ctx; const unsigned char *q = request; unsigned char *r = response;
    assert(n == 96 && m == 40864 && load32(q) == 0x1001 && load32(q+4) == 0x700003e8);
    assert(!load32(q+8) && !load32(q+12) && !load32(q+16) && !load32(q+20));
    assert(load32(q+24) == 32 && load32(q+28) == 64);
    assert(!memcmp(q+32, expected_secret, 64)); ++calls;
    memset(r, 0, m);
    if (reject) { save32(r, (uint32_t)-30); return 0; }
    save32(r+4, 12); save32(r+8, malformed ? 57 : 58); r[13] = 42;
    return 0;
}
int auth_backend_open(struct auth_backend *b, const volatile sig_atomic_t *s)
{
    assert(!*s); ++opens;
    if (cancel_backend) cancelled = 1;
    b->gk.context = NULL; b->gk.exchange = exchange;
    return fail_backend ? -EIO : 0;
}
void auth_backend_close(struct auth_backend *b) { explicit_bzero(&b->gk, sizeof b->gk); }
int auth_backend_status(struct sargo_gk_result r)
{ return r.transport ? r.transport : r.status ? -EACCES : 0; }

static void scenario(unsigned mode)
{
    char path[] = "/tmp/sargo-daily-recovery-test-XXXXXX"; assert(mkdtemp(path));
    struct auth_store s = {.directory=-1, .lock=-1};
    struct auth_credential initial = {0}, loaded = {0};
    struct disk_record before = {0}, after = {0};
    assert(!auth_store_open_test(&s, path, getuid(), getgid()));
    assert(!auth_store_begin(&s, DAILY_UID, &initial));
    memcpy(expected_secret, initial.secret, sizeof expected_secret);
    assert(!read_record(&s, "uid-1000.intent", &before));
    if (mode != 1) {
        assert(!retain_new(&s, prior_name, prior_note, sizeof prior_note - 1));
        if (mode == 2) { int fd = openat(s.directory, prior_name, O_WRONLY); assert(fd >= 0); assert(write(fd,"!",1)==1); close(fd); }
        if (mode == 3) assert(!fchmodat(s.directory, prior_name, 0644, 0));
        if (mode == 4) assert(!linkat(s.directory,prior_name,s.directory,"extra-link",0));
    }
    if (mode == 5) { initial.handle[1] = 42; assert(!auth_store_commit(&s, &initial)); }
    if (mode == 6) { int fd=openat(s.directory,"uid-1000.intent",O_WRONLY|O_TRUNC); assert(fd>=0); close(fd); }
    if (mode == 7) assert(!retain_new(&s, receipt_name, "partial", 7));
    if (mode == 8) assert(!retain_new(&s, backup_name, &before, sizeof before));
    if (mode == 9) cancelled = 1;
    opens=calls=syncs=0; fail_sync_at = mode >= 10 && mode <= 13 ? mode-9 : 0;
    fail_backend = mode == 14; cancel_backend = mode == 15; reject = mode == 16; malformed = mode == 17;
    int rc = recover_once(&s);
    assert((rc >= 0) == (mode == 0));
    assert(calls == (mode == 0 || mode == 16 || mode == 17));
    assert(opens == (mode == 0 || mode >= 14));
    if (mode == 0) {
        assert(!auth_store_load(&s, DAILY_UID, &loaded));
        assert(!memcmp(loaded.secret, expected_secret, 64));
    }
    if (mode == 0 || mode >= 14) {
        assert(!read_record(&s, backup_name, &after));
        assert(!memcmp(&before, &after, sizeof before));
    }
    if (mode >= 10 || mode == 0) assert(!check_history(&s));
    if (mode >= 10) {
        assert(!read_record(&s,"uid-1000.intent",&after));
        assert(!memcmp(&before,&after,sizeof before));
    }
    unsigned old_opens=opens, old_calls=calls;
    fail_sync_at=0; fail_backend=cancel_backend=reject=malformed=false; cancelled=0;
    /* A pre-call cancellation intentionally consumes no attempt. Every other
     * rejected state and every consumed attempt still refuses replay. */
    if (mode != 9) { assert(recover_once(&s)<0); assert(opens==old_opens && calls==old_calls); }
    const char *files[]={".lock","uid-1000.intent","uid-1000.credential",prior_name,receipt_name,backup_name,"extra-link"};
    for (unsigned i=0;i<sizeof files/sizeof files[0];++i) unlinkat(s.directory,files[i],0);
    auth_store_close(&s); assert(!rmdir(path));
    auth_credential_clear(&initial); auth_credential_clear(&loaded);
    explicit_bzero(&before,sizeof before); explicit_bzero(&after,sizeof after);
    explicit_bzero(expected_secret,sizeof expected_secret);
}
int main(void)
{
    for(unsigned mode=0;mode<18;++mode) scenario(mode);
    puts("PASS: fixed native UID and original secret on wire; exact prior receipt; unsafe/completed/partial state rejection; four durability failures; cancellation; secure failure; malformed handle; preserved original intent; success and replay refusal");
}
