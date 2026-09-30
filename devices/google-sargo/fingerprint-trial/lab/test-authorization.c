/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define main authorization_main
#define sargo_gk_verify mock_verify
#include "check-authorization.c"
#undef main
#undef sargo_gk_verify
#include <assert.h>
#include <stdlib.h>

static unsigned scenario, verifies, authorizes, backend_opens;
int __real_fsync(int);
int __wrap_fsync(int fd) { if (scenario==2) { errno=EIO; return -1; } return __real_fsync(fd); }
int auth_store_open(struct auth_store *s) { (void)s; return -ENOSYS; }
void auth_store_close(struct auth_store *s) { (void)s; }
int auth_store_load(struct auth_store *s,uint32_t uid,struct auth_credential *c)
{
    (void)s; assert(uid==1234);
    if (scenario==1) return -EUCLEAN;
    c->linux_uid=1234; c->gatekeeper_uid=0x700004d2;
    memset(c->secret,0x55,sizeof c->secret); memset(c->handle,0x66,sizeof c->handle);
    return 0;
}
void auth_credential_clear(struct auth_credential *c) { explicit_bzero(c,sizeof *c); }
int auth_backend_open(struct auth_backend *b,const volatile sig_atomic_t *s)
{ (void)b; assert(!*s); ++backend_opens; return scenario==3 ? -EIO : 0; }
void auth_backend_close(struct auth_backend *b) { (void)b; }
int auth_backend_status(struct sargo_gk_result r) { return r.transport ? r.transport : r.status ? -EACCES : 0; }
int fpc_sensor_open(struct fpc_sensor_device *s,const char *p)
{ assert(!strcmp(p,"/dev/fpc1020")); s->fd=42; return 0; }
void fpc_sensor_close(struct fpc_sensor_device *s) { s->fd=-1; }
int fpc_sensor_reset(struct fpc_sensor_device *s) { assert(s->fd==42); return 0; }
int fpc_qsee_open(struct fpc_qsee_session *s,const char *app)
{ assert(!strcmp(app,FPC_QSEE_APP_NAME)); s->opened=true; return 0; }
void fpc_qsee_close(struct fpc_qsee_session *s) { s->opened=false; }
int fpc_qsee_exchange(struct fpc_qsee_session *s,const void *request,size_t n,
    void *response,size_t m,void *aux,size_t aux_n,uint32_t offset)
{
    (void)s; assert(n==64 && m==960 && !aux && !aux_n && !offset);
    assert(fpc_get_le32(request)==0x205 && fpc_get_le32((const char *)request+4)==2);
    memset(response,0,m);
    fpc_put_le32((char *)response+4,12); fpc_put_le32((char *)response+8,scenario==4 ? 0 : 152);
    return 0;
}
int fpc_qsee_command(void *ctx,void *data,size_t n,int32_t *outer)
{
    (void)ctx; assert(n>=24);
    uint32_t target=fpc_get_le32(data), cmd=fpc_get_le32((char *)data+4);
    *outer=0; fpc_put_le32((char *)data+8,0);
    if (target==FPC_TARGET_SENSOR) {
        assert(cmd==FPC_SENSOR_INIT || cmd==FPC_SENSOR_DEEP_SLEEP);
    } else {
        assert(target==FPC_TARGET_AUTH);
        if (cmd==FPC_AUTH_IMPORT_WRAPPED_KEY) assert(n==168);
        else if (cmd==FPC_AUTH_GET_ENROL_CHALLENGE) {
            fpc_put_le64((char *)data+16,scenario==5 ? 0 : 0x1234567890);
            if (scenario==8) cancelled=1;
        } else {
            assert(cmd==FPC_AUTH_AUTHORIZE_ENROL && n==85 && verifies==1);
            for (unsigned i=16;i<n;++i) assert(((unsigned char *)data)[i]==0x77);
            ++authorizes;
            if (scenario==7) fpc_put_le32((char *)data+8,(uint32_t)-1);
        }
    }
    return 0;
}
struct sargo_gk_result mock_verify(struct sargo_gk *g,uint32_t uid,uint64_t challenge,
    const void *handle,size_t n,const void *secret,size_t m,unsigned char hat[69])
{
    (void)g; assert(uid==0x700004d2 && challenge==0x1234567890 && n==58 && m==64);
    for (unsigned i=0;i<n;++i) assert(((const unsigned char *)handle)[i]==0x66);
    for (unsigned i=0;i<m;++i) assert(((const unsigned char *)secret)[i]==0x55);
    ++verifies; memset(hat,0x77,69);
    return (struct sargo_gk_result){0,scenario==6 ? -30 : 0};
}
int main(void)
{
    assert(identity("androidboot.serialno=99NAY1AZG1 pocketfed.root_mode=usb pocketfed.liveboot=" AUTH_RUN));
    assert(!identity("androidboot.serialno=other pocketfed.root_mode=usb pocketfed.liveboot=" AUTH_RUN));
    assert(!identity("androidboot.serialno=99NAY1AZG1 pocketfed.root_mode=ram pocketfed.liveboot=" AUTH_RUN));
    for (scenario=0;scenario<10;++scenario) {
        char path[]="/tmp/fpc-authorization-test-XXXXXX"; assert(mkdtemp(path));
        struct auth_store s={.directory=open(path,O_RDONLY|O_DIRECTORY)}; assert(s.directory>=0);
        verifies=authorizes=backend_opens=0; cancelled=scenario==0;
        int rc=authorization_once(&s);
        assert((rc==0)==(scenario==9));
        assert(verifies==(scenario==6 || scenario==7 || scenario==9));
        assert(authorizes==(scenario==7 || scenario==9));
        if (scenario>=2) {
            unsigned before=backend_opens; cancelled=0;
            assert(authorization_once(&s)<0 && backend_opens==before);
        }
        unlinkat(s.directory,"uid-1234.lab-authorization-attempt",0);
        close(s.directory); assert(!rmdir(path));
    }
    puts("PASS retained credential only, challenge forwarding, failure/cancellation gates, FPC refusal and one-use verification; no biometric or database command");
}
