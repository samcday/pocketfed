/* SPDX-License-Identifier: GPL-2.0-only */
/* Mock only the kernel/SCM boundary; the invoke body is inserted below. */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

typedef uint32_t u32;
typedef uint64_t phys_addr_t;
#define PAGE_ALIGN(n) (((n) + PAGE_SIZE - 1) & ~(size_t)(PAGE_SIZE - 1))
#define QSEECOM_TEE_MAX_XFER (16U * 1024 * 1024)
#define QSEECOM_TEE_MAX_PATCH 4
#define TEE_SHM_POOL 1
#define TEE_IOCTL_PARAM_ATTR_TYPE_MASK 255
#define TEE_IOCTL_PARAM_ATTR_TYPE_VALUE_INPUT 1
#define TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INPUT 5
#define TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_OUTPUT 6
#define TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INOUT 7
#define QCOM_TZMEM_POLICY_STATIC 1
#define GFP_KERNEL 0
#define ERR_PTR(n) ((void *)(intptr_t)(n))
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define IS_ERR(p) ((uintptr_t)(p) >= (uintptr_t)-4095)
#define guard(kind) (void)
#define check_add_overflow(a,b,p) __builtin_add_overflow(a,b,p)
#define upper_32_bits(n) ((uint32_t)((uint64_t)(n) >> 32))
#define lower_32_bits(n) ((uint32_t)(n))
#define barrier_data(p) __asm__ __volatile__("" : : "r"(p) : "memory")

struct qseecom_tee { struct qcom_tzmem_pool *mempool; };
struct qseecom_tee_context { struct qseecom_tee *qtee; int mutex; };
struct tee_context { struct qseecom_tee_context *data; };
struct qseecom_tee_session { u32 app_id, app_gen; };
struct tee_ioctl_invoke_arg { u32 func, session, num_params, ret, ret_origin; };
struct tee_shm { unsigned flags; size_t size; unsigned char *data; int id; };
struct tee_param {
    uint64_t attr;
    union {
        struct { struct tee_shm *shm; size_t size, shm_offs; } memref;
        struct { uint64_t a,b,c; } value;
    } u;
};
struct qcom_tzmem_pool_config { size_t initial_size, max_size; int policy; };
struct qcom_tzmem_pool { size_t size; };

static struct qseecom_tee_session session = {17, 23};
static struct qcom_tzmem_pool pool;
static unsigned char *allocation;
static size_t allocation_size, req_length, rsp_length, aux_length[4];
static unsigned patch_count, va_calls[6], fail_va_id, fail_va_call;
static unsigned allocations, frees, pool_creations, pool_frees, sends, phys_calls;
static unsigned fail_phys_call;
static int scm_error;
static bool fail_pool, fail_alloc, session_missing, stale_app, high_phys;

static struct qseecom_tee_session *
qseecom_tee_session_find(struct qseecom_tee_context *ctx, u32 id)
{
    (void)ctx;
    return !session_missing && id == 1 ? &session : NULL;
}

static bool qseecom_tee_app_current(struct qseecom_tee *qtee, u32 id, u32 gen)
{
    (void)qtee;
    assert(id == session.app_id && gen == session.app_gen);
    return !stale_app;
}

static size_t tee_shm_get_size(struct tee_shm *shm) { return shm->size; }

static void *tee_shm_get_va(struct tee_shm *shm, size_t off)
{
    assert(shm->id < 6);
    va_calls[shm->id]++;
    if (allocation)
        allocation[allocation_size - 1] = 0xf3; /* Check full tail on errors. */
    if ((unsigned)shm->id == fail_va_id && va_calls[shm->id] == fail_va_call)
        return ERR_PTR(-EFAULT);
    return shm->data + off;
}

static __attribute__((unused)) struct qcom_tzmem_pool *
qcom_tzmem_pool_new(struct qcom_tzmem_pool_config *config)
{
    (void)config;
    fputs("PER-INVOKE pool creation or destruction\n", stderr);
    exit(91);
}

static void *qcom_tzmem_alloc(struct qcom_tzmem_pool *p, size_t size, int flags)
{
    (void)flags;
    allocations++;
    assert(p == &pool && size % PAGE_SIZE == 0 && !allocation);
    if (fail_alloc)
        return NULL;
    allocation_size = size;
    allocation = malloc(size);
    assert(allocation);
    memset(allocation, 0xa5, size);
    return allocation;
}

