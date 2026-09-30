/* SPDX-License-Identifier: LGPL-2.1-or-later */
/* Diagnostic-build-only markers. Call with literal stage names and operation
 * numbers/statuses only. Never pass buffers, addresses, IDs or token values.
 * One bounded write per marker; tracing failures must not change errno or the
 * driver result. This deliberately adds latency and is not production logging.
 */
#ifndef FPC_TRIAL_TRACE_H
#define FPC_TRIAL_TRACE_H
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static inline void
fpc_trial_trace(const char *stage, int64_t a, int64_t b, int64_t status)
{
    int saved_errno = errno;
    struct timespec now = {0};
    unsigned cpu = 0;
    long tid = syscall(SYS_gettid);
    int cpu_result = syscall(SYS_getcpu, &cpu, NULL, NULL);
    char line[192];
    (void)clock_gettime(CLOCK_MONOTONIC, &now);
    int n = snprintf(line, sizeof(line),
                     "FPC_TRACE %lld.%06ld tid=%ld cpu=%d %s a=%lld b=%lld status=%lld\n",
                     (long long)now.tv_sec, now.tv_nsec / 1000, tid,
                     cpu_result ? -1 : (int)cpu, stage,
                     (long long)a, (long long)b, (long long)status);
    if (n > 0 && (size_t)n < sizeof(line)) {
        ssize_t written = write(STDERR_FILENO, line, (size_t)n);
        (void)written;
    }
    errno = saved_errno;
}
#endif
