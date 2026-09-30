# First live fingerprint trial — 11 September 2026

Sam confirmed: “Ready—phone online, USB recovery available.” This authorizes the
prepared deployment and controlled hardware trial. Touch prompts remain part of
the live test. The approved public issue payload is unchanged.

The pre-stage refresh at 03:33 UTC matched the saved `.8` baseline: exact package
set, 52 configuration paths, slot b, deployment requests and old recovery pins.
Battery was 91%. No competing deployment or transaction existed. The working
`ae313ebc772138e011a4a0a42b0f2d4247769433f4a1208b1824a062a78f7cfa.0`
deployment is now pinned; all earlier pins remain intact. The four transient eSIM
packages and their hashes remain available among the retained runtime artifacts.

The validated v3 image was exported to an OCI directory and transferred directly
over SSH. No registry publication was needed. The phone verified all 127 layer
hashes and the exact configuration identity:

- Image ID: `671197f9f3bf539fc4e1fd138843a8739df3958cabcacd0e5f9ca6a3baaa9996`
- OCI manifest: `sha256:198898e05ab2ba35ef38cf11bbc49bacba46a78195516c468a6cbdf3f144a5e6`
- Device source: `/var/tmp/sargo-fingerprint-v3-20260911/oci:candidate`

The first import failed before staging because the parent transfer directory was
0700 and the image proxy runs without root privileges. The OCI directory is now
root-owned and not writable by other users, with traversal on its parent. No
SELinux policy or enforcement change was needed. The second import reused 114
layers and imported the 13 new layers successfully; deployment preparation is
still running as this note is written. Finalization remains locked by the staging
command. No reboot or trusted-app operation has occurred yet.

Full local records and logs: `/tmp/sargo-fingerprint-live-v3/`. Staged image
checks use the existing independent boot parser and exact v3 file/package facts.
The inactive slot is a; recovery slot b and its root mapping must remain intact.

The imported base commit is `c2e4908…`. The second attempt then stopped before
staging because rpm-ostree rejects a local-package request when the exact NEVRA
already exists in the new base. The third staging command removes only the
redundant `feedbackd-device-themes` layering request. The image retains exactly
`feedbackd-device-themes-0.8.9-1.fc46.noarch`; the pinned recovery deployment keeps
its original local-package request. This is a deliberate metadata exception to
the original preserve-all-requests procedure, not a package removal. All other
requests and overrides remain required to match.

## Staged deployment and activation

Locked staging completed as
`75fbe0ef477f5314d393752c87ac0caf1d89536160fc22f93bc93711732ffb5c.0`.
All 943 package identities, policy bytes, service files/masks, retained requests,
and recovery pins matched their expected values. The only initial file-comparison
exception was an unchanged LPAC certificate symlink: the older parser recorded
its dereferenced bytes. Both link target and bytes match the running baseline.

The phone regenerated its initramfs. Its 132 kernel module paths exactly match
the actual working `.8` initramfs, itself checked against the current BLS initrd.
The container-built baseline had 107 paths and included five unrelated build-host
drivers; it was not the appropriate exact-list comparison for device regeneration.
The real working/trial lists have no missing or added module paths.

A regular-file finalization preview passed independent Android-v2 and ABLX
payload checks, with unchanged outer shim and the exact new kernel/DTB. Its size
is 48,144,384 bytes, below the 64 MiB boot partition limit. Preview SHA-256:
`ac1187c37250d1545c1e49118cc6701009c1dbf4735e67a5dbd913f886449f96`.
Regenerated initramfs SHA-256:
`c7ea18ef283704b946f1b334a31eba7ef03306d3ab9dc3546438cf2b5d20ba9e`.

After rechecking exact stage, lock, current slot and recovery pin, activation
was requested using `rpm-ostree finalize-deployment` with the full staged checksum.
This command unlocks finalization and initiates reboot. Actual boot and hardware
results are pending; no fingerprint service was unmasked before this request.

The first activation request was rejected without unlocking: despite its help
text saying CHECKSUM, this rpm-ostree version expects the **OCI manifest digest**
for a container-derived deployment. Source inspection confirmed validation occurs
before unlock/reboot. The corrected request retains an independent exact staged
commit check and supplies
`sha256:198898e05ab2ba35ef38cf11bbc49bacba46a78195516c468a6cbdf3f144a5e6`
to `finalize-deployment`. The procedure must use this container digest form.

## Boot and first hardware results

