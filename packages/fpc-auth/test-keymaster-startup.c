/* SPDX-License-Identifier: LGPL-2.1-or-later */
#define main startup_main
#include "keymaster-startup.c"
#undef main
#include <assert.h>

enum scenario {
    SUCCESS, ALREADY_READY, WRONG_VERSION, TRANSPORT_MINUS24, SECURE_OTHER,
    UNTOUCHED_WRAPPED, PARAM_TRANSPORT, PARAM_UNTOUCHED, PARAM_ZERO,
    CANCEL_AFTER_PARAMS, COMPUTE_TRANSPORT, COMPUTE_SECURE, COMPUTE_ZERO,
    FINAL_WRAPPED_BAD, CANCEL_BEFORE_OPEN, END
};
static enum scenario scenario;
static unsigned calls, opens, closes, computes, wrapped;

int fpc_qsee_open(struct fpc_qsee_session *s, const char *name)
{
    assert(!strcmp(name, "keymaster64"));
    ++opens;
    s->opened = true;
    return 0;
}

void fpc_qsee_close(struct fpc_qsee_session *s)
{
    if (s->opened) ++closes;
    s->opened = false;
}

int fpc_qsee_exchange(struct fpc_qsee_session *s, const void *request, size_t n,
                     void *response, size_t m, void *aux, size_t a, uint32_t p)
{
    const unsigned char *b = request;
    unsigned char *r = response;
    assert(s->opened && !stopping && !aux && !a && !p);
    ++calls;
    uint32_t command = fpc_get_le32(b);
    if (command == 0x205) {
        assert(n == 64 && m == 960 && fpc_get_le32(b + 4) == 2);
        for (unsigned i = 8; i < 64; ++i) assert(!b[i]);
        ++wrapped;
        if (scenario == TRANSPORT_MINUS24) return -24;
        if (scenario == UNTOUCHED_WRAPPED) return 0;
        memset(r, 0, m);
        if (scenario == SECURE_OTHER) fpc_put_le32(r, -38);
        else if (wrapped == 1 && scenario != ALREADY_READY) fpc_put_le32(r, -24);
        else {
            fpc_put_le32(r + 4, scenario == FINAL_WRAPPED_BAD ? 961 : 12);
            fpc_put_le32(r + 8, 152);
            memset(r + 12, 0x51, 152);
        }
        return 0;
    }
    assert(n + m == SARGO_GK_BUFFER_SIZE);
    switch (command) {
    case 0x200:
        assert(calls == 1 && n == 4);
        memset(r, 0, m);
        fpc_put_le32(r + 4, 4); fpc_put_le32(r + 12, 4);
        fpc_put_le32(r + 16, scenario == WRONG_VERSION ? 166 : 165);
        break;
    case 0x207: {
        const unsigned words[] = {0x207, 4, 5, 4, 5, 0};
        assert(calls == 2 && n == 24);
        for (unsigned i = 0; i < 6; ++i) assert(fpc_get_le32(b + 4 * i) == words[i]);
        memset(r, 0, m);
        break;
    }
    case 0x20e:
        assert(calls == 4 && n == 4);
        if (scenario == PARAM_TRANSPORT) return -EBUSY;
        if (scenario == PARAM_UNTOUCHED) return 0;
        memset(r, 0, m);
        if (scenario != PARAM_ZERO)
            for (unsigned i = 0; i < 64; ++i) r[4 + i] = i + 1;
        if (scenario == CANCEL_AFTER_PARAMS) stopping = 1;
        break;
    case 0x20f:
        assert(calls == 5 && n == 76 && fpc_get_le32(b + 4) == 12 && fpc_get_le32(b + 8) == 1);
        for (unsigned i = 0; i < 64; ++i) assert(b[12 + i] == i + 1);
        ++computes;
        if (scenario == COMPUTE_TRANSPORT) return -EIO;
        memset(r, 0, m);
        if (scenario == COMPUTE_SECURE) fpc_put_le32(r, -38);
        else if (scenario != COMPUTE_ZERO) memset(r + 4, 0x72, 32);
        break;
    default:
        /* No credential/UID, enrollment, verification or storage command. */
        assert(0);
    }
    return 0;
}

int main(void)
{
    for (scenario = SUCCESS; scenario < END; ++scenario) {
        calls = opens = closes = computes = wrapped = 0;
        stopping = scenario == CANCEL_BEFORE_OPEN;
        int result = initialize();
        assert((result == 0) == (scenario == SUCCESS || scenario == ALREADY_READY));
        assert(opens == closes);
        bool should_compute = scenario == SUCCESS ||
            (scenario >= COMPUTE_TRANSPORT && scenario <= FINAL_WRAPPED_BAD);
        assert(computes == (unsigned)should_compute);
        if (scenario == ALREADY_READY) assert(calls == 3 && wrapped == 1);
        if (scenario == WRONG_VERSION) assert(calls == 1);
        if (scenario == CANCEL_BEFORE_OPEN) assert(calls == 0 && opens == 0);
    }
    puts("PASS startup idempotence, real negotiation/codec frames, genuine uninitialized-state requirement, malformed replies, cancellation and no retries");
}
