/* SPDX-License-Identifier: MIT */
#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif
#include "sargo-device.h"
#include <assert.h>
#include <unistd.h>

static void write_dev(const char *text)
{
    FILE *f = fopen("card/mmcblk0rpmb/dev", "w");
    assert(f && fputs(text, f) >= 0 && !fclose(f));
}

int main(void)
{
    const char valid[] = "google,sargo\0qcom,sdm670";
    assert(sargo_compatible_data(valid, sizeof valid));
    assert(!sargo_compatible_data(valid, sizeof valid - 1));
    assert(!sargo_compatible_data("google,bonito", sizeof("google,bonito")));
    assert(!sargo_compatible_data("google,sargo-extra", sizeof("google,sargo-extra")));
    assert(!sargo_compatible_data("google,sargo\0\0", sizeof("google,sargo\0\0")));
    assert(!sargo_compatible_data(NULL, 0));
    char root[] = "/tmp/sargo-lab-device-XXXXXX";
    assert(mkdtemp(root) && !chdir(root));
    assert(!mkdir("card", 0700) && !mkdir("card/mmcblk0rpmb", 0700));
    assert(!mkdir("other-card", 0700) && !mkdir("chars", 0700));
    assert(!symlink("../card/mmcblk0rpmb", "chars/503:0"));
    struct stat st = {.st_mode = S_IFCHR | 0600, .st_rdev = makedev(503, 0)};
    write_dev("503:0\n");
    assert(!sargo_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    st.st_rdev = makedev(504, 0);
    assert(sargo_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    assert(!symlink("../card/mmcblk0rpmb", "chars/504:0"));
    write_dev("504:0\n");
    assert(!sargo_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    assert(sargo_rpmb_identity_at(&st, "card/mmcblk0rpmb", "other-card", "chars"));
    assert(!unlink("chars/504:0") && !symlink("../other-card", "chars/504:0"));
    assert(sargo_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    assert(!unlink("chars/504:0") && !symlink("../card/mmcblk0rpmb", "chars/504:0"));
    const char *invalid[] = {"", "-1:0\n", "+504:0\n", "504:-1\n", "504:0 junk\n",
                             "504:0\nextra", "504:0", "4294967800:0\n", "504:1\n"};
    for (size_t i = 0; i < sizeof invalid / sizeof *invalid; ++i) {
        write_dev(invalid[i]);
        assert(sargo_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    }
    write_dev("504:0\n");
    st.st_mode = S_IFREG | 0600;
    assert(sargo_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    assert(sargo_rpmb_identity(&st)); /* Refuse before consulting real sysfs. */
    assert(!unlink("card/mmcblk0rpmb/dev") && !unlink("chars/503:0") && !unlink("chars/504:0"));
    assert(!rmdir("chars") && !rmdir("card/mmcblk0rpmb") && !rmdir("card") && !rmdir("other-card"));
    assert(!chdir("/") && !rmdir(root));
    puts("PASS dynamic majors, matching card and char identity, malformed attributes and non-device refusal");
}
