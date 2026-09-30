# Sensor-touch freeze tracing, 12 September

Daily sam-sargo froze when Sam touched his enrolled finger on the lockscreen
before swiping. UART first recorded the fingerprint worker/fprintd starting,
then a display frame timeout about 0.26 seconds after fprintd started, RPMh
completion timeouts, and another boot. The record does not yet show whether
the failing operation was initialization, capture or identification.

The following boot is `51d59842-0056-46a5-a417-532ef194ad54`. The Phosh fingerprint
socket has an inactive runtime mask. That mask expires on reboot; PIN access
remains available. See [the fresh-boot record](../fresh-boot-observation-20260912.json).

This diagnostic build records fixed stage names, operation numbers, return
statuses, monotonic timestamps, thread IDs and CPUs. It records neither buffer
contents nor addresses, template IDs, identity decisions or token values.
`trace.h` emits one bounded stderr write and preserves errno even if writing
fails. Logging adds latency, so an apparent improvement under tracing alone
would not establish a fix.

The source is the exact libfprint 1.6 patch stack on commit
`430e24e538ba137b6edcfe2e1b3b8cc29c66fa6a`. [The patch](trace.patch) changes only
diagnostic markers around the worker, sensor open/reset/wakeup, TEE session and
invoke calls, and protocol dispatch. It is intentionally outside the production
RPM spec. The source generator rejects changed source/archive inputs.

[Host checks](host-checks.json) passed against the actual instrumented protocol,
transport and sensor code, including negative paths and cleanup. A separate
test confirms successful/failed trace writes both preserve errno.
[The ARM64 build](arm64-build-result.json) passed all 176 build targets and all
seven selected unit/FPC tests. Introspection and installed test packaging were
disabled for this diagnostic library; this is not a new production RPM.
The historical toolchain image had been removed. Its replacement derives from
the pinned cached GNOME toolchain plus the libfprint spec's build dependencies.
The first compiler-discovery failure is retained under the generated run's
`.attempt1` files. The temporary approval-review usage error cleared on retry.

Generated source/build/artifacts live in
`out/fingerprint-driver-trace-20260912-v2`. `prepare.py` and `check.py` regenerate
the patch and host checks. `build-arm64.py --prepared PATH --image sha256:ID`
verifies the source and image before an offline container build. The complete
toolchain is `sha256:69ffaa7c0dec7f64cdd3cbfb877f69d3d7b7d840a5afc961e66ecba4bbcc9135`.

The device installer is bound to daily serial `994AY18RSD`, the boot above,
libfprint 1.6's installed library hash and the unchanged PIN PAM hash. It
requires enforcing SELinux, the Phosh socket mask and inactive fingerprint
services. It places the extra library under `/usr/local/lib64` with the original
library's SELinux label, then binds it into fprintd through one `/run` drop-in.
It starts a passive journal relay to the already-owned UART. Distribution
library bytes and authentication files remain intact. No reboot is requested.

`claim-only.py` first verifies that fprintd actually sees the traced library.
It lists existing labels, claims the sensor for Sam, then releases it. It never
starts enrollment, verification, deletion or native credential recovery. Its
one-attempt receipt prevents accidental repetition. This deliberately tests
initialization separately from physical touch. The [live claim-only trial](claim-only-observation.json) stalled: open, TEE
session creation and reset returned, then sensor initialization (target 10,
command 0) entered TEE_IOC_INVOKE without a return marker. Claim timed out after
45 seconds. CPU7 later soft-locked in SSH seccomp/BPF cross-CPU synchronization;
CPU1 did not answer the automatic backtrace. Kernel staging versus secure-world
execution still needs separation. No capture or matching request was issued.
The initial Python helper lacked gi.repository and stopped before activation;
the actual trial used the compiled GLib client with the same device guards.

After the trial and once fprintd is inactive, remove only
`/run/systemd/system/fprintd.service.d/99-call-trace.conf`, reload systemd, and
stop the passive relay. The Phosh socket pause is separate and must be removed
when reliable fingerprint unlock can be tested. Both runtime changes expire on
reboot, while the unused extra library and private evidence remain available.

[The stock comparison](stock-comparison.json) found matching reset/IRQ wiring
and no established missing clock vote. Qualcomm's generic ioctl path can vote
for bandwidth/clocks, but the matching SDM670 include declares
`qcom,no-clock-support` and does not enable `qcom,support-bus-scaling`; its probe
rejects that combination. This is a reason to trace first, not evidence that
all power-management behavior is correct. No kernel or power change was made.
