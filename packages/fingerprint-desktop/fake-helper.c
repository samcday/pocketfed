/* SPDX-License-Identifier: GPL-3.0-or-later */
/* A subprocess fixture, never packaged or installed. */
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <unistd.h>
int main(void)
{
    const char *mode = getenv("FINGERPRINT_FAKE_MODE");
    if (!mode) return 2;
    if (!strcmp(mode, "success")) return 0;
    if (!strcmp(mode, "signal")) raise(SIGTERM);
    if (!strcmp(mode, "block")) for (;;) pause();
    return 1;
}
