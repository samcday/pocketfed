# Fingerprint implementation on Sargo

Tracking: [sam-sargo #11](https://github.com/samcday/sam-sargo/issues/11).

The original goal was working native **fprint**, successful enrollment by Sam in
**GNOME Control Center**, and fingerprint authentication through **Phosh and
Phrog**. PIN fallback must remain available. Neither protocol unit tests nor
sensor interrupts establish that this goal is complete.

## Status — 1 October 2026

**Accepted on sam-sargo on 2026-09-13** with kernel `.12`: Settings
enrolment and normal Phosh lockscreen unlock, with PIN once after reboot and
then fingerprints. Phrog fingerprint login and fingerprint-only encrypted-home
unlock were dropped from scope. **Nothing is integrated into `main`.** This
tree is a source publication of the local snapshot `0f08890d`
(`wip/shared-checkout-20260917`, 2026-09-17); integration and the Fedora HWE
move are tracked in [pocketfed#115](https://github.com/samcday/pocketfed/issues/115).
The 11 September notes below are kept as history and still say "pending" in
places.

| Component | Directory | Accepted version |
|---|---|---|
| Kernel | [kernel-fingerprint](../../packages/kernel-fingerprint/) | `7.1.2-0.pocketfed.sdm670.12` (COPR 10980882) |
| FPC/Gatekeeper codecs, transport, probe | [fpc-qsee](../../packages/fpc-qsee/) | `fpc-qsee-probe 0.1.0-0.1.pocketfed` |
| Enrolment broker, Keymaster startup | [fpc-auth](../../packages/fpc-auth/) | `pocketfed-fpc-auth 0.1.0-0.4.pocketfed` |
| Supplicant + RPMB listener | [qsee-supplicant](../../packages/qsee-supplicant/) | `0.1.1-1.4.pocketfed` (+`-sargo-rpmb`) |
| libfprint `fpcqsee` driver | [libfprint](../../packages/libfprint/) | `1.94.100-1.6.pocketfed` |
| SELinux policy | [fpc-selinux](../../packages/fpc-selinux/) | `pocketfed-fpc-selinux 0.1.0-0.2.pocketfed` |
| Settings, Phosh, PAM helper | [fingerprint-desktop](../../packages/fingerprint-desktop/) | g-c-c `51~rc.1-1.2.fingerprint`, phosh `0.57.0-1.5.fingerprint`, `phosh-fingerprint-auth 0.1.0-0.1.pocketfed` |
| Firmware prep, device config, trial records | [fingerprint-trial](fingerprint-trial/) | — |
| fprintd | stock Fedora | `1.94.5-6.fc45` |

Where the rest lives:

- Kernel: reproducible `.12` source on samcday/linux branch
  [`codex/sargo-fingerprint-invoke-pool-fix`](https://github.com/samcday/linux/tree/codex/sargo-fingerprint-invoke-pool-fix)
  (release commit `3ad4e5eac8aa`), RPMs on the
  [`sargo-fingerprint-kernel-12`](https://github.com/samcday/linux/releases/tag/sargo-fingerprint-kernel-12)
  release, upstream-shaped series in [linux#14](https://github.com/samcday/linux/pull/14).
- Invoke-pool validation: [pocketfed#62](https://github.com/samcday/pocketfed/pull/62).
- Device acceptance history: [sam-sargo#11](https://github.com/samcday/sam-sargo/issues/11);
  raw working-tree copy under `pocketfed-workdir/` in
  [sam-sargo-slush](https://github.com/samcday/sam-sargo-slush).
- Handoff note: `git fetch origin refs/notes/evidence:refs/notes/fingerprint-handoff && git notes --ref=fingerprint-handoff show 15d4fe2d8dca65cda11e2ae47f9a2fa2c894b4c7`.

**Gatekeeper finding.** Sargo's FPC TA refuses to complete enrolment without a
Gatekeeper-signed, challenge-bound hardware authentication token. The
`fpc-auth` broker obtains one through its own QSEECOM Gatekeeper session with a
native service credential, independent of the user's PIN. That session only
works when the AP-side secure-storage listeners are up: FS, GPFS and RPMB
(listener id `0x2000`), which
[`sargo-rpmb`](../../packages/qsee-supplicant/sargo-rpmb/) registers in one
lifetime, with RPMB operating on `mmcblk0rpmb`. Proprietary TA and firmware binaries are not in this tree;
they are extracted and hash-verified on the device.

## Historical implementation state — 11 September 2026

The last successful phone inventory on 11 September AEST recorded: kernel
`7.1.2-0.pocketfed.sdm670.8.fc46.aarch64`, Phosh 0.57.0, Phrog 0.53.0,
GNOME Control Center 51 beta. No native fingerprint packages are installed.
That snapshot had no pending deployment and three older recovery deployments
pinned. Connectivity recovered after a temporary SSH/tailnet outage. A refresh
at 2026-09-11 03:05 UTC confirmed the same deployment, pins, package inventory,
boot arguments and all 46 checked authentication/device-configuration paths.
There is no staged deployment or transaction. Recovery/touch availability remains
unconfirmed; refresh the inventory again if staging is delayed.
No runtime sensor/TEE commands or authentication changes have been applied by
this task. The [initial read-only inventory](diagnostics/2026-09-10-fingerprint/README.md)
remains useful background, with the symbol-table correction below.

- **Stock protocol recovered:** [protocol reference](../../packages/fpc-qsee/protocol.md)
  and C helpers describe the exact inspected FPC TA/HAL. Despite its absent ELF
  section table, the TA retains dynamic symbols through `PT_DYNAMIC`; these
  enabled direct recovery of the dispatchers. Its SHA-256 is unchanged from the
  initial inventory.
- **Native transport and probe:** [source](../../packages/fpc-qsee/) implements
  the recovered 64-byte request/response wrapper and unaligned 64-bit auxiliary
  pointer. It includes an explicit initialization/capture-readiness probe.
  No biometric templates or signing keys are returned or logged by the probe.
- **Protocol/transport tests:** native host tests pass, including malformed
  lengths, failed transport/dispatcher/command results, zero IDs, nonmatch
  decisions, shared-memory cleanup and session ID zero. They also pass with
  undefined-behavior trap instrumentation. These simulate the TEE boundary and
  do not establish live compatibility.
- **Supplicant packaging:** [qsee-supplicant](../../packages/qsee-supplicant/)
  pins upstream `36e06680cf7f690fccbdcd07abc2a64c4bb061d8`. Base ARM64 trial
  [10973528](https://copr.fedorainfracloud.org/coprs/build/10973528) succeeded.
  A Sargo-required explicit shared-library loader extension passed trial build
  [10973582](https://copr.fedorainfracloud.org/coprs/build/10973582). Its new
  request-layout/error tests and upstream listener/loader tests pass locally.
  The subsequent readiness-lifetime fix passed ARM64
  [COPR 10973847](https://copr.fedorainfracloud.org/coprs/build/10973847), release
  `1.3.pocketfed`. Registration failure cannot announce readiness, and listener
  loss after readiness exits the daemon so systemd revokes its active state.
  Its lifecycle and registration tests pass; downloaded signatures are verified.
- **Kernel:** isolated `/tmp/sargo-fingerprint-kernel` starts from the prepared
  camera `.9` release, preserving those fixes. It adapts the legacy QSEECOM
  backend for the Sargo ELF64 TA, adds shared-library loading, corrects audited
  resource-lifetime faults, and supplies the native reset/IRQ device. Source
  objects, complete module linking and Sargo DT checks pass. The `.10` kernel passed isolated
  [COPR 10973618](https://copr.fedorainfracloud.org/coprs/build/10973618); all seven
  runtime RPM signatures and payload digests are verified against the configured
  kernel COPR signing key.
  The `.11` follow-up passed
  [COPR 10973843](https://copr.fedorainfracloud.org/coprs/build/10973843), with all
  seven runtime RPM signatures verified. It wipes the complete kernel staging
  allocation before release, including error paths. The earlier image contains `.10`; the current masked image contains `.11`.
  Neither trial kernel has booted on the phone.
  The [boot procedure](../../packages/kernel-fingerprint/trial-procedure.md)
  requires a new embedded DTB and preserves the current overlays and recovery pins.
- **Desktop:** [preparation](../../packages/fingerprint-desktop/) includes
  separate fingerprint authentication for Phosh, scoped Phrog/PAM integration,
  and a GNOME Control Center fix for the optional missing GDM schema that
  otherwise hides enrollment. ARM64 COPR builds for Phosh
  [10973639](https://copr.fedorainfracloud.org/coprs/build/10973639), Control Center
  [10973640](https://copr.fedorainfracloud.org/coprs/build/10973640), and the scoped
  PAM helper [10973641](https://copr.fedorainfracloud.org/coprs/build/10973641)
  passed, and RPM signatures are verified. Independent image comparison then
  found that the Phosh RPM replaced the working Fedora PAM policy with an
  pam_unix-only policy supplied by our package. Corrected Phosh 1.5 preserves system-auth and fixes the isolated GUI test
  environment. ARM64 [COPR 10973752](https://copr.fedorainfracloud.org/coprs/build/10973752)
  passed with all 45 tests retained. The image also
  preserves the exact base PAM file. Live UI validation remains.
- **libfprint:** ARM64 [COPR 10973705](https://copr.fedorainfracloud.org/coprs/build/10973705)
  passed after correcting the test hardware boundary for link-time optimization.
  Production optimization stays enabled. Full selected tests pass in the
  actual Fedora package build; live sensor operations remain untested.
- **Trial image:** the locally cached image was proven identical to the running
  base by matching its OCI configuration and all 114 root filesystem layer
  digests. The first complete image was rejected for the Phosh PAM regression.
  The corrected `.10` image `83cc5287c9ae` passed its historical checks.
  The [current image](fingerprint-trial/image/README.md), ID `671197f9f3bf`, now
  includes kernel `.11`, listener 1.3, broker 0.2 and reviewed policy outputs.
  All 19 selected runtime versions, unrelated packages, working PAM, exact units,
  boot payloads, all 107 initramfs module paths and policy bytes pass comparison.
  Five masks cover fprintd, qsee-supplicant, the Phosh helper socket, broker
  socket and provisioning template. No credential state or database marker was
  created. Installed unit-graph checks and ARM64 context lookups pass in a
  disposable container. No image was published, staged or booted.

## Remaining dependencies

The FPC TA requires a valid Gatekeeper-signed, challenge-bound hardware
authentication token before it completes enrollment. It obtains its wrapped
authentication key from `keymaster64`; a challenge-only token is rejected.
The native credential store, restricted broker and production TEE backend are
implemented. Broker release `0.2.pocketfed` passed ARM64
[COPR 10973881](https://copr.fedorainfracloud.org/coprs/build/10973881), signature
verification, unit validation and dynamic-link checks. Host and ARM64 tests
exercise the real codec and userspace transport through synthetic TEE replies,
including durable provisioning intent, challenge/SID validation, cancellation,
throttling and failure cleanup. No real credential has been provisioned and no
genuine token issued. The broker is now included in the masked local image.
Sam approved private local analysis of the stock keymaster firmware and
Gatekeeper/libkeymasterutils files. Those files establish the older fixed-field
Gatekeeper format (commands `0x1001`/`0x1002`), independently confirmed against
the TA; host and ARM64 framing/rejection tests pass. The separately approved
`libkeymasterdeviceutils.so` copy resolved the exact GET/SET version handshake
and unpadded request/response partitioning. The native codec now matches it and passes host tests plus address/undefined
behavior checks; the submitted probe RPM predates this codec update. SET_VERSION configures the loaded TA only once; repeating
it successfully does not prove or repair a previous client's settings. Resident
application identity, listener behavior and genuine token issuance remain live
validation gaps. No credential stores or existing Android templates were read.

The TA replaces an existing Gatekeeper UID record during fresh enrollment.
Native provisioning must reserve IDs outside Android ranges and refuse silent
replacement of existing native credentials. Passing a Linux UID directly is
not an isolated namespace. No Gatekeeper provisioning has been attempted.

The [backend review](../../packages/fpc-auth/backend-integration.md) confirms
that the existing kernel reconstructs the exact stock request/response split.
Before activating credentials, it also requires explicit cleanup of the kernel
staging copy and a listener-health check that remains valid after a daemon
failure. A userspace socket deadline does not establish a bounded secure call.
A [focused kernel cleanup follow-up](../../packages/kernel-fingerprint/followup/0001-tee-qseecom-wipe-application-invoke-staging.patch)
now passes 25 production-function fixture cases on ARM64 with 4K and 64K pages,
including failure paths and rejection of missing/short clearing. That patch is
now built in `.11`. The broker's units require `.11` and qsee-supplicant `1.3`,
bind their lifetime to the listener service, and keep the session and state lock
until a synchronous secure call returns. The masked image includes these
corrected packages; its offline checks do not establish secure-call behavior.

The native fprint driver will receive enrollment authorization through a
restricted local token broker. The broker must obtain a legitimate HAT; it must
not manufacture a successful match or skip the TA's checks. Fingerprint
recognition must come from the TA's successful identify result and must match
the requested libfprint gallery.

SELinux is enforcing on the inspected phone. The candidate's compiled policy
does not let `fprintd_t` open the default `device_t` labels assigned to the new
FPC and non-privileged TEE nodes. The systemd device-access drop-in does not
override that restriction. A [narrowly scoped policy candidate](../../packages/fpc-selinux/README.md)
compiles and passes offline access/path-boundary checks and independent review.
The candidate also labels the broker socket and private credential directory
separately. Offline tests permit fprintd socket access while denying credential
file access, including conditional policy branches. Its validated compiled
outputs are now included in the masked image; it has not been loaded on the phone. A follow-up inventory found
an empty module store despite an existing compiled policy; reconstruction from
the exact signed Fedora package and active image additions now preserves the
complete baseline decompiled policy and context text. Normal offline module
insertion passes access tests and exact preservation checks outside the reviewed
fingerprint additions. Image inclusion is complete; enforcing runtime checks remain.
The inactive policy RPM passed
[COPR 10973947](https://copr.fedorainfracloud.org/coprs/build/10973947), signature
verification and byte-for-byte comparison with the validated module. It has no
scriptlets; installing the package alone does not activate policy. The current
image incorporates its verified policy outputs while retaining all service masks.
The [offline SELinux evidence](../../packages/fpc-auth/selinux-integration.md)
separates default-policy predictions from the process/inode labels and AVCs
still needed during a controlled live test.

An inactive encrypted homed home also needs a decryption credential. A boolean
fprintd match by itself cannot supply that secret. Active-session unlocking and
Phrog authentication need their own measured evidence; cold-home login must be
explicitly tested and its credential requirements recorded. The
[source review and live-test matrix](../../packages/fpc-auth/homed-integration.md)
separate current homed support from the still-unproven biometric-protected
credential provider needed for fingerprint-only cold-home login. This dependency
must not be hidden by marking the overall goal complete after an active-session
test alone.

## Completion evidence still required

1. COPR-built kernel boots with all current recovery and image customizations
   preserved; the QSEECOM backend and native FPC control device work.
2. This phone's TA loads; initialization, capture and cleanup behave correctly.
3. Native fprint supports enrollment, matching, wrong-finger rejection,
   cancellation, deletion, persistence and useful retry feedback.
4. Sam successfully enrolls through GNOME Control Center on the real phone.
5. Sam successfully authenticates through both Phosh and Phrog; wrong fingers
   fail, PIN fallback works, and cancellation does not admit stale results.
6. Suspend/resume, reboot, and active/inactive encrypted-home behavior are
   checked at the scope required by those login paths.

Code, builds, or synthetic tests alone do not satisfy these device/UI gates.
