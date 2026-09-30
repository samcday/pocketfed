# Daily sam-sargo acceptance

Latest status, 13 September: the device-pool fix is installed as kernel `.12`.
The exact approved deployment booted with SELinux enforcing, the existing PIN
configuration and all eleven prior pinned deployments preserved. The installed
production stack passed 50 ordinary fprintd Claim/Release cycles across ten
service lifetimes and 50 explicit stops in 58.35 seconds. UART independently
confirmed every completion with no observed stall signatures or intervening
reboot. Sam then passed additional finger enrollment, a dozen more dialog
reopens and sampled matching/nonmatching feedback. The subsequent normal reboot preserved enrollments and automatic fingerprint
activation. After PIN login, Sam passed roughly six cycles alternating multiple
fingers, wrong-finger rejection, PIN fallback, Phosh unlock and the Settings
tester. The device stayed responsive on the same .12 boot without UART stall
signatures. Settings/Phosh acceptance is complete. See
[the pool-fix acceptance record](pool-fix/README.md),
[kernel PR #3](https://github.com/samcday/linux/pull/3) and
[validation PR #62](https://github.com/samcday/pocketfed/pull/62).
The following sections preserve the earlier `.11` failures and recovery history.

Current status, 13 September: second-finger enrollment, both fingers' Settings
match feedback, wrong-finger rejection, both Phosh fingerprint unlocks, and PIN
fallback followed by fingerprint unlock all passed in the live daily session.
The Settings race fix was applied live from its verified cached deployment.
However, reopening the normal Settings fingerprint dialog then froze the phone
again with production libfprint and no kernel tracing. Reliability acceptance
therefore remains failed; the planned reboot acceptance was not started.
UART shows fprintd worker TID 10733 on CPU 1, which did not provide a backtrace;
CPU 3 waits for RCU and CPU 5 waits during BPF cleanup. This reproduces the
problem independently of the earlier trace-reader complication. The exact
fingerprint operation remains unknown. See [the current desktop trial and
freeze](settings-direct-trial-20260913.json). The fleeting bad-fingerprint/PAM
message on Phosh is retained there as a separate UI follow-up.

The earlier five plain Claim/Release cycles passed, but were insufficient to
establish reliability. See [the diagnostic comparison](driver-trace/tracing-and-plain-observation-20260913.json).

A subsequent no-capture test pinned all fprintd threads to CPU 7. Claim 1 passed;
Claim 2 froze after INIT returned, while allocating the next command's bounce
memory. The fingerprint worker waited in CMA/RCU; CPU 2, running systemd-oomd,
did not answer the CPU-backtrace request. No kernel probes were active. CPU
affinity therefore does not resolve the problem. The phone was recovered with
one UART SysRq reboot, retaining persistent masks on fprintd and the Phosh
fingerprint socket/template. See [the CPU 7 failure](driver-trace/cpu7-observation-20260913.json).

On the recovered boot, 1,000 DMA-heap allocation/release operations of 8 KiB each
passed both [without secure apps](driver-trace/cma-baseline-result-20260913.json)
and [with the FPC app loaded but no sensor commands](driver-trace/cma-loaded-result-20260913.json).
A third test completed INIT and all 1,000 allocations, then spontaneously reset
before a DEEP_SLEEP result was recorded. Sam confirmed he did not restart it.
The exact reset point is unconfirmed because UART ended mid-line before the
next command's entry marker. These allocation checks do not exercise coherent
virtual mappings, nor exactly match the current 12 KiB FPC bounce pool size.
See [the INIT/allocation comparison](driver-trace/init-cma-observation-20260913.json).
Normal fingerprint activation remains paused; PIN PAM is unchanged.

The matching [CPU-latency comparison](driver-trace/init-cma-qos-observation-20260913.json)
also reset after INIT and at least 900 allocations. Its temporary zero-microsecond
CPU-latency request was verified active before loading the secure app; the reset
prevented the final idle-counter check. This did not establish a power-state
workaround. The next isolated kernel comparison changes only invoke staging to
use the driver's existing long-lived TZ memory pool, avoiding coherent allocation
and unmapping on each invoke. It remains an experiment, not an accepted fix.

The exclusively assigned `A5069RR4` UART remains capturing daily sam-sargo.
No global USB-host reservation applies; test-sargo and its named UART belong to
another task and are left alone. See [the UART assignment](uart-assignment-20260913.json).
The earlier standalone initialization checks on CPU 7 and CPU 1 both passed;
see [the CPU comparison](cpu-compare/README.md).

The following sections retain the earlier deployment and recovery history.

Current status (12 September): Sam requested a direct daily-device UART retest.
The new modem-preserving candidate is booted, and the native recovery **passed**
with every stage captured over UART. The original secret and all earlier attempt
history were preserved. Sam enrolled his right index finger in Settings, confirmed
matching/nonmatching feedback, and unlocked the Phosh lockscreen by fingerprint
without entering a PIN. See [the first desktop acceptance](desktop-first-acceptance-20260912.json).
Adding a second finger exposed a Settings VerifyStop/EnrollStart ordering race;
the patched Settings RPMs passed regression tests and were applied live.
An unexpected reboot discarded that unfinalized update. On the original
Settings version after PIN login, Sam successfully enrolled a second finger,
then reported another freeze with USB still connected. UART subsequently captured
a kernel stall: CPU 2 waits in BPF cleanup/cross-CPU synchronization, CPU 0 also
waits for cross-CPU synchronization, and CPU 1 did not answer the CPU-backtrace
request. The initiating fault remains unconfirmed. Sam force-restarted to
fastboot, and the verified daily phone then booted normally with UART retained.
The fresh PIN login and ordinary fprintd activation passed; the original
right-index enrollment is listed, while the second finger is absent. Touching
the enrolled finger on the lockscreen before swiping then froze the phone again.
UART captured fprintd starting, a display timeout 0.26 seconds later, RPMh
request timeouts, and another boot sequence. The precise failing driver call
is not yet known. On the following boot, automatic Phosh fingerprint attempts
are paused with a runtime socket mask; PIN access remains available. The mask
expires on reboot. Metadata-only tracing is being prepared before another touch. See
[the fresh boot](fresh-boot-observation-20260912.json),
[the freeze evidence](freeze-observation-20260912.json), and
[the live update](mm/settings-live-update-result-20260912.json).
A subsequent traced Claim/Release trial reproduced a stall without a capture
request: sensor reset returned, then the initialization TEE ioctl did not.
The task dump places the fingerprint worker on CPU1, which did not answer the
automatic backtrace; SSH later stalls in BPF cross-CPU synchronization. See
[the traced initialization trial](driver-trace/claim-only-observation.json).
Daily enrollment persistence and reliable unlock after reboot remain unverified.
See [the current UART result](uart-recovery-result-20260912.json)
and [current deployment details](mm/README.md). Earlier failure/staging sections
below are retained history; their old authorization/status limits predate this
new user-requested test. The earlier bootreason flag did not establish that
recovery caused a watchdog reset.

The target is Settings enrollment and Phosh lockscreen unlock after the first
PIN login following reboot. Preserve homed encryption and the existing PIN PAM
route. Phrog is outside this goal.

The dedicated test phone passed enrollment, a genuine match, and—after fixing
FPC identification finalization—persistent match/nonmatch across disposable
reboots. The packaged service chain then passed match/nonmatch with enforcing
SELinux. Its receiver registered the RPMB listener, but that verification-only
run did not exercise an authenticated write callback. See
[the recorded run](../lab/fprintd-services-unmasked-result.json).

The 12 September daily-phone refresh found a newer Plymouth deployment:
`0a32cb8e3b19f53ea0525b1c07a9bd932060fd9a2253a6b97bb478e078fd48a4`,
from image `29e0cb65295162732906be1d0acb3915484ab229f4cb4f22a85657527ad48fdc`.
The local update derives from that exact image. Six hash-verified local RPMs
supply listener/RPMB 1.4, native broker 0.4, libfprint 1.6 and broker policy 0.2.
They are local unsigned build artifacts; only this explicit image transaction
omits RPM signature checking, while retaining digests and dependency checks.
No repository or system verification policy is changed.

The candidate is
`39fd4d186f6235332d3ae1c6101b676091243d57d9d7d609a91f8962448f54b1`;
its OCI manifest is
`sha256:0e9857f2e728ae874706925166e42bc18123d2b17b28ee1ea65f6f2a88f6a1c0`.
The full inherited OCI verifier and bootc lint passed. Independent comparison
confirmed unchanged embedded boot payload, kernel/DT/modules, current 95-module
initramfs inventory, authentication files, unrelated packages and systemd files.
The historical validator assumed an older initramfs containing two DRM modules;
the current comparison preserves the exact newer baseline instead. All five
fingerprint activation masks remain in the candidate. See [build evidence](upgrade-build.json).

`stage-candidate.py` rechecks handset identity, exact current deployment, package
requests, policy bytes, inactive services and every OCI blob. It pins the current
deployment and preserves prior pins, then stages with finalization locked.
It does not reboot or run any credential operation. Inspect the actual staged
root and its locked state before activation.

The staged deployment is
`6f5d5fe5b07a9ca3ef9b74a3782b4d4e9ec964411fb27b7dcd135e1b63544e4b`.
[Staged inspection](staged-inspection-20260912.json) passed for all 945 package
rows, preserved requests/pins, slot and boot payload. The
[regular-file boot preview](boot-preview-20260912.json) also passed; this check
wrote no partition. At inspection time, activation and credential recovery had not run.

The old running SELinux policy does not know the new broker executable type,
so the SSH caller sees `unlabeled_t`. An OSTree metadata read showed the stored
`pocketfed_fpc_auth_exec_t` context, and the inspected checkout shares the same
inode as that verified OSTree object. This is consistent with the kernel's
[SELinux getsecurity handling](https://raw.githubusercontent.com/torvalds/linux/master/security/selinux/hooks.c):
raw unknown contexts require the MAC-admin permission. No relabel or policy load
was needed. `startup-once.py` still requires the proper mapped executable label
after booting the new policy.

After fresh approval, `activate-candidate.py activate-reviewed-candidate`
rechecks the staged deployment and preview before finalizing the exact OCI
manifest and rebooting. `startup-once.py` then verifies the booted deployment,
enforcing policy and unchanged PIN PAM file before starting only the listener,
loaders and per-boot key exchange. The separately frozen recovery launcher is
run once only after those prerequisites pass. Settings enrollment and real
Phosh lockscreen acceptance remain outstanding.

## Remaining credential recovery

Daily UID 1000 maps to reserved native Gatekeeper UID `0x700003e8`. The first
provisioning and already-approved one-time recovery failed; the latter returned
secure status -30 and no handle. The original 160-byte intent and consumed
132-byte receipt remain. Neither is permission to retry.

`recover-storage-once.c` is a separately reviewed candidate for the corrected
storage path. It requires the exact prior receipt and valid original intent,
refuses completed credentials and previous new attempts, and uses the original
random service secret. It durably saves a new exclusive receipt and an exact
private copy of the original intent before one Gatekeeper enrollment for the
fixed reserved UID. It preserves the old receipt and intent snapshot on success
or failure. There is no loop, replacement of another UID, or automatic retry.
It emits statuses and lengths only; sensitive buffers are cleared.

Host and ARM64 synthetic tests exercise the real codec and store, wire identity,
original-secret reuse, bad/unsafe/partial state, four durability failures,
cancellation, secure failure, malformed reply, successful commit and replay
refusal. Bundle tests cover file integrity, ownership/modes, symlink rejection,
exact unit identity, no automatic activation and public-TEE-only device access.
See [recovery build evidence](recovery-build.json).

`prepare-recovery.py` produces a frozen bundle bound to the accepted new
checksum and policy. `launch-recovery.py` additionally requires the correct
daily serial, enforcing policy, healthy exact packaged receiver/startup chain,
masked inactive fingerprint clients and unchanged failed-state metadata. The
runtime directory, systemd start limit and durable C receipt independently
prevent accidental repetition. It must not be run without new explicit approval
for this separate daily-phone recovery. No lab credential or biometric record
is copied to the daily phone.

## Installed acceptance follow-up

The approved reboot reached the exact candidate checksum with enforcing SELinux,
correct mapped broker label, unchanged PIN PAM hash and a healthy graphical
boot. The display manager is `phrog.service`; inactive `greetd.service` by itself
is not a boot failure.

The preserved Plymouth baseline contained the older firmware extractor and
service, so startup first failed at `226/NAMESPACE` for missing `vendor_b` before
loading a secure application. [The guarded cache correction](enable-cached-firmware.py)
installed the existing tested `--ensure` helper under `/usr/local/libexec` and
an `/etc/systemd/system` override. All 16 cached firmware files passed the pinned
hash, structure and ownership checks. The coordinated listener, loaders and
Keymaster startup then completed under enforcing SELinux with no service restart.
The original startup failure record remains.

The frozen recovery first failed at `203/EXEC` from `/run`; no native code ran
and no new durable recovery receipt existed. The same binary at
`/usr/local/libexec/pocketfed-fpc-storage-recovery-20260912` returned the expected
status 2 with an invalid argument under the same unit restrictions, before
opening credential state. [The guarded launch correction](complete-recovery-after-exec-failure.py)
retains that evidence and changes only the original unit's executable path.
It refuses any native attempt or original failure other than 203/EXEC.

SSH disconnected during the subsequent launch. Reconnection confirmed a new
boot with `androidboot.bootreason=watchdog`. The new native receipt and exact
intent snapshot exist, while no completed credential was saved. No secure return
status or pstore crash trace survived, so the exact point of failure remains
unknown. [The metadata-only result](recovery-watchdog-result-20260912.json) records
the retained state. The listener and fingerprint clients are masked again, and
the temporary sleep inhibitor is stopped. Do not relaunch or delete receipts.
Continue diagnosis on the dedicated test handset. The frozen binary is unchanged;
daily Settings and Phosh acceptance remain pending.

The subsequent [lab native-verification probe](../lab/native-auth-v2-result-20260912.json)
passed Keymaster attachment and verification through the packaged receiver
under enforcing SELinux. Keymaster, TrustZone and cached FPC/common-library
firmware hashes match across both handsets. The daily prior-boot journal has
no recorded suspend operation near the failed launch, but also lacks the
native call's outcome; absence of a log does not rule out an unrecorded event.
An isolated lab enrollment with the same UID mapping is the next comparison.
The daily recovery receipt remains consumed; none of these diagnostic results
authorizes another daily credential replacement.

## Reconciliation with the 12 September ModemManager rollout

Sam confirmed the new ModemManager deployment and authorized staging a new
fingerprint candidate. The current booted checksum is
`06d451841d0119060d454da1744bdb47ce1bec3815530775aec3be4f235560b2`,
with ModemManager 1.25.95-1.pocketfed, libqmi 1.38.0-1.1.pocketfed, kernel .8,
and GNOME Settings 51~rc.1-1.fc46. Its immutable source OCI is
`ghcr.io/samcday/sam-sargo@sha256:f99cc04bed61613a1704a71024421c8188a65b25ee084d2f47b650217621802d`.
The old fingerprint candidate must not replace this newer baseline unchanged.

The new preparation in `mm/` uses an offline re-export of the exact stored OCI,
because direct registry access failed. It rebuilds the GNOME row fix against
the installed RC version and composes the fingerprint policy from the new
base's own policy. Artifacts and logs are under
`out/fingerprint-daily-mm-20260912`. Candidate build, independent comparison, locked staging and boot preview
now passed; see [the MM-preserving staging result](mm/README.md). This is not
daily fingerprint enrollment or unlock acceptance.

Lab enrollment with daily's UID mapping and a subsequent verification after
six minutes of storage runtime suspend both passed. Daily native state still
has no completed credential, and its recovery receipt remains consumed. The
new staging authorization does not authorize another credential replacement.

## Recovery after repeated sensor-startup freezes

Later UART-observed daily native recovery, right-index enrollment and a Phosh
fingerprint unlock succeeded; the subsequent sensor-startup freezes remain
unresolved. See `mm/README.md` and `driver-trace/claim-only-observation.json`
for that later evidence. A Claim-only attempt stopped inside the initialization
TEE invocation before any capture or verification request. The implicated worker
was running on the CPU that did not answer diagnostic backtraces. This narrows
the failure boundary but does not yet distinguish kernel staging from secure
world execution.

After Sam reported another freeze while logging in and returned daily
`994AY18RSD` to fastboot, the old runtime-only scan pause was insufficient: it
did not survive reboot. `prepare-paused-boot.py` produces a temporary boot image
with only command-line header changes, preserving the installed `.11` kernel,
shim, DTB and initramfs byte-for-byte. All four payload hashes match the verified
MM-preserving deployment. The targeted `fastboot boot` succeeded without any
flash, erase or slot change, reaching boot ID
`0ac24861-f5de-4f09-8128-fd24c2f80070`, the same `d639…` deployment, enforcing
SELinux, Wi-Fi, SSH and the display manager.

`pause-fingerprint.py` installed persistent `/etc/systemd/system` masks for
`fprintd.service`, `phosh-fingerprint-auth.socket` and
`phosh-fingerprint-auth@.service`. All are verified masked and inactive; the
original PIN PAM hash, deployment and eleven pins remain. A bare-template
property query failed after the masks were installed; an unstarted named
instance then verified the template mask, preserving the original attempt
receipt. No credential or template stores were opened. The physical PIN-login
check is pending. These masks contain the fingerprint path during investigation;
they are not a kernel fix. The immediately preceding failed boot retained no
fingerprint-unit journal entries, so that login freeze's cause is not proven.

UART was released for Sam's requested dongle rename. The coordinating task
reported unchanged EEPROM readback after its write attempt and released all
handles. Capture resumed on the existing `A5069RR4` by-id path with
`capture-uart.py --uart-only`; this holds only the daily device lock and leaves
the global USB-root hosting lock to the independent test-sargo session. Do not
take test-sargo until the Premouth task explicitly releases it.

The recovery artifacts and receipt are in `out/fingerprint-daily-recovery-20260912`;
the retained observation is `fastboot-recovery-observation-20260912.json`.
Live read-only checks confirm tracefs and all three planned SCM probe symbols
exist. No probes have been installed and no sensor has been opened during this
recovery. `driver-trace/kernel-boundary-plan.json` describes the next experiment.
## Current UART assignment, 13 September

Sam explicitly assigned
`/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_A5069RR4-if00-port0`
exclusively to this task for daily `sam-sargo` (`994AY18RSD`). The independently
named `test-sargo` adapter and test handset belong to the other session and
must be left alone. The prior global USB-host reservation process is withdrawn;
historical coordination notes below are not current prerequisites.

`capture-uart.py` now always takes only the daily handset lock and exclusive
ownership of its assigned UART. Its old `--uart-only` argument remains accepted
for existing commands but no longer changes behavior. A new receive-only capture
was verified with a serial/boot-ID marker from sam-sargo's SSH console output.
See `uart-assignment-20260913.json`. Fingerprint services remain masked/inactive.
