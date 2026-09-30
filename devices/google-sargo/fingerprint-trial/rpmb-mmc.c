// SPDX-License-Identifier: MIT
#ifndef _DEFAULT_SOURCE
#define _DEFAULT_SOURCE
#endif
#include "rpmb-mmc.h"
#include <errno.h>
#include <linux/mmc/ioctl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>

static unsigned frame_type(const unsigned char *frame)
{
    return frame[510] * 256u + frame[511];
}

int sargo_rpmb_mmc_transfer(void *context, bool write,
    const void *request, size_t request_frames,
    void *response, size_t response_frames)
{
    const unsigned char *q = request;
    unsigned char result_request[SARGO_RPMB_FRAME] = {0};
    struct mmc_ioc_multi_cmd *multi = NULL;
    size_t commands = write ? 3 : 2;
    size_t allocation = sizeof(*multi) + commands * sizeof(struct mmc_ioc_cmd);
    int rc = -EINVAL;
    if (!context || *(int *)context < 0 || !q || !response || !request_frames ||
        !response_frames || request_frames > 32 || response_frames > 49)
        return -EINVAL;
    if (write) {
        if (response_frames != 1)
            goto out;
        for (size_t i = 0; i < request_frames; ++i)
            if (frame_type(q + i * SARGO_RPMB_FRAME) != 3)
                goto out;
    } else if (request_frames != 1 ||
               (frame_type(q) != 2 && frame_type(q) != 4) ||
               (frame_type(q) == 2 && response_frames != 1)) {
        goto out;
    }
    multi = calloc(1, allocation);
    if (!multi) {
        rc = -ENOMEM;
        goto out;
    }
    multi->num_of_cmds = commands;
    for (size_t i = 0; i < commands; ++i) {
        struct mmc_ioc_cmd *c = &multi->cmds[i];
        bool read_response = i == commands - 1;
        c->opcode = read_response ? 18 : 25;
        c->write_flag = read_response ? 0 : 1;
        c->flags = 21 | 32; /* MMC_RSP_R1 | MMC_CMD_ADTC */
        c->blksz = SARGO_RPMB_FRAME;
        c->blocks = i == 0 ? request_frames : read_response ? response_frames : 1;
    }
    mmc_ioc_cmd_set_data(multi->cmds[0], request);
    if (write) {
        multi->cmds[0].write_flag = (int)0x80000001u; /* Reliable write. */
        result_request[511] = 5;
        mmc_ioc_cmd_set_data(multi->cmds[1], result_request);
    }
    mmc_ioc_cmd_set_data(multi->cmds[commands - 1], response);
    /* Single kernel transaction; never replay after an ambiguous error. */
    rc = ioctl(*(int *)context, MMC_IOC_MULTI_CMD, multi) ? -errno : 0;
out:
    if (rc)
        explicit_bzero(response, response_frames * SARGO_RPMB_FRAME);
    explicit_bzero(result_request, sizeof(result_request));
    if (multi) {
        explicit_bzero(multi, allocation);
        free(multi);
    }
    return rc;
}
