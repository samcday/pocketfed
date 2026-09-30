# Initialization boundary trace on test-sargo

The daily Claim-only reproduction stopped after entering `TEE_IOC_INVOKE`
for target 10 / command 0. CPU 1 was running the fingerprint worker and did
not answer the subsequent backtrace request. This experiment separates kernel
request staging, QSEE serialization and the SCM execution helper.

`initialize-once.c` links the **same hash-verified protocol, transport and sensor
sources** used by the daily diagnostic libfprint. It opens the sensor and TEE
session, resets, initializes, requests deep sleep only after initialization
succeeds, and closes after calls return. It does not call capture, database,
matching, enrollment, authentication or credential APIs. It requires exact
test-sargo serial `99NAY1AZG1`, USB-root mode and the exact run token, with an
exclusive runtime attempt marker. It cannot run on daily sam-sargo.

`trace-init.py` creates a dedicated trace instance and six uniquely named
kprobe/kretprobe events around `qcom_scm_qseecom_app_send`, `__scm_smc_call`
and `__scm_smc_do_quirk`. Only the two functions returning integers have a
signed return-value fetch; the void quirk helper has none. The event filter
starts with the controller PID and inherits children before the init executable
runs. Its reader emits only PID, CPU, monotonic time, fixed event names and
integer status, discarding rendered instruction/caller addresses. It confirms
a trace marker before invoking the sensor. Output is capped at 256 records;
overflow prevents a passing result.

The known ordered startup overlay supplies firmware, read-only RPMB reception,
cmnlib, FPC residency and Keymaster setup. Production fprintd and desktop/auth
clients stay masked. No credential or biometric records are copied into this
fixture. The kernel, DTB and modules are the existing coherent `.11` set from
the cached MM-preserving image. No kernel behavior or power setting changes.

A probe observation timeout does not kill or repeat the secure caller. The
controller stays alive, preserving its trace and services for explicit whole-
guest UART recovery. With completed calls, it stops the secure services and
removes only its own trace instance/events. USB-root hosting must remain alive
until the guest has demonstrably rebooted to fastboot.

The ARM64 build and metadata parser checks passed. The fixture passed root
layout, policy-composition and label validation, and boot preparation passed
using tool snapshots from the accepted ordered-startup trial. These are host
checks, separately recorded from the live result below.
See `prepared-result.json` for hashes and exact limits. Generated artifacts:
`out/fingerprint-kernel-trace-20260913`.

The `samsung-a5` task (`01a09377-6cf7-7952-ae12-46e959823eb0`) explicitly lent
its idle hosting slot for this bounded trial. Test-sargo booted the sealed
candidate, registered all six probes, and confirmed the trace marker. Both
initialization and deep sleep returned transport/outer/command status 0.
All nested app/SCM/quirk entries and returns were captured without dropped
records. Initialization took 245.278 ms; deep sleep took 14.032 ms. Secure
services stopped cleanly and the controller removed its owned probes/instance.

The handoff report passed enforcing SELinux, overlay root and matching modules,
but one interleaved IPA printk line prevented automatic recognition. A separate
artifact removes exactly that complete inserted line and parses the original
JSON; the raw UART and removal record are retained. No automatic runner pass or
`result.json` was manufactured. Repeated startup snapshots also shared a report
name, conflicting in the checksummed collector. Excluding only that progress
name recovered the other complete checksummed reports; the final report retains
every startup result. Source now emits separate names per unit, with a regression
check. The frozen executed image is unchanged.

UART acknowledged the explicit SysRq reset, and exact serial `99NAY1AZG1`
returned product `sargo` in fastboot before its host was stopped. Fresh lock and
UART-owner checks confirmed release. A5 was notified that its reservation was
returned; coordinate before taking the slot again. See `live-result.json`.

Daily sam-sargo remains on the recovered boot with persistent fingerprint
masks; it was still reachable after 24,149 seconds in the read-only check.

Even a successful lab trace only establishes this initialization path on
test-sargo. It does not resolve the daily freeze, validate full fprintd Claim,
or accept enrollment/Phosh unlock. No finger touch is required for this round.

One observed difference is CPU placement: this initialization entered on CPU 5
and returned on CPU 7, whereas the daily stuck worker ran on CPU 1. That is a
candidate controlled comparison, not a diagnosed cause. A next test can pin the
same initialization probe to CPU 1, retaining the current configuration and
transport; it needs another coordinated hardware slot. USB-root activity and
the absence of fprintd's full open path remain separate differences from daily.
