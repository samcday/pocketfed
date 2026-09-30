# Daily CPU comparison, 13 September

Both guarded standalone probes passed on daily sam-sargo, serial `994AY18RSD`,
boot `0ac24861-f5de-4f09-8128-fd24c2f80070`, kernel `.11`, with enforcing SELinux.
CPU 7 completed INIT in 284.063 ms and DEEP_SLEEP in 18.531 ms; CPU 1 completed
them in 383.221 ms and 28.863 ms. Every nested kernel entry and return was captured
on the requested CPU, with zero transport status. Both service chains stopped
cleanly and their scoped probes were removed. See [result.json](result.json).

The probe uses the same instrumented protocol, transport and sensor sources as
the earlier fprintd trial. It opens the sensor and TEE session, resets, initializes,
puts the sensor to sleep and closes. It does not capture a finger or invoke any
database, authentication, enrollment or credential-recovery API. Production
fprintd and Phosh fingerprint activation remain persistently masked; PIN PAM is
unchanged. This demonstrates that CPU 1 can complete initialization. It does not
resolve the earlier full fprintd Claim freeze or establish reliable unlock.

SDM670's device tree assigns capacity 610 to CPUs 0–5 and 1024 to CPUs 6–7.
The initial proposed CPU 5 comparison incorrectly described it as a performance
core. That host-only artifact was rejected before device staging; the executed
second build compares CPU 7 and CPU 1. Neither run can migrate between CPUs.

Sources live here. Generated source snapshots, compiler invocation, checksummed
bundle, launch offsets and full metadata results are in
`out/fingerprint-daily-cpu-compare-20260913-v2`. The cached ARM64 compiler ran
offline with `-Wall -Wextra -Werror`; invalid arguments, unsupported CPU 5 and
wrong-device invocations returned 2 before sensor access. The reused trace
metadata and ordering checks passed.

The binary and controller independently bind to this exact serial and boot.
Per-CPU attempt directories and native exclusive receipts prevent repetition;
CPU 1 additionally requires a successful CPU 7 result. A timeout leaves a pending
secure caller and tracing alive for whole-device recovery. No receipt may be
deleted to retry. The private device directory is
`/var/tmp/sargo-fingerprint-cpu-compare-20260913`; installed diagnostics and runtime
units are inactive after both completed runs.
