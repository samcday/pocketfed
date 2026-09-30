// SPDX-License-Identifier: MIT
#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SARGO_RPMB_LISTENER 0x2000u
#define SARGO_RPMB_BUFFER (25u * 1024u)
#define SARGO_RPMB_FRAME 512u

struct sargo_rpmb_geometry {
    uint32_t sectors_512;
    uint32_t reliable_frames;
};

/* Forward opaque JEDEC frames. The secure world and device authenticate them.
 * No key programming, emulation, MAC generation or automatic retries.
 * Return zero for a completed transport, including device error responses.
 */
typedef int (*sargo_rpmb_transfer)(void *context, bool write,
    const void *request, size_t request_frames,
    void *response, size_t response_frames);

/* Bounded codec for the documented layout and observed read payload lengths.
 * Preserve the opaque RW version field in replies, as stock and LK do.
 * Reads passed on test-sargo; authenticated writes remain a separate trial.
 * Returns zero for a formatted reply, -1 for an unusable buffer.
 * Data writes require explicit enablement by the owning trial, default false.
 */
int sargo_rpmb_dispatch(void *buffer, size_t size,
    const struct sargo_rpmb_geometry *geometry, bool allow_data_writes,
    sargo_rpmb_transfer transfer, void *context);