static void qcom_tzmem_free(void *p)
{
    assert(p == allocation && allocation && !frees && !pool_frees);
    for (size_t i = 0; i < allocation_size; i++) {
        if (allocation[i] != 0) {
            fputs("UNWIPED invoke staging at free\n", stderr);
            exit(90);
        }
    }
    frees++;
    free(allocation);
    allocation = NULL;
}

static __attribute__((unused)) void qcom_tzmem_pool_free(struct qcom_tzmem_pool *p)
{
    (void)p;
    fputs("PER-INVOKE pool creation or destruction\n", stderr);
    exit(91);
}

static phys_addr_t qcom_tzmem_to_phys(void *p)
{
    phys_calls++;
    assert(allocation && (unsigned char *)p >= allocation);
    assert((unsigned char *)p < allocation + allocation_size);
    allocation[allocation_size - 1] = 0xf3;
    if (phys_calls == fail_phys_call)
        return 0;
    return (high_phys ? UINT64_C(0x100000000) : UINT64_C(0x100000)) +
           ((unsigned char *)p - allocation);
}

static void put_unaligned_le32(uint32_t n, void *p) { memcpy(p, &n, 4); }
static void put_unaligned_le64(uint64_t n, void *p) { memcpy(p, &n, 8); }

static int qcom_scm_qseecom_app_send(u32 id, void *req, size_t rn,
                                    void *rsp, size_t sn)
{
    sends++;
    assert(id == session.app_id && req == allocation);
    assert(rn == req_length && sn == rsp_length);
    assert(rsp == allocation + req_length);
    /* Simulate the TA overwriting every byte, including allocator padding. */
    memset(allocation, 0xc7, allocation_size);
    memset(rsp, 0x92, sn);
    size_t off = PAGE_ALIGN(rn + sn);
    for (unsigned i = 0; i < patch_count; i++) {
        assert(off + aux_length[i] <= allocation_size);
        memset(allocation + off, 0xa0 + i, aux_length[i]);
        off += aux_length[i];
    }
    return scm_error;
}

/* INSERT_PRODUCTION_FUNCTIONS */

static void check_bytes(const unsigned char *p, size_t n, unsigned char value)
{
    for (size_t i = 0; i < n; i++)
        assert(p[i] == value);
}

enum scenario {
    SUCCESS_PLAIN, SUCCESS_AUX32, SUCCESS_AUX64, SUCCESS_FOUR_PATCHES,
    SCM_FAILURE, SCM_BUSY, SCM_TIMEOUT, PATCH_MAP_FAIL_FIRST, PATCH_MAP_FAIL_SECOND,
    PHYS_FAIL_FIRST, PHYS_FAIL_SECOND, PHYS32_OVERFLOW, COPYBACK_MAP_FAILURE,
    INVALID_FUNC, INVALID_COUNT, NO_SESSION, STALE_APP, BAD_REQ_REF, BAD_RSP_REF,
    BAD_PATCH, ZERO_REQUEST, TOTAL_OVERFLOW, TOTAL_TOO_LARGE, ALLOC_FAIL,
    SCENARIO_COUNT
};

