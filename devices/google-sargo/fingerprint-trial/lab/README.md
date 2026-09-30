# Fingerprint experiments on test-sargo

Use the [PocketFed liveboot workflow](../../../../tools/liveboot/README.md)
on the dedicated handset serial `99NAY1AZG1`, with FTDI adapter
`/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_test-sargo-if00-port0`.
The user made this handset available for the fingerprint investigation on
11 September 2026. It is separate from daily-driver `sam-sargo` and its preserved
native credential recovery records.

USB-backed root and matching modules passed on this handset with kernel `.11`.
Reuse that transport and the local fingerprint image; the unfinished resident
RAM mode is unnecessary for these experiments. The host must keep serving USB
storage until the guest has rebooted. Use the runner's serial-bound selection,
exclusive locks, UART log and gated SysRq interface. Never select the other
attached fastboot handset implicitly.

## Initial metadata inspection

`inspect-device.py` is a boot-time reader restricted to this serial, a
fingerprint lab run token, and an overlay root. It reports device nodes,
eMMC capability metadata, service states, partition layout, and selected vendor
build fingerprints. If vendor_b exists it uses the installed firmware inspector
to compare exact program firmware against the pinned manifest. It performs no
secure calls, credential operations, partition writes, or firmware installation.
Only metadata is written to the UART report.

The first overlay retains the standard liveboot installation and USB guards,
adds this inspection service, and masks QSEE, the common-library/FPC loaders,
firmware staging, fprintd and authentication/provisioning services. Its local
source image is
`sha256:671197f9f3bf539fc4e1fd138843a8739df3958cabcacd0e5f9ca6a3baaa9996`.
The generated overlay is
`out/liveboot/overlays/sargo-fingerprint-inspect-20260911` and the fixture is
`out/liveboot/fixtures/sargo-fingerprint-inspect-20260911`.
The exporter must use `/usr/bin/python3` with `PATH=/usr/bin:/bin` for the
Fedora SELinux bindings; Homebrew's Python lacks `setools`.

The first run, `sargo-fingerprint-lab-inspect-20260911`, passed the enforcing
handoff in 64.40 seconds but did not execute the inspection. First-boot presets
removed its enablement link. UART SysRq HELP and reboot were acknowledged;
the handset returned to fastboot before its host was stopped. The corrected
profile at `out/liveboot/profiles/sargo-fingerprint-inspect-20260911.json` adds
`systemd.wants=pocketfed-fingerprint-lab-inspect.service`, matching the normal
liveboot checker's explicit command-line activation. The second run reuses the
exact fixture and `.11` kernel bundle; it changes only boot preparation.

The second run, `sargo-fingerprint-lab-inspect-02-20260911`, executed the reader
successfully. Both its handoff report and inspection JSON were interleaved with
kernel audit messages on UART. Complete JSON was recovered by removing those
complete injected printk lines; the original capture and the recovery method
and hashes remain beside `recovered-handoff.json` and
`fingerprint-inspection.json`. The runner itself reported `handoff-timeout`, so
its automatic status has not been rewritten as a pass. The recovered handoff
reports enforcing SELinux, disposable root, matching modules and no failed
units at its checkpoint. The reader's service completion was also logged.

Observed prerequisites:

| Item | test-sargo result |
| --- | --- |
| Vendor build | `google/sargo/sargo:12/SP2A.220505.002/8353555:user/release-keys` |
| Fingerprint node | `/dev/fpc1020`, character 10:262, root0600 |
| Public/private TEE nodes | `/dev/tee0` 501:0 and `/dev/teepriv0` 501:16, root0600 |
| RPMB node | `/dev/mmcblk0rpmb`, character 503:0, root0600 |
| MMC capabilities | multiplier 0x80, enhanced RPMB 1, reliable sectors 1 |
| Secure services | QSEE receiver, common-library/FPC loaders and auth services inactive |

The production firmware inspector refused the older vendor build before reading
the firmware payloads, as intended. This is not evidence that the actual FPC or
common-library bytes differ: the next read-only inspection must pin this lab
build explicitly and compare its firmware hashes. Do not weaken the existing
sam-sargo manifest. The changed dynamic character majors also mean the frozen
daily-driver diagnostic cannot be reused unchanged. Bind the lab adapter to
the actual kernel device identity rather than copying sam-sargo's numeric major.
The root image still says hostname `sam-sargo`; hardware serial, not hostname,
is the device identity for this lab.

