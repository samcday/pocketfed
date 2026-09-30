# Fingerprint candidate retaining the 12 September modem rollout

The user authorized staging a new candidate after the successful ModemManager
rollout. Preserve the exact baseline, package requests, PIN/homed configuration,
and all existing pinned deployments. This preparation does not authorize another
native credential recovery on daily sam-sargo.

Generated inputs and logs: `out/fingerprint-daily-mm-20260912`.
Baseline deployment: `06d451841d0119060d454da1744bdb47ce1bec3815530775aec3be4f235560b2`.
Original registry manifest: `f99cc04bed61613a1704a71024421c8188a65b25ee084d2f47b650217621802d`.
The registry was inaccessible, so `ostree container image reexport` exported
its exact cached layered image to a private temporary OCI on the phone.
Re-exported local image: `sha256:b5c4bd5293af3caf701193d9f40f8527dedb7e0d57d2fa21f1161c162837959c`.
All source image labels are retained. The imported package inventory matches
live sam-sargo except for its existing layered Tailscale package.

The kernel stage reuses the hash-verified .11 RPMs and the existing kernel image
recipe. The rebuilt build-only device-tree tools are recorded in the local
`dt-tools` context; they are never installed on the phone.

GNOME Settings is rebuilt from Fedora's exact 51~rc.1-1.fc46 source RPM, with
only the existing optional-GDM-schema row fix and a fingerprint trial release.
`gnome-source-provenance.json` records the source RPM, tarball/spec context and
patch identity. ARM64 builds use the isolated `gcc-toolchain` and `gcc-rpmbuild`
directories. No source or artifact was submitted to a public build service.

The image's own policy (`10fcd6ab76e143768f677af371805f22c64419af119e9382427a5b1a08f5b197`)
is composed offline with the reviewed FPC module and supplementary broker
module. Both stages compare complete existing CIL forms and query positive and
negative access boundaries. Context text is preserved and the binary regex
cache is regenerated on ARM64. No host policy is loaded. This is an additive
binary-policy composition, not a reconstruction of Fedora's source module store.

The image installer is restricted to fourteen hash-bound fingerprint packages.
It keeps existing authentication and boot files, preserves all other package
versions, and leaves the receiver and fingerprint clients masked. The final
comparison independently checks the resulting RPM inventory, boot payloads,
service changes, PIN configuration and exact policy inputs before staging.

The full candidate built as
`sha256:094ad9568428bb5351e0ab9d3c03c59ec71db60ed0d79b68ac7f53325d27f861`,
with OCI manifest
`sha256:82a2f20a07d45ee3db0f651ee86ef223cae62337cdd7ad7ad14db2226df61e1e`.
The independent comparison passed, including all unrelated package versions and
existing PIN files. Eight deliberately altered comparisons were rejected
(modem downgrade, PIN change, unmasked fprintd, wrong policy, missing rootwait,
duplicate root argument, extra service and removed signing-key records).

GNOME Settings and the Phosh, broker and PAM worker binaries passed dynamic
symbol resolution in the final image. GNOME reports 51.rc.1. The Fedora source
spec has no `%check`; the attempted post-build Meson test run could not execute
because RPM cleanup had removed its build metadata. No GNOME test-suite pass is
claimed. Image lint passed ten checks and skipped one, with four recorded
warnings about composefs and runtime/log/tmpfiles content.

The exact candidate then passed enforcing boot and native UID 1000 verification
on test-sargo. This verifies the new image's policy and packaged backend chain;
it does not accept daily GNOME enrollment or a physical Phosh unlock.

The first staging operation stopped before import because the image reader
could not traverse the private parent directory. Its attempt and log remain.
The guarded access retry keeps top-level evidence files mode 0600 and changes
only the parent directory from 0700 to 0711; the OCI is already readable.
It checks the original access failure and all original baseline/image guards,
and preserves a separate exclusive retry receipt. Import then completed with
finalization locked. The actual staged checksum is
`d639fe55e1cf11b2756f367fef1dad99ab7e2705c19b0b72f73e80c265d16b89`.
All 944 RPM records match the candidate plus the retained Tailscale layer.
The existing package requests and nine previously pinned deployments remain,
and the running MM deployment is now pinned too (ten pins total).

The staged verifier passed with no file mismatches. It reads the runtime
GVariant using the installed GLib C library because this base lacks Python GI;
its result was independently compared with the host GLib bindings on the same
serialized record. The current old policy sees the new broker executable as
unlabeled, so the verifier checks the exact raw stored SELinux context and that
the checkout shares the verified object inode. The candidate's live lab boot
separately exercised the new mapped policy under enforcing SELinux.

