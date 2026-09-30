// SPDX-License-Identifier: MIT
#define _DEFAULT_SOURCE
#include "rpmb-protocol.h"
#include <stdlib.h>
#include <string.h>
#ifdef SARGO_RPMB_DIAGNOSTICS
#include <stdio.h>
#endif

enum { INIT = 0x101, READ = 0x102, WRITE = 0x103, VERSION = 2,
       RW_REQUEST = 24, RW_RESPONSE = 20, INIT_RESPONSE = 40,
       COUNTER = 2, DATA_WRITE = 3, DATA_READ = 4 };

static uint32_t le32(const unsigned char *p)
{
    return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 |
           (uint32_t)p[3] << 24;
}

static uint16_t be16(const unsigned char *p)
{
    return (uint16_t)p[0] << 8 | p[1];
}

static void put32(unsigned char *p, uint32_t x)
{
    for (unsigned i = 0; i < 4; ++i)
        p[i] = x >> (i * 8);
}

static int geometry_valid(const struct sargo_rpmb_geometry *g)
{
    /* JEDEC addresses are 16 bit; each data payload is 256 bytes. */
    return g && g->sectors_512 && g->sectors_512 <= 32768 &&
        (g->reliable_frames == 1 || g->reliable_frames == 2 ||
         g->reliable_frames == 32);
}

int sargo_rpmb_dispatch(void *buffer, size_t size,
    const struct sargo_rpmb_geometry *g, bool allow_data_writes,
    sargo_rpmb_transfer transfer, void *context)
{
    unsigned char *b = buffer, *request = NULL;
    uint32_t cmd, count, length, offset, version, reliable;
    uint32_t response_length = 0, status = UINT32_MAX;
    size_t request_length = 0;
    const char *stage = "envelope";
    int transfer_status = 0;
    if (!b || size < INIT_RESPONSE || size > SARGO_RPMB_BUFFER)
        return -1;
    cmd = le32(b);
    if (cmd == INIT) {
        version = le32(b + 4);
        memset(b, 0, size);
        put32(b, cmd);
        put32(b + 4, VERSION);
        put32(b + 8, UINT32_MAX);
        if (version == VERSION && geometry_valid(g)) {
            put32(b + 8, 0);
            put32(b + 12, g->sectors_512);
            put32(b + 16, g->reliable_frames);
            put32(b + 20, 3); /* Qualcomm storage device enum: eMMC */
        }
        return 0;
    }
    count = le32(b + 4);
    length = le32(b + 8);
    offset = le32(b + 12);
    version = le32(b + 16);
    reliable = le32(b + 20);
    /* Stock and LK do not interpret this RW field and preserve it in replies.
     * Live SAM.008 uses 0 on reads and 0x100 on a write. INIT negotiation is
     * separate; frame bounds/types and write authorization carry validation. */
    if (!geometry_valid(g) || !transfer ||
        (cmd != READ && cmd != WRITE) || !count ||
        count > (size - RW_REQUEST) / SARGO_RPMB_FRAME ||
        offset < RW_REQUEST || offset > size || length > size - offset)
        goto reply;
    if (cmd == READ) {
        stage = "read-length";
        /* SAM.008 reports requested data bytes (256 per response block),
         * while the physical read request is always one 512-byte frame.
         * Retain support for the prior single-frame encoding.
         * Bound that physical frame independently of the declared data size. */
        if ((length != SARGO_RPMB_FRAME && length != count * 256u) ||
            SARGO_RPMB_FRAME > size - offset)
            goto reply;
        stage = "read-type";
        uint16_t type = be16(b + offset + 510);
        if (type != COUNTER && type != DATA_READ)
            goto reply;
        stage = "counter-count";
        if (type == COUNTER && count != 1)
            goto reply;
        if (type == DATA_READ) {
            stage = "read-blocks-or-range";
            uint16_t blocks = be16(b + offset + 506);
            if ((blocks && blocks != count) ||
                (uint32_t)be16(b + offset + 504) + count > g->sectors_512 * 2)
                goto reply;
        }
    } else {
        stage = "write-disabled-or-group";
        if (!allow_data_writes || !reliable || reliable > g->reliable_frames ||
            count % reliable || length != count * SARGO_RPMB_FRAME)
            goto reply;
        for (uint32_t i = 0; i < count; ++i) {
            stage = "write-frame";
            const unsigned char *frame = b + offset + i * SARGO_RPMB_FRAME;
            if (be16(frame + 510) != DATA_WRITE ||
                be16(frame + 506) != reliable ||
                be16(frame + 504) >= g->sectors_512 * 2)
                goto reply;
        }
    }
    /* Input and reply share memory; snapshot the complete request first. */
    stage = "allocation";
    request_length = cmd == READ ? SARGO_RPMB_FRAME : length;
    request = malloc(request_length);
    if (!request)
        goto reply;
    memcpy(request, b + offset, request_length);
    memset(b, 0, size);
    if (cmd == READ) {
        stage = "read-transfer";
        transfer_status = transfer(context, false, request, 1, b + RW_RESPONSE, count);
        if (!transfer_status) {
            response_length = count * SARGO_RPMB_FRAME;
            status = 0;
        }
    } else {
        stage = "write-transfer";
        for (uint32_t i = 0; i < count; i += reliable) {
            memset(b + RW_RESPONSE, 0, SARGO_RPMB_FRAME);
            status = UINT32_MAX;
            response_length = 0;
            transfer_status = transfer(context, true, request + i * SARGO_RPMB_FRAME,
                                       reliable, b + RW_RESPONSE, 1);
            if (transfer_status)
                goto reply;
            /* Preserve device failure as a frame for secure-world checking,
             * then stop before issuing any later signed write group. */
            response_length = SARGO_RPMB_FRAME;
            status = 0;
            if (be16(b + RW_RESPONSE + 510) != 0x300 ||
                be16(b + RW_RESPONSE + 508))
                break;
        }
    }
reply:
#ifdef SARGO_RPMB_DIAGNOSTICS
    /* Envelope sizes and a fixed validation-stage label only. No frame type,
     * address, counter, nonce, MAC, credential or storage contents are logged. */
    fprintf(stderr, "event=rpmb_dispatch cmd=%u count=%u length=%u offset=%u "
            "version=%u reliable=%u stage=%s transfer_status=%d reply_status=%d\n",
            cmd, count, length, offset, version, reliable, stage,
            transfer_status, (int32_t)status);
#else
    (void)stage;
#endif
    if (request) {
        explicit_bzero(request, request_length);
        free(request);
    }
    /* Never return request payload or a partial response on transport error. */
    if (status)
        memset(b, 0, size);
    else
        memset(b, 0, RW_RESPONSE);
    put32(b, cmd);
    put32(b + 4, status);
    put32(b + 8, status ? 0 : response_length);
    put32(b + 12, status ? 0 : RW_RESPONSE);
    put32(b + 16, version);
    return 0;
}
