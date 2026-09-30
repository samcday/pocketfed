/* SPDX-License-Identifier: GPL-3.0-or-later */
/* Unprivileged client for a fixed-service, peer-bound PAM worker. */
#define _GNU_SOURCE
#include "fingerprint-wire.h"
#include <stdio.h>
#include <sys/socket.h>
#include <sys/un.h>

int
main(int argc, char **argv)
{
    struct sockaddr_un address = { .sun_family = AF_UNIX };
    struct ucred peer = {0};
    socklen_t peer_size = sizeof(peer);
    unsigned char payload[FINGERPRINT_MESSAGE_MAX + 1], type;
    uint32_t length;
    int fd, result = 1;
    (void) argv;
    if (argc != 1 || getuid() != geteuid() || getgid() != getegid())
        return 2;
    memcpy(address.sun_path, FINGERPRINT_SOCKET_PATH, sizeof(FINGERPRINT_SOCKET_PATH));
    fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0)
        return 2;
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) ||
        getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &peer, &peer_size) ||
        peer_size != sizeof(peer) || peer.uid != 0) {
        close(fd);
        return 2;
    }
    /* No username, service, secret, or result is supplied by the caller.
     * Closing this socket, including when Phosh kills us, cancels the worker. */
    while (!fingerprint_receive(fd, &type, payload, &length)) {
        if (type == FINGERPRINT_MESSAGE) {
            payload[length] = 0;
            if (memchr(payload, 0, length)) break;
            if (length && (fwrite(payload, 1, length, stdout) != length ||
                           fputc('\n', stdout) == EOF || fflush(stdout))) break;
        } else if (type == FINGERPRINT_RESULT && length == 1) {
            result = payload[0] == 0 ? 0 : 1;
            break;
        } else break;
    }
    close(fd);
    return result;
}
