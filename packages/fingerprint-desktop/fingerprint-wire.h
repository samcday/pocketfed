/* SPDX-License-Identifier: GPL-3.0-or-later */
#pragma once
#include <errno.h>
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <unistd.h>

#define FINGERPRINT_SOCKET_PATH "/run/phosh-fingerprint-auth/socket"
#define FINGERPRINT_MESSAGE_MAX 4096u
#define FINGERPRINT_MESSAGE 1u
#define FINGERPRINT_RESULT 2u

/* Type byte, big-endian uint32 length, then length bytes. Message text cannot
 * inject a result frame. No caller-selected account crosses this socket. */
static inline int fingerprint_read_exact(int fd, void *buffer, size_t length)
{
    unsigned char *p = buffer;
    while (length) {
        ssize_t n = read(fd, p, length);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n;
        length -= (size_t)n;
    }
    return 0;
}
static inline int fingerprint_write_exact(int fd, const void *buffer, size_t length)
{
    const unsigned char *p = buffer;
    while (length) {
        ssize_t n = write(fd, p, length);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += n;
        length -= (size_t)n;
    }
    return 0;
}
static inline int fingerprint_send(int fd, unsigned char type, const void *data, uint32_t length)
{
    unsigned char header[5] = { type, length >> 24, length >> 16, length >> 8, length };
    if (length > FINGERPRINT_MESSAGE_MAX) return -1;
    if (fingerprint_write_exact(fd, header, sizeof(header))) return -1;
    return fingerprint_write_exact(fd, data, length);
}
static inline int fingerprint_receive(int fd, unsigned char *type, void *data, uint32_t *length)
{
    unsigned char header[5];
    if (fingerprint_read_exact(fd, header, sizeof(header))) return -1;
    *type = header[0];
    *length = (uint32_t)header[1] << 24 | (uint32_t)header[2] << 16 |
              (uint32_t)header[3] << 8 | header[4];
    if (*length > FINGERPRINT_MESSAGE_MAX) return -1;
    return fingerprint_read_exact(fd, data, *length);
}