The 52,731,904-byte regular-file boot preview passed kernel, DTB and deployment
argument checks. No boot partition was written. The daily boot ID and running
MM checksum are unchanged, finalization remains locked, and the temporary
keep-awake unit has been stopped. Existing native-recovery history remains;
there is still no completed daily credential. Daily enrollment and Phosh unlock
are not yet accepted. See `final-state.json` and `boot-preview-validation.json`.

## UART-observed daily activation and recovery

Sam subsequently requested another live test with daily sam-sargo on the UART
harness and confirmed it connected. The exact staged candidate was activated,
retaining the new modem packages, Tailscale, pins, and PIN configuration. The
new boot reached kernel .11 and checksum `d639fe55e1cf11b2756f367fef1dad99ab7e2705c19b0b72f73e80c265d16b89`
with SELinux enforcing. After Sam's PIN login, an exact serial/boot-ID marker
confirmed the UART connection.

`../recover-uart-once.c` preserves all prior attempt receipts and intent backups,
checks that the prior backup equals the original intent, and reserves a separate
exclusive UART-attempt receipt before reusing the same trial UID/secret. Host and
ARM64 synthetic checks passed, including missing/mismatched prior backups,
durability failures and replay refusal. This requested live recovery returned
transport 0, secure status 0, a validated 58-byte handle, and commit/result 0.
UART captured every stage. The resulting daily credential is a valid root-owned
mode-0600 160-byte record; the original secret and earlier history are retained.
No credential contents were copied off the daily phone.

The broker and Phosh sockets are now enabled persistently, fprintd is unmasked,
and the Pixel 3a sensor appears on its D-Bus API. The existing Phosh PIN PAM hash
is unchanged. Sam enrolled his right index finger in GNOME Settings and confirmed
green feedback for that finger and red feedback for other fingers. He then
confirmed a Phosh lockscreen unlock by fingerprint without entering a PIN.
The device signals show enrollment completion and matching/nonmatching results;
the Phosh PAM account step acquired the already active homed home. The worker's
supervisor reported exit 1 after the successful unlock; its client-disconnect
handling can explain that status, but it is not recorded as a clean unit exit.
See [the first acceptance record](../desktop-first-acceptance-20260912.json).
Private UART capture and generated bundle: `out/private/sargo-daily-uart-20260912`.

## Second-finger enrollment follow-up

Sam's next enrollment returned to the Users page with an already-claimed error.
The Settings journal gives the precise failure:
`AlreadyInUse: Verification already in progress`. Settings 51.rc.1 sent
`EnrollStart` before its asynchronous `VerifyStop` completed. The fix in
`packages/fingerprint-desktop/0003-users-wait-for-verification-before-enrollment.patch`
waits for the stop reply and handles cancellation and device loss while waiting.
Tests compiled from the actual patched functions passed on host and ARM64;
restoring the original ordering fails the ordering assertion.

Settings and its filesystem subpackage have built as
`51~rc.1-1.2.fingerprint.fc46`. `update-settings.py` stages exactly those two local
RPMs with finalization locked, checks the complete package delta, retained pins
and requests, and unchanged PIN/Phosh/broker/receiver/policy files, then applies
them live without reboot. That guarded update passed, producing target
`efa97ca47fa5962a46f9bfa5c8d50dada208cf299ef113c3e18b709f4a5bfe7a`;
all checks passed, boot ID stayed the same, and Settings was relaunched. See
[the live application result](settings-live-update-result-20260912.json).
Physical second-finger acceptance and persistence after a further daily-phone
reboot remain pending.

The next user report was a freeze/reboot coinciding with USB unplug. Read-only
inspection found boot ID `f4004f50-da2f-4d01-90ac-7fea406885dc`, the prior `d639…`
deployment and Settings 1.1, no staged update, and empty `/sys/fs/pstore`. The
successful live update had not persisted through the unexpected reboot.
Both fingerprint sockets remained active; their dependent services had not yet
been requested. The original live-update receipts remain. A separate directory
received the same cached RPMs/manifest, but SSH timed out during updater copying
and before the restaging command ran; no new package transaction began.

Sam then reported successful second-finger enrollment after PIN login, followed
by another apparent freeze while USB remained connected. That occurred on the
original Settings version; unplugging alone cannot explain both reports. SSH
was unresponsive. The initial empty UART inventory was from the sandbox and
did not establish host adapter absence. After Sam confirmed the daily harness,
an escalated host reader captured the kernel stall. Enrollment retries and
restaging are paused while its initiating fault is investigated. See
[the freeze evidence](../freeze-observation-20260912.json). CPU 2 was waiting in
BPF cleanup/cross-CPU synchronization; CPU 0 also waited for other CPUs, while
CPU 1 did not answer the diagnostic backtrace request and was recorded as idle.
Later RPMh requests timed out. These observations do not identify the initiating
fault or establish a cause for earlier resets.
