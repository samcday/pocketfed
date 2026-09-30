/* SPDX-License-Identifier: MIT */
#pragma once
#include "rpmb-protocol.h"
#include <errno.h>
#include <string.h>

struct sargo_write_policy { bool enabled, failed; };

static int sargo_checked_transfer(struct sargo_write_policy *policy, bool stopping,
    sargo_rpmb_transfer transfer, void *context, bool write,
    const void *request, size_t request_frames, void *response, size_t response_frames)
{
    if (!policy || !transfer || stopping ||
        (write && (!policy->enabled || policy->failed))) return -EPERM;
    int rc = transfer(context, write, request, request_frames, response, response_frames);
    if (write) {
        const unsigned char *p = response;
        unsigned type = !rc && p && response_frames == 1 ? p[510] * 256u + p[511] : 0;
        unsigned status = !rc && p && response_frames == 1 ? p[508] * 256u + p[509] : 0xffff;
        if (rc || type != 0x300 || status) policy->failed = true;
    }
    return rc;
}
