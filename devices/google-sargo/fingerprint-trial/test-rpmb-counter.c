// SPDX-License-Identifier: MIT
#include <assert.h>
#include <stdarg.h>
#define main counter_main
#define open mock_open
#define fstat mock_fstat
#define ioctl mock_ioctl
#define getrandom mock_getrandom
#define geteuid mock_geteuid
#define close mock_close
#include "rpmb-counter-check.c"
#undef main
static int calls, mode;
int mock_open(const char *name, int flags, ...) { assert(!strcmp(name,"/dev/mmcblk0rpmb")); assert(flags == (O_RDWR|O_CLOEXEC|O_NOFOLLOW)); return 17; }
int mock_fstat(int fd, struct stat *s) { assert(fd==17); memset(s,0,sizeof(*s)); s->st_mode=S_IFCHR|0600; s->st_rdev=makedev(504,0); return 0; }
uid_t mock_geteuid(void) { return 0; }
ssize_t mock_getrandom(void *b,size_t n,unsigned f) { assert(n==16 && !f); memset(b,0x91,n); return n; }
int mock_close(int fd) { assert(fd==17); return 0; }
int mock_ioctl(int fd,unsigned long cmd,...) {
    va_list ap; va_start(ap,cmd); struct mmc_ioc_multi_cmd *m=va_arg(ap,void*); va_end(ap);
    assert(fd==17 && cmd==MMC_IOC_MULTI_CMD && ++calls==1 && m->num_of_cmds==2);
    for(unsigned i=0;i<2;i++) {
        const struct mmc_ioc_cmd *c=&m->cmds[i];
        assert(c->opcode==(i?18:25) && c->write_flag==(i?0:1));
        assert(c->flags==53 && c->blocks==1 && c->blksz==512 && !c->arg && !c->is_acmd);
    }
    const uint8_t *q=(void *)(uintptr_t)m->cmds[0].data_ptr;
    uint8_t *r=(void *)(uintptr_t)m->cmds[1].data_ptr;
    for(unsigned i=0;i<512;i++) assert(q[i]==(i==511?2:(i>=484 && i<500?0x91:0)));
    if(mode==3) { errno=EIO; return -1; }
    memcpy(r+484,q+484,16); r[510]=2;
    if(mode==1) r[484]^=1;
    if(mode==2) r[509]=7;
    return 0;
}
int main(void) {
    char *args[]={"counter","--read-counter-status",NULL};
    for(mode=0;mode<4;mode++) { calls=0; assert(counter_main(2,args)==(mode?1:0)); assert(calls==1); }
    calls=0; assert(counter_main(1,args)==1 && calls==0);
    puts("PASS fixed counter-only MMC frames, nonce and status failures, transport failure, no retry and argument refusal");
}