Both preparations took about 9.6 seconds. After inspection, UART acknowledged
the second guest's SysRq reboot, fastboot listed `99NAY1AZG1`, and only then was
the host stopped. The control FIFO was removed and UART released. No enrollment,
RPMB transaction, secure-service activation or firmware staging occurred in
either lab run. No operation was performed on the physical sam-sargo.

## Subsequent secure-service experiments

First establish this handset's firmware identity and RPMB geometry from the
report. Then adapt the read-only receiver trial for the disposable environment;
do not run the daily-driver activation script, whose hostname and recovery
guards intentionally describe a different device. Compare receiver registration,
actual callbacks, service permissions and shutdown before enabling storage
writes or enrollment. A lab pass still needs final validation on sam-sargo.

The Linux writable overlay disappears at reboot, but RPMB is persistent
hardware storage. Before a credential experiment, arrange durable private
retention of that experiment's credential intent and outcome. Reboot is not a
rollback of Gatekeeper state, and daily-driver credentials or biometric records
must not be copied into a lab fixture.

## Read-only receiver result

`sargo-fingerprint-lab-readonly-20260911` passed automatic enforcing handoff in
57.85 seconds and produced checksum-verified inspection and receiver reports.
All **16 FPC/common-library firmware files are byte-for-byte identical** to
sam-sargo's pinned files, despite the older vendor build identifier. The separate
lab [manifest](firmware-manifest.json) records the observed source build; the
production manifest was not changed. The source mapping was writable at the
block layer, and inspection used read-only debugfs. Firmware was not staged.

The lab receiver validates the open RPMB descriptor against
`/sys/bus/mmc_rpmb/devices/mmcblk0rpmb/dev`, its MMC card parent and the matching
`/sys/dev/char` link. This passed on the observed dynamic major 503. Its source
producer snapshots the frozen receiver and changes only that identity check;
the daily-driver proposal remains unchanged. Host and ARM64 tests cover changed
majors, wrong parents/links, malformed attributes, protocol framing and both
independent write-refusal guards. Build/source hashes and run evidence are in
[readonly-build.json](readonly-build.json).

The receiver registered FS (10, 20 KiB), GPFS (0x7000, 504 KiB) and RPMB (0x2000,
25 KiB), reached Type=notify readiness, and then stopped successfully. Both
snapshots reported zero restarts; shutdown reported status 0 and MainPID became
0. No RPMB callback occurred, so this proves registration/lifetime handling,
not authenticated storage or Gatekeeper enrollment. No app was loaded and no
credential operation was performed. The next stage can use the measured lab
firmware to check Keymaster/FPC startup with the read-only receiver present.

`lab_report.py` emits small duplicated metadata chunks with an overall SHA256;
the collector requires a complete matching digest before accepting a report.
Its tests cover interleaved console noise, missing data and corruption.

This run also exposed a recovery interaction: `loglevel=3` suppressed the kernel
command line that the normal runner uses to arm SysRq. A one-time host recovery
verified the exact run's checksummed hardware report, live runner/host PIDs and
sole UART ownership, then used the runner's existing UART BREAK/reboot routine
while leaving USB hosting running. The original UART acknowledged reboot;
fastboot identity was checked before stopping the host and releasing UART.
`quiet-uart-recovery.json` in the run records that explicit recovery. The next
profile, `out/liveboot/profiles/sargo-fingerprint-readonly-console-20260911.json`,
removes `loglevel=3`; retain the normal kernel arming marker in future runs.

## Packaged Keymaster startup result

`sargo-fingerprint-lab-startup-20260911` passed enforcing handoff in 64.09 seconds.
The 16 verified firmware files were staged into the disposable root, all three
listeners registered, and cmnlib64 loaded. The packaged 0.3 Keymaster helper
observed wrapped-key status -24, then status 0 for both GET_HMAC and COMPUTE_HMAC.
Its final wrapped-key request returned **-16773121 (`0xff000fff`)**. The meaning
of this status has not been established. HMAC setup status alone does not prove
usable authentication state. No RPMB callback was recorded.

The controller stopped at that failure, before FPC loading or sensor probing.
There was no credential operation or RPMB data write. Normal gated SysRq reboot
was acknowledged, fastboot identified the test handset, and the USB host was
then stopped. The checksummed `startup_finished.json` preserves the exact steps;
[startup-build.json](startup-build.json) records the source and binary identities.