static void exercise(enum scenario which)
{
    struct qseecom_tee qtee = {.mempool = &pool};
    struct qseecom_tee_context ctxdata = {.qtee = &qtee};
    struct tee_context ctx = {.data = &ctxdata};
    struct tee_ioctl_invoke_arg arg = {.session = 1, .ret = 99, .ret_origin = 99};
    unsigned char data[6][160];
    struct tee_shm shm[6];
    struct tee_param params[10] = {0};
    int expected = 0;
    bool before_allocation = which >= INVALID_FUNC;

    allocations = frees = pool_creations = pool_frees = sends = phys_calls = 0;
    memset(va_calls, 0, sizeof(va_calls));
    fail_va_id = 99; fail_va_call = 0; fail_phys_call = 0; scm_error = 0;
    fail_pool = fail_alloc = session_missing = stale_app = high_phys = false;
    assert(!allocation);
    req_length = 67; rsp_length = 79; patch_count = 2;
    if (which == SUCCESS_PLAIN) patch_count = 0;
    if (which == SUCCESS_AUX32 || which == SUCCESS_AUX64) patch_count = 1;
    if (which == SUCCESS_FOUR_PATCHES) patch_count = 4;
    arg.num_params = 2 + 2 * patch_count;
    for (unsigned i = 0; i < 6; i++) {
        memset(data[i], 0x30 + i, sizeof(data[i]));
        shm[i] = (struct tee_shm){TEE_SHM_POOL, sizeof(data[i]), data[i], i};
    }
    params[0].attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INPUT;
    params[0].u.memref.shm = &shm[0]; params[0].u.memref.size = req_length;
    params[1].attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_OUTPUT;
    params[1].u.memref.shm = &shm[1]; params[1].u.memref.size = rsp_length;
    for (unsigned i = 0; i < patch_count; i++) {
        unsigned k = 2 + 2 * i;
        aux_length[i] = 91 + i;
        params[k].attr = TEE_IOCTL_PARAM_ATTR_TYPE_VALUE_INPUT;
        params[k].u.value.a = 5 + 8 * i; /* Unaligned packed address field. */
        params[k].u.value.b = which == SUCCESS_AUX32 || which == PHYS32_OVERFLOW ? 4 : 8;
        params[k + 1].attr = TEE_IOCTL_PARAM_ATTR_TYPE_MEMREF_INOUT;
        params[k + 1].u.memref.shm = &shm[2 + i];
        params[k + 1].u.memref.size = aux_length[i];
    }
    switch (which) {
    case SCM_FAILURE: scm_error = expected = -EIO; break;
    case SCM_BUSY: scm_error = expected = -EBUSY; break;
    case SCM_TIMEOUT: scm_error = expected = -ETIMEDOUT; break;
    case PATCH_MAP_FAIL_FIRST: fail_va_id = 2; fail_va_call = 1; expected = -EFAULT; break;
    case PATCH_MAP_FAIL_SECOND: fail_va_id = 3; fail_va_call = 1; expected = -EFAULT; break;
    case PHYS_FAIL_FIRST: fail_phys_call = 1; expected = -EINVAL; break;
    case PHYS_FAIL_SECOND: fail_phys_call = 2; expected = -EINVAL; break;
    case PHYS32_OVERFLOW: high_phys = true; expected = -EOVERFLOW; break;
    case COPYBACK_MAP_FAILURE: fail_va_id = 2; fail_va_call = 2; break;
    case INVALID_FUNC: arg.func = 1; expected = -EINVAL; break;
    case INVALID_COUNT: arg.num_params = 3; expected = -EINVAL; break;
    case NO_SESSION: session_missing = true; expected = -EINVAL; break;
    case STALE_APP: stale_app = true; expected = -ENOENT; break;
    case BAD_REQ_REF: params[0].u.memref.shm = NULL; expected = -EINVAL; break;
    case BAD_RSP_REF: fail_va_id = 1; fail_va_call = 1; expected = -EFAULT; break;
    case BAD_PATCH: params[2].u.value.b = 3; expected = -EINVAL; break;
    case ZERO_REQUEST: params[0].u.memref.size = 0; arg.num_params = 2; expected = -EINVAL; break;
    case TOTAL_OVERFLOW:
        shm[0].size = params[0].u.memref.size = SIZE_MAX;
        arg.num_params = 2; expected = -EINVAL; break;
    case TOTAL_TOO_LARGE:
        shm[0].size = params[0].u.memref.size = QSEECOM_TEE_MAX_XFER;
        arg.num_params = 2; expected = -EINVAL; break;
    case ALLOC_FAIL: fail_alloc = true; expected = -ENOMEM; break;
    default: break;
    }
    assert(qseecom_tee_invoke_func(&ctx, &arg, params) == expected);
    assert(!allocation);
    if (before_allocation) {
        assert(!sends && !frees);
        assert(pool_creations == 0);
        assert(allocations == (which == ALLOC_FAIL));
        assert(pool_frees == 0);
    } else {
        assert(pool_creations == 0 && allocations == 1 && frees == 1 && pool_frees == 0);
    }
    check_bytes(data[0], sizeof(data[0]), 0x30); /* Never wipe caller's request. */
    if (!expected) {
        assert(sends == 1 && arg.ret == 0 && arg.ret_origin == 0);
        check_bytes(data[1], rsp_length, 0x92);
        for (unsigned i = 0; i < patch_count; i++)
            check_bytes(data[2 + i], aux_length[i],
                        which == COPYBACK_MAP_FAILURE && i == 0 ? 0x32 : 0xa0 + i);
    } else {
        assert(arg.ret == 99 && arg.ret_origin == 99);
        check_bytes(data[1], sizeof(data[1]), 0x31);
        for (unsigned i = 0; i < patch_count; i++)
            check_bytes(data[2 + i], sizeof(data[2 + i]), 0x32 + i);
    }
}

int main(void)
{
    for (enum scenario i = 0; i < SCENARIO_COUNT; i++)
        exercise(i);
    printf("PASS: %d invoke cleanup/copy-back cases, PAGE_SIZE=%u\n", SCENARIO_COUNT, PAGE_SIZE);
    return 0;
}
