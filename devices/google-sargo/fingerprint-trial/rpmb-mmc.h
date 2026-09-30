// SPDX-License-Identifier: MIT
#pragma once
#include "rpmb-protocol.h"

/* Context is an int pointing to a previously validated open eMMC RPMB fd. */
int sargo_rpmb_mmc_transfer(void *context, bool write,
    const void *request, size_t request_frames,
    void *response, size_t response_frames);