The next comparison keeps the same receiver, service restrictions and startup
order, using the older GET-only diagnostic that returned a validated 152-byte
wrapped key on sam-sargo. Its inspector also hashes the allowlisted signed
Keymaster and TrustZone program partitions; it does not copy their contents or
read credential stores. FPC/common-library equality does not establish equality
of these other firmware components.

`sargo-fingerprint-lab-sharing-20260911` completed that comparison: the earlier
GET-only helper returned the same final `0xff000fff` status. Both test-sargo
Keymaster partitions have SHA256
`8f800f36d6eef63373dc502462c5f52d1d779dd078e0ae429108ea86fcbb261a`, exactly matching
the privately inspected sam-sargo program. Both lab TrustZone partitions also
match each other; no sam-sargo TrustZone comparison was made. The automatic
enforcing handoff passed in 63.39 seconds, no RPMB callback occurred, and the
guest was rebooted to fastboot before stopping USB hosting.

Private static analysis identifies the wrapped-key handler's call to
`qsee_encapsulate_inter_app_message` at TA address `0xb77c`, with its status copied
back to the caller. The recipient comes from `get_fpta_name`, which consults
the `fpta_name` property and otherwise uses `fingerprint`. This supports testing
recipient residency before wrapping; it does not independently establish the
meaning or precise source of the observed error. The earlier successful daily
phone diagnostic had FPC loaded already, while the two failed lab sequences
requested the wrapped key before loading FPC. `prepare-ordered-overlay.py`
changes that ordering, retaining the same packaged helper and read-only receiver.

The ordered run, `sargo-fingerprint-lab-ordered-20260911`, **passed**. With FPC
loaded before Keymaster, the identical packaged helper returned a valid 152-byte
wrapped key; a second invocation reported `hmac_state=already-ready` without
repeating GET/COMPUTE_HMAC. Sensor initialization and deep sleep both returned
transport/dispatcher/command status 0. All service stop operations completed,
the receiver reported clean shutdown, and no RPMB callback occurred. The
checksummed final report includes every operation even where a separate UART
progress report was lost to interleaving.

The production startup service now requires and follows the FPC loader, and
loses readiness if that loader stops (`0.4` source). This fixes the demonstrated
ordering dependency; it does not assign a universal meaning to `0xff000fff`.
No credential operation, enrollment or matching was attempted. Secure-storage
acceptance and durable lab credential handling remain the next prerequisites.

The guest returned to fastboot before its USB host was stopped; UART was
released. The local `0.4` ARM64 RPM build passed its required test suite and
contains the corrected service. Its hashes and exact acceptance limits are in
[ordering-build.json](../../../../packages/fpc-auth/ordering-build.json).
The general `prepare-startup-overlay.py` producer now emits the accepted startup
sequence and maps the FPC dependency to the lab loader; new profiles/manifests
use the output name so they do not overwrite the historical run evidence.

The next [Gatekeeper storage trial](gatekeeper-trial.md) now has a tested
one-attempt helper, a durable private host intent, encrypted credential export
and a sealed private fixture. Host and ARM64 lifecycle/export tests passed.
Sam explicitly approved the real credential operation after automatic approval
review requested that authorization. The sealed trial then ran once: FPC and
Keymaster startup passed, but Gatekeeper failed with secure status -30 after
the listener rejected a read callback with RW version field 0. The prototype
had incorrectly required 2. No completed credential was exported; the original
intent and consumed launch receipt remain private and durable. The handset
returned to fastboot before hosting stopped. Details and the bounded protocol
correction are in [gatekeeper-trial.md](gatekeeper-trial.md).

Further metadata-only probes found the remaining read-framing mismatch: the
declared read length can be payload bytes (`count × 256`) while the request
itself is one complete 512-byte frame. Correcting that let Gatekeeper read its
table and request an authenticated initialization write. Preserving the opaque
RW field also matters: reads used 0, while the observed write used 0x100.

The [bounded authenticated-storage recovery](storage-recovery.md) then passed:
two authenticated write groups succeeded, Gatekeeper returned a validated
58-byte handle, and the credential was committed and retained privately on the
host. Both prior failure histories and the original secret were preserved.
All secure services stopped cleanly, and the handset returned to fastboot
before USB hosting ended. Credential verification, FPC token authorization and
actual fingerprint enrollment remain separate acceptance checks. The next
[authorization check](authorization.md) passed after reboot: Gatekeeper verified
the retained credential, issued a challenge/SID/type-validated HAT, and FPC
accepted it. No biometric samples or database operations were involved. The
fprintd [start/cancel and database reopen check](fprintd-preflight.md) then passed.
The first [interactive enrollment trial](fprintd-interactive.md) timed out during
the preliminary duplicate scan while Sam was away from the sensor. It did not
reach actual enrollment; the next run adds advance touch cues.

