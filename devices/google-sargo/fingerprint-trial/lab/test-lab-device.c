/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include "lab-device.h"
#include <assert.h>
#include <unistd.h>

static void write_dev(const char *text)
{
    FILE *f = fopen("card/mmcblk0rpmb/dev", "w");
    assert(f && fputs(text, f) >= 0 && !fclose(f));
}

int main(void)
{
    char root[] = "/tmp/sargo-lab-device-XXXXXX";
    assert(mkdtemp(root) && !chdir(root));
    assert(!mkdir("card", 0700) && !mkdir("card/mmcblk0rpmb", 0700));
    assert(!mkdir("other-card", 0700) && !mkdir("chars", 0700));
    assert(!symlink("../card/mmcblk0rpmb", "chars/503:0"));
    struct stat st = {.st_mode = S_IFCHR | 0600, .st_rdev = makedev(503, 0)};
    write_dev("503:0\n");
    assert(!lab_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    st.st_rdev = makedev(504, 0);
    assert(lab_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    assert(!symlink("../card/mmcblk0rpmb", "chars/504:0"));
    write_dev("504:0\n");
    assert(!lab_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    assert(lab_rpmb_identity_at(&st, "card/mmcblk0rpmb", "other-card", "chars"));
    assert(!unlink("chars/504:0") && !symlink("../other-card", "chars/504:0"));
    assert(lab_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    assert(!unlink("chars/504:0") && !symlink("../card/mmcblk0rpmb", "chars/504:0"));
    const char *invalid[] = {"", "-1:0\n", "+504:0\n", "504:-1\n", "504:0 junk\n",
                             "504:0\nextra", "504:0", "4294967800:0\n", "504:1\n"};
    for (size_t i = 0; i < sizeof invalid / sizeof *invalid; ++i) {
        write_dev(invalid[i]);
        assert(lab_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    }
    write_dev("504:0\n");
    st.st_mode = S_IFREG | 0600;
    assert(lab_rpmb_identity_at(&st, "card/mmcblk0rpmb", "card", "chars"));
    assert(lab_rpmb_identity(&st)); /* Refuse before consulting real sysfs. */
    assert(!unlink("card/mmcblk0rpmb/dev") && !unlink("chars/503:0") && !unlink("chars/504:0"));
    assert(!rmdir("chars") && !rmdir("card/mmcblk0rpmb") && !rmdir("card") && !rmdir("other-card"));
    assert(!chdir("/") && !rmdir(root));
    puts("PASS dynamic majors, matching card and char identity, malformed attributes and non-device refusal");
}
