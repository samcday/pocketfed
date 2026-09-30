// SPDX-License-Identifier: MIT
/* Read only the eMMC RPMB counter/status, never data records or a key.
 * Linux MMC_IOC_MULTI_CMD sends a request packet with CMD25 even for a read.
 * This fixed packet uses RPMB request 2; no command or frame is caller supplied.
 * The response MAC is not authenticated here: this is a transport diagnostic.
 */
#define _GNU_SOURCE
#include <endian.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/mmc/ioctl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/random.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include <unistd.h>

enum { FRAME_SIZE = 512, NONCE_OFFSET = 484, RESULT_OFFSET = 508,
       TYPE_OFFSET = 510, MMC_RSP_R1 = 21, MMC_CMD_ADTC = 32 };

int main(int argc, char **argv)
{
    uint8_t request[FRAME_SIZE] = { 0 }, response[FRAME_SIZE] = { 0 };
    struct stat st;
    int fd = -1, result = 1;
    size_t size = sizeof(struct mmc_ioc_multi_cmd) +
                  2 * sizeof(struct mmc_ioc_cmd);
    struct mmc_ioc_multi_cmd *multi = calloc(1, size);
    if (!multi)
        return 1;
    if (argc != 2 || strcmp(argv[1], "--read-counter-status") || geteuid()) {
        fprintf(stderr, "Requires root and --read-counter-status.\n");
        goto out;
    }
    fd = open("/dev/mmcblk0rpmb", O_RDWR | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0 || fstat(fd, &st) || !S_ISCHR(st.st_mode) || st.st_uid ||
        (st.st_mode & 0777) != 0600 || major(st.st_rdev) != 504 ||
        minor(st.st_rdev) != 0) {
        fprintf(stderr, "Expected this trial's root0600 RPMB device (504:0).\n");
        goto out;
    }
    if (getrandom(request + NONCE_OFFSET, 16, 0) != 16)
        goto out;
    request[TYPE_OFFSET + 1] = 2;
    multi->num_of_cmds = 2;
    for (unsigned i = 0; i < 2; i++) {
        multi->cmds[i].opcode = i ? 18 : 25;
        multi->cmds[i].write_flag = i ? 0 : 1;
        multi->cmds[i].flags = MMC_RSP_R1 | MMC_CMD_ADTC;
        multi->cmds[i].blksz = FRAME_SIZE;
        multi->cmds[i].blocks = 1;
    }
    mmc_ioc_cmd_set_data(multi->cmds[0], request);
    mmc_ioc_cmd_set_data(multi->cmds[1], response);
    int rc = ioctl(fd, MMC_IOC_MULTI_CMD, multi);
    int error = rc ? errno : 0;
    printf("counter_transport_errno=%d\n", error);
    if (rc)
        goto out;
    unsigned type = response[TYPE_OFFSET] * 256u + response[TYPE_OFFSET + 1];
    unsigned status = response[RESULT_OFFSET] * 256u + response[RESULT_OFFSET + 1];
    int nonce_matches = !memcmp(request + NONCE_OFFSET, response + NONCE_OFFSET, 16);
    printf("counter_response_type=%u counter_device_status=%u nonce_matches=%d\n",
           type, status, nonce_matches);
    if (type == 0x200 && !status && nonce_matches)
        result = 0;
out:
    if (fd >= 0)
        close(fd);
    explicit_bzero(request, sizeof(request));
    explicit_bzero(response, sizeof(response));
    explicit_bzero(multi, size);
    free(multi);
    return result;
}