## Native credential diagnosis after daily activation, 12 September

Daily sam-sargo booted the accepted image, but its separately approved native
credential recovery ended in a watchdog reset without a completed credential.
Both slots of the Keymaster and TrustZone program partitions, and all 16 cached
FPC/common-library files, now have verified matching hashes across both phones.
Different firmware bytes therefore do not explain the failure.

The first `native-auth` diagnostic exited before storage/backend access because
its extra `/proc/cmdline` guard was incompatible with the confined broker domain.
The controller and unit already enforce the exact test serial, USB root and run
token. Removing that redundant read produced the passing
[native verification result](native-auth-v2-result-20260912.json): attachment,
version negotiation and verification of the retained lab UID 1234 all returned
success through the packaged receiver. SELinux stayed enforcing, the credential
was unchanged, services stopped cleanly, and USB hosting ended after fastboot.
The packaged receiver does not log successful RPMB writes, so this report does
not independently count write callbacks.

`native-enroll-probe.c`, `trial-native-enroll.py` and `prepare-native-enroll.py`
narrow the next experiment to a fresh native UID 1000 on **test-sargo only**.
It uses the same native UID mapping as daily sam-sargo with an independent
random secret. The original lab UID 1234 credential remains intact. The new
intent is retained privately before boot; any returned credential is exported
with RSA-OAEP to that private host directory. Host and ARM64 failure-path tests
cover durability failure, secure rejection, cancellation, malformed handles,
successful commit and refusal of a repeated attempt.

The old cached OCI/build images disappeared during diagnosis. The enrollment
fixture uses the retained local export of the actual daily candidate
`39fd4d186f6235332d3ae1c6101b676091243d57d9d7d609a91f8962448f54b1`,
including its own complete SELinux policy. Kernel image, DTB and loadable
modules match the preceding lab fixture; packaged `aboot.img` and
`initramfs.img` differ because the daily candidate includes the newer Plymouth
baseline. No image was published or installed by this lab experiment.

The [same-UID enrollment result](native-enroll-result-20260912.json) passed on
that exact candidate image. The packaged backend returned a valid 58-byte
handle and committed the new lab UID 1000 credential. Its independent secret
and completed record are retained only in the private lab directory; the
original lab UID 1234 credential was unchanged. The first fixture failed a
missing export-helper preflight before any secure service started; the corrected
fixture reused that untouched intent, rather than creating a second identity.

The [six-minute idle verification](native-idle-auth-result-20260912.json) also
passed after both the eMMC card and controller reported runtime-suspended.
Transport and secure status were both zero, credential bytes were unchanged,
and the packaged services stopped successfully. UART subsequently showed an
orderly systemd shutdown and return to fastboot before the host's attempted
SysRq; the shutdown initiator was not captured. USB hosting was stopped only
after exact serial 99NAY1AZG1 was observed in fastboot. These results do not
reproduce or explain the daily phone's unexplained interruption.

The [new ModemManager-base candidate](mm-native-auth-result-20260912.json)
also passed an enforcing USB-root boot and retained UID 1000 native verification
with the new image's own fingerprint policy. All packaged services started and
stopped successfully; the credential remained unchanged. No enrollment or
human fingerprint matching was performed. The requested UART reboot returned
exact serial 99NAY1AZG1 to fastboot before USB hosting ended.

The [existing-record recovery](native-recovery-result-20260912.json) passed on
12 September using the exact frozen daily recovery binary, on the new candidate
image. Its test-specific controller/unit required serial 99NAY1AZG1, the unique
run token, and USB root. The original lab UID 1000 secret was retained; its secure
user ID and handle were replaced successfully. The old completed record remains
as historical evidence and is explicitly marked superseded in its private vault.
The original physical-fingerprint UID 1234 file was unchanged. The new record was
exported encrypted and retained privately. All services stopped cleanly; UART
SysRq reboot returned the exact test serial to fastboot before the USB host stopped.

A further dual-record verification/read-only eMMC workload was prepared but
**not run**. Sam redirected the investigation to direct UART observation on daily
sam-sargo, noting that he may have initiated the earlier reboot. The previous
bootreason flag alone did not establish a recovery-caused watchdog failure.