SSH returned at 04:25:36 UTC on kernel
`7.1.2-0.pocketfed.sdm670.11.fc46.aarch64`, deployment `75fbe0ef…`, slot a.
Sam confirmed Phrog appeared and ordinary login opened Phosh. Slot b retains
the pinned working `ae313ebc…` root. SELinux remains Enforcing, with the exact
reviewed policy hash `2a6013d4c22133f1ea730df92bcf4c739b5ac49e43682007cce59ac39f99913a`.
Phosh PAM retains its baseline bytes. Two boot warnings concern DSI clock
disable/unprepare; the display works. No QSEE failure occurred in these probes.

The slot switch left the stock `vendor_b` mapper absent. Read-only slot-1 LP
metadata on `system_b` confirmed the saved extent. A read-only mapping was
recreated as `0 991624 linear /dev/disk/by-partlabel/system_b 1759464`.
The firmware extractor then verified all 16 stock files against the manifest and
completed successfully. This mapping needs persistent integration for a future
boot; no physical partition was changed by its creation.

The listener service was unmasked with runtime first-attempt overrides disabling
service retries. A temporary wrapper also stops on the daemon's first startup
transport failure. FS listener 10 and GPFS listener 28672 registered successfully,
then READY was received. Common-library and FPC app loader sessions both succeeded
and remain anchored. No listener retry was needed.

With the exclusive device lock held, the installed probe initialized the sensor
successfully and returned it to deep sleep. A second probe armed a touch window.
Sam touched and lifted the rear sensor: `qualify_capture` returned transport 0,
dispatcher 0, command 0 and capture detail 0. IRQ sequence advanced from 120 to
144. The probe returned to deep sleep and exited successfully. This proves a
real accepted capture; enrollment and identity matching remain untested.

A public TEE attach to exactly `keymaster64` succeeded (status 0) and was closed.
This lookup sent no application command and requested no firmware load. The
Linux QSEE storage directory remains empty, and no native auth credential exists.
The next step is the recovered Keymaster negotiation, followed by first database
initialization before any native Gatekeeper provisioning can populate storage.
fprintd, the auth broker socket, provisioning template and Phosh fingerprint
socket remain masked at this checkpoint.

## Keymaster handshake and missing HMAC setup

The exact stock GET_VERSION and SET_VERSION exchanges both succeeded. GET
reported `[4,0,4,165]`. This is an acknowledgment, not readback of earlier
once-per-loaded-TA settings. The Linux QSEE directory remained empty.

fprintd was unmasked with a runtime `Restart=no` override. Its state directory
was restored to `fprintd_var_lib_t`; an exclusive empty mode0600
`initialize-empty` marker was created for the confirmed-empty namespace.
GetDevices returned `/net/reactivated/Fprint/Device/0`. Claim then failed while
parsing the wrapped authentication-key response, before database initialization.
No relevant AVC occurred; the marker and empty QSEE namespace remain intact.
fprintd was stopped before the status diagnostic.

The status-only diagnostic confirmed transport 0, Keymaster status -24. Private
inspection traces this to `km_get_auth_token_key` (`0xb548`) calling the shared
HMAC key accessor (`0x2960`), whose uninitialized flag branches at `0x2a18` to
the -24 return. This is missing per-boot HMAC agreement, not a device permission
failure. Neither credential nor fingerprint database has been created.

The same signed image's dispatch table maps `0x20e` to `0x1c00c` and `0x20f`
to `0x1c14c`. The first accepts a four-byte command and returns status followed
by a cached 64-byte seed/nonce pair. The second takes a 12-byte header with a
request-relative offset and participant count, followed by 64-byte entries.
It checks its own pair is present, derives a key inside the TA, installs the
per-boot shared HMAC value, and returns status plus a 32-byte sharing check.
The single-participant request is 76 bytes; response capacity is 40884 bytes.
No persistent credential or factory agreement key is replaced by these handlers.

