/* SPDX-License-Identifier: MIT */
/* Dedicated authenticated-storage trial. Included after the receiver globals.
 * Opaque signed writes only, no key programming, no replay after uncertainty. */
#include <sys/prctl.h>
#define WRITER_RUN "sargo-fingerprint-lab-gatekeeper-storage-rw-20260911"
static bool writer_authorized, writer_failed;
static unsigned writer_groups;

static bool writer_token(const char *line, const char *wanted)
{
    size_t n = strlen(wanted);
    while (*line) {
        while (isspace((unsigned char)*line)) ++line;
        const char *end = line;
        while (*end && !isspace((unsigned char)*end)) ++end;
        if ((size_t)(end - line) == n && !memcmp(line, wanted, n)) return true;
        line = end;
    }
    return false;
}

static bool writer_identity_line(const char *line)
{
    return writer_token(line, "androidboot.serialno=99NAY1AZG1") &&
        writer_token(line, "pocketfed.root_mode=usb") &&
        writer_token(line, "pocketfed.liveboot=" WRITER_RUN);
}

static bool writer_identity(void)
{
    char line[8192];
    FILE *f = fopen("/proc/cmdline", "re");
    if (!f) return false;
    bool valid = fgets(line, sizeof line, f) &&
        (strchr(line, '\n') || feof(f)) && writer_identity_line(line);
    fclose(f);
    return valid;
}

static int bounded_transfer(void *context, bool write,
    const void *request, size_t request_frames,
    void *response, size_t response_frames)
{
    if (!writer_authorized || stopping) return -EPERM;
    if (write && (writer_failed || writer_groups >= 8)) return -EPERM;
    if (write) ++writer_groups; /* Reserve before any potentially ambiguous IO. */
    int rc = sargo_rpmb_mmc_transfer(context, write, request, request_frames,
                                    response, response_frames);
    if (write) {
        const unsigned char *p = response;
        unsigned type = !rc && response_frames == 1 && p ? p[510] * 256u + p[511] : 0;
        unsigned status = !rc && response_frames == 1 && p ? p[508] * 256u + p[509] : 0xffff;
        if (rc || type != 0x300 || status) writer_failed = true;
        fprintf(stderr, "event=rpmb_write_group group=%u frames=%zu transport=%d "
                "response_type=%u device_status=%u further_writes=%s\n",
                writer_groups, request_frames, rc, type, status,
                writer_failed || writer_groups >= 8 ? "disabled" : "bounded");
    }
    return rc;
}