Android documents HMAC agreement as part of Keymaster startup, and upstream
tests explicitly exercise one through four participants:
[interface contract](https://android.googlesource.com/platform/hardware/interfaces/%2B/6adbab13e/keymaster/4.0/IKeymasterDevice.hal),
[single-participant test](https://android.googlesource.com/platform/system/keymaster/%2B/afba455c8c76c0544ba2725c51ce5cf387587999/tests/android_keymaster_test.cpp).
The Linux trial uses the resident Qualcomm TA as its sole participant; it does
not claim StrongBox interoperability. The diagnostic requires the exact TA
version and a genuine -24 secure status first, sends back only that TA's returned
parameters, logs only status/length metadata, and wipes all response buffers.
Synthetic checks cover exact framing and stops on transport errors, unexpected
secure statuses and untouched replies. Hardware execution of this new exchange
is the next step.

The HMAC setup completed successfully on hardware: GET parameters status 0,
COMPUTE status 0, 32-byte sharing check, then a valid 152-byte wrapped key.
After this correction, fprintd Claim and Release succeeded. Its first open
consumed the marker and saved the dedicated database at
`/var/lib/qsee-supplicant/pocketfed/fpc-sargo-v1.db` (77 bytes, root0600).
No prints are enrolled. No relevant AVC or listener failure occurred.

At 04:53:42 UTC the first `pocketfed-fpc-provision@1000.service` attempt failed
with the broker's generic Permission denied error. It left the intended durable
`uid-1000.intent` (160 bytes, root0600) and no completed credential. The intent
is preserved untouched; provisioning has not been retried. The current binary
maps negative secure statuses to EACCES, so the exact original TA error was not
retained. That diagnostic limitation must be fixed before another credential
attempt. The state directory has its dedicated SELinux type and no AVC occurred.
The broker socket and Phosh fingerprint socket remain masked.

A subsequent fprintd Claim/Release still succeeds, establishing that its saved
database and wrapped-key path survive the Gatekeeper failure. The next diagnosis
uses a four-byte Gatekeeper command with no UID or credential payload. The
inspected handler rejects this length before deserializing a UID or accessing
any credential record; expected status is -29. This distinguishes a failure in
the common application setup from one inside the credential operation, without
resubmitting or replacing the preserved intent.

The header check returned transport 0 and the expected -29. The common dispatch
path therefore remains functional. The original broker did not retain its
failure phase either; its generic error alone cannot conclusively distinguish
the secure operation from a subsequent store failure. Source diagnostics now
preserve the provisioning phase and separate transport/secure status without
logging credentials or response bytes. These changes are not installed yet.

A bounded recovery tool is prepared under the private local trial directory.
It validates and reuses the original intent through the production store code,
refuses a completed credential, and creates/syncs an exclusive recovery receipt
before any secure call. It can replace only this trial's unpublished native UID
`0x700003e8`; this is a deliberate recovery operation, not a safe existence
query. Successful recovery uses the normal durable commit; failed recovery
preserves the intent and receipt and cannot repeat through this tool. Synthetic
tests passed for preserved-secret commit, failure preservation, duplicate
receipt refusal, and malformed/completed state refusal.

Automatic approval review rejected execution because this recovery can replace
a durable secure credential and change service state without explicit approval
for that exact recovery. No recovery execution or service override happened.
Sam has been asked to approve the concrete `recover-unpublished.c` and
`recover-first.py` operation. The executable has only been copied to the private
runtime directory. No further touch or USB action is currently required.

## Approved recovery result and RPMB dependency

Sam approved that exact one-time recovery. At 05:06:40 UTC it ran once and
returned backend setup 0, enrollment transport 0, secure status **-30**, and
validated handle length 0. No completed credential exists. The original
160-byte intent and exclusive 132-byte first-recovery receipt remain root0600.
The recovery authorization has been used; the guarded tool refuses repetition.
fprintd is runtime-masked, and both authentication sockets remain masked.
FS/GPFS, cmnlib64 and fingerprint loaders remain active with zero restarts.

Private static analysis places the fresh-enrollment -30 path at failure to
obtain a Gatekeeper RPMB record (`0xf988`). Its initialization (`0x100b4`)
allocates a 12 KiB buffer and, when RPMB is enabled, reads 24 sectors then
writes a header sector through the trusted storage API. Initialization failure
or a full 184-record table can both return null; the observed status does not
distinguish them. No RPMB record contents have been inspected. Missing RPMB
service is a dependency hypothesis, not proof of the exact failing subcall.

The installed supplicant registers only FS 10 and GPFS 0x7000. Stock qseecomd
names a separate RPMB library/service. The open Qualcomm/LK protocol provides
listener 0x2000, a 25 KiB shared buffer, version-2 initialization, and read/write
requests. The local reference is lk2nd commit
`4a88d4cc9d6da226a90e55f2a0e66f7179a0b79b`, files
`platform/msm_shared/rpmb/rpmb_listener.c`, `rpmb.c`, and `rpmb_emmc.c`.
That bootloader implementation is protocol evidence, not a hardened userspace
implementation to copy unchanged.

Live metadata shows `/dev/mmcblk0rpmb` (character 504:0, root0600,
`removable_device_t`) and kernel RPMB registration. The eMMC reports
`raw_rpmb_size_mult=0x80` (16 MiB), `enhanced_rpmb_supported=1`, and
`rel_sectors=1`. Qualcomm's protocol expresses capacity in 512-byte units;
its enhanced-RPMB write grouping uses a separate capability rule. These units
must not be conflated with 256-byte RPMB data payloads or generic reliable
sector count. The kernel exposes no userspace RPMB class attributes here;
the parent MMC sysfs attributes provide the capability metadata.

Broker phase/status diagnostics pass the complete local `make check` suite,
including peer-credential checks outside the sandbox. They remain source-only.
A fixed counter/status diagnostic is being prepared to verify the existing
Linux MMC ioctl transport without reading data records, programming a key, or
writing authenticated data. It must never be represented as MAC verification.

The fixed counter/status diagnostic subsequently passed on hardware:
`counter_transport_errno=0`, response type 512 (0x0200), device status 0,
matching nonce, exit 0. The ARM64 executable SHA256 was
`1a53b859dec5e4deb9d41e685279d7608e869a7912a8fe351ce08ea614712ef7`.
Its fixed packet requested only the counter; no RPMB record payload or
authenticated data write was sent. The result proves command transport, not
MAC authentication or secure partition readability.

Private stock RPMB library analysis confirms the protocol layout and the
enhanced capability rule. An experimental codec and upstream MMC transaction
adapter now pass host and ARM64 synthetic tests; neither is enabled on the
phone. The exact evidence, supported subset and next hardware gate are recorded
in [rpmb-investigation.md](rpmb-investigation.md). No second credential recovery
has been performed. This work has not been published to the public issue.

The combined FS/GPFS/read-only-RPMB receiver has now been built and its
integration tests pass on host and ARM64. Its fixed activation script and
binary are copied to `/run/sargo-fingerprint-trial`. Automatic approval review
rejected running that script because it stops/replaces live shared secure
services without explicit approval for that exact change. No activation ran;
the original service state remains. The concrete operation has been submitted
to Sam for approval. This is separate from, and does not repeat, the consumed
native credential recovery approval.

While the read-only service activation awaits approval, the separate per-boot
Keymaster gap is being addressed in source. Broker release `0.3` adds a static,
idempotent startup helper: a valid wrapped key ends the check, and only genuine
TA status -24 enables the measured single-participant HMAC setup. The helper
precedes broker/provisioning, and libfprint release `1.4` requires it before
sensor open. No new package or helper has been installed on the phone. The
frozen read-only RPMB trial binary and activation script are unchanged.

The full host broker/startup suite and local ARM64 RPM build both passed,
including all credential lifecycle, peer-credential, transport clearing and
new HMAC startup tests. Local candidate
`pocketfed-fpc-auth-0.1.0-0.3.pocketfed.fc46.aarch64.rpm` has SHA256
`7b3f605e40e638df8e2e246ddd8f3c1d82cba095d0d3ba4ffbf7747a16acb853`.
Its package payload includes the startup binary/static service and the flock
dependency; source hashes and acceptance limits are in
`packages/fpc-auth/startup-build.json`. This is an unsigned local candidate,
not a public build or live installation. The new libfprint dependency is
source-only. A fresh read-only device check confirms the original QSEE daemon
and wrapper override remain active and no read-only activation receipt exists.
The approval request remains pending.

## Firmware cache preparation while service approval is pending

The transient vendor_b mapping is no longer needed for subsequent firmware
staging in the updated source. The new `--ensure` path validates the persistent
private bundle's ownership, modes, exact lengths, hashes, and split ELF layout.
An absent bundle falls back to verified vendor_b extraction; an unsafe or
damaged existing bundle fails without overwriting it. The updated static unit
uses this mode and permits the vendor path to be absent. No automatic mapping
creation was added, and first extraction still requires the pinned source.

All nine synthetic extractor tests passed. Local `systemd-analyze verify` passed
outside the sandbox, whose socket restrictions prevent the verifier from
running normally. A read-only on-phone import of the validator verified all 16
cached files (1,166,860 bytes) with source inspection deliberately disabled.
Neither the installer nor symlink repair was called. The checked script had
SHA256 `b365059822573ce46e5cbfbf551fe8297435f90c0d199022451f890da1c556cb`;
the sole subsequent source change clarified a comment about mapper write
permissions. The installed manifest matched SHA256
`fae1f24705b8939fa4fcb7d988ae25c7e61abe14add687deaa9b905050876d80`.
The cache-aware unit is not installed or accepted through reboot yet.

That same device check found qsee-supplicant active/running with MainPID 7247,
zero restarts, and no read-only RPMB activation receipt. The frozen RPMB trial's
seven source hashes and executable hash remain unchanged. Live progress still
requires the pending explicit approval to replace the shared secure-service
receiver; no additional touch or USB action is needed at this point. The
earlier one-time native recovery approval has already been consumed.

## Dedicated test-sargo liveboot investigation

Sam pointed this task at `kernel iteration embetterment` and made the attached
test-sargo available for experiments. Its serial is `99NAY1AZG1`; the dedicated
FTDI UART resolves to `/dev/ttyUSB0`. The existing USB-root tooling already
accepted the local `.11` fingerprint image, and kernel bundles can be prepared
independently of the root fixture. Investigation can now proceed on this lab
device while the daily-driver service replacement remains unexecuted.

Two lab boots reused the `.11` kernel and a metadata-only userspace overlay.
The first passed the automatic handoff gate in 64.40 seconds but first-boot
presets removed the inspection enablement link. The second requested inspection
explicitly through the command line and the reader completed successfully.
Kernel audit output split the second run's UART JSON; the complete reports were
recovered with the original log and parsing provenance retained, while the
runner's own `handoff-timeout` result remains unchanged. Source, detailed
evidence and limits are in [lab/README.md](lab/README.md).

Test-sargo has the older SP2A.220505.002 vendor build, rather than sam-sargo's
pinned SP2A.220505.008. The production inspector refused it before reading
firmware payloads. Its FPC, TEE and RPMB nodes exist, but dynamic device numbers
differ; the eMMC capability metadata matches. Next inspect this lab build's
exact program firmware and adapt the read-only receiver to the actual device
identity. Neither lab run invoked a secure operation. Both guests were rebooted
to fastboot before their USB hosts were stopped; UART ownership was released.

The subsequent lab read-only receiver trial passed. Its explicit inspection of
SP2A.220505.002 found all 16 FPC/common-library files identical in length and
SHA256 to sam-sargo's pinned firmware. A separate lab manifest retains that
source identity. The lab-only device validator matched the RPMB node to its
kernel sysfs device, card parent and character-device link; host and ARM64 tests
passed. The receiver registered FS, GPFS and RPMB, reached readiness and stopped
cleanly with zero restarts. No RPMB callback or credential operation occurred;
this establishes receiver lifetime, not Gatekeeper storage functionality.
The run, firmware comparison and checksum-verified reports are recorded in
`lab/readonly-build.json`. The original sam-sargo activation script is unchanged
and remains unexecuted. Test-sargo was returned to fastboot and its host stopped.

The subsequent startup experiments found and fixed an ordering dependency.
Both the packaged Keymaster helper and the earlier GET-only diagnostic returned
wrapped-key status `0xff000fff` when FPC was not loaded. The test phone's
Keymaster program hashes exactly match sam-sargo, as do the 16 FPC/common-library
files. Loading FPC before the same packaged helper produced the expected
152-byte wrapped key. A second startup check reported already-ready and skipped
HMAC recomputation. Sensor initialization/deep sleep returned all-zero status,
and every service stopped cleanly. No RPMB callback or credential operation was
observed. The ordered run passed enforcing handoff in 64.70 seconds and was
returned to fastboot before USB hosting stopped.

The `0.4` auth source now orders startup after the FPC loader and withdraws its
readiness when that loader stops. Lab evidence and the comparative runs are in
[lab/README.md](lab/README.md). This is startup acceptance on test-sargo, not
Gatekeeper enrollment, fprint matching or either lockscreen's acceptance.
Secure-storage callbacks and durable retention of the lab credential intent
are the next investigation steps; no finger touch is currently needed.

A guarded lab Gatekeeper trial is now prepared with durable private host
recovery material and RSA-OAEP export of any returned credential. Lifecycle,
replay-refusal and real ARM64 export interoperability tests passed. Its RPMB
receiver remains read-only. Automatic approval review rejected the launch
because general lab access did not explicitly authorize the credential mutation.
No device process started, no launch receipt was created and test-sargo remains
in fastboot. The exact scope and guards are in
[lab/gatekeeper-trial.md](lab/gatekeeper-trial.md). Explicit approval for this
lab operation is the next user action; it does not authorize a daily-phone
recovery or enable fingerprint enrollment by itself.
