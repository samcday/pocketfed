# Installed acceptance of the QSEECOM pool fix

Kernel `.12` follows the successful disposable allocator comparison and repeated
native tests documented in `../kernel-pool/README.md`. The precise platform
failure is still unresolved; installed desktop acceptance is a separate gate.

The candidate starts from cached image
`sha256:094ad9568428bb5351e0ab9d3c03c59ec71db60ed0d79b68ac7f53325d27f861`.
It changes the four currently installed kernel packages to `.12` and the two
Settings packages to `51~rc.1-1.2.fingerprint.fc46`. Extra optional kernel
subpackage sets are not added. Source and guarded image assembly live in
`packages/kernel-fingerprint/followup-pool/image/`; generated artifacts and
comparisons live in `out/fingerprint-pool-fix-20260913/`.

Installed `.12` acceptance has now passed its automatic phase. The approved
activation booted deployment `aa40b5a0…`, with the expected manifest, enforcing
SELinux, unchanged PIN PAM configuration and all eleven prior pinned deployments.
The production Settings package is `51~rc.1-1.2.fingerprint.fc46`.
The v2 acceptance controller completed 50 ordinary fprintd Claim/Release cycles
across ten complete service lifetimes in 58.35 seconds, including 50 explicit
service stops. UART independently recorded every completed cycle and stop,
with no observed RPMh timeout or CPU-stall signatures. The boot ID stayed the
same, and the temporary service timeout override was removed.

The v2 controller explicitly includes the normal per-boot Keymaster startup
service among the five units in each lifetime. It performed no capture,
enrollment, deletion or credential operation. The previous 50,000-allocation
disposable test and this installed D-Bus test are distinct acceptance scenarios.

Physical Settings checks passed: Sam enrolled a couple more fingers, reopened
the fingerprint dialog a dozen additional times, and sampled matching and
nonmatching feedback on random attempts. The fresh snapshot retained the same
`.12` boot and UART had no observed stall signatures. The ordinary Phosh
fingerprint socket and template are now unmasked and the socket is enabled;
the PIN PAM file remains unchanged. The subsequent user-authorized normal
reboot returned to the same .12 deployment and automatically active fingerprint
socket. All four enrolled-finger names were retained through the public fprintd
metadata API, with unchanged PIN hash, enforcing SELinux and all prior pins.
Sam subsequently confirmed roughly six cycles alternating Phosh lock/unlock,
multiple fingers and failure modes, PIN fallback and Settings tester green/red
feedback. The device remained responsive on the same boot with no UART stall
signatures. Settings and Phosh acceptance is complete.
Evidence is in `out/fingerprint-pool-fix-20260913/firstboot-inspection.json`,
`installed-claim-lifetimes/`, and `installed-lifetimes-uart-verification.json`.
The physical report is `settings-physical-acceptance.json`, with the fresh
device snapshot in `settings-accepted-snapshot.json` and Phosh activation output
in `phosh-scanning-activation.log` in the same generated evidence directory.
Reboot evidence is `persistence-postboot.json`, `enrollment-persistence.json`
and `reboot-acceptance-status.json`. The current fresh boot ID is
`c7527493-d48e-4b34-86fa-9855a85fa191`. The final physical result is recorded in `final-physical-acceptance.json`,
with `final-device-snapshot.json` and `final-uart-error-audit.json`.
The remaining sections retain the earlier staging history.

The exact source RPM is approved for COPR build 10980882. The full ARM64
binary build and local image build succeeded. Independent image comparison
passed with exactly six package changes; all 95 initramfs modules, the boot shim,
DTB, arguments, authentication, service and policy files were preserved. The
Settings binary matches the previously tested direct binary and passes dynamic
link checks. At that staging checkpoint, installed acceptance was still pending. The local
comparison guards passed nine deliberately altered comparisons, including a
modem downgrade, PIN or policy modification, missing mask, malformed boot
content, wrong module release, missing initramfs module and an extra service.
These synthetic comparisons do not establish an image or hardware pass.

The latest read-only daily snapshot is boot
`d7644ec6-9578-47ac-8a8d-230ed0398484`, kernel `.11`, deployment `d639fe55…`,
slot `_a`, SELinux enforcing, with no staged deployment or transaction.
Its watchdog boot reason follows our explicit SysRq reset of the passing
disposable repeat test; it is not another spontaneous failure. The eleven pinned
deployments and current package requests must remain intact. The active broker
listener has no active service; staging stops only that socket after checking
all native services inactive. The fprintd and Phosh masks remain during staging.

The scripts here adapt the prior inspected staging pipeline to the new exact
candidate identity. `stage-candidate.py` checks the fresh baseline and complete
OCI, records intent, pins the current deployment and stages with finalization
locked. `inspect-staged.py` checks the actual checkout, packages, files, boot
payloads, masks and labels. `preview-boot.py` generates a regular file and parses
its deployment arguments. `activate-candidate.py` can finalize only after those
checks pass. It reboots as part of the normal installed deployment workflow.

After the new boot, `claim-lifetimes.py` uses the already built plain D-Bus client
for 50 Claim/Release cycles across ten fprintd and firmware-service lifetimes.
It uses the packaged libfprint and production service configuration; the client
does not start capture or change enrollment or credential state. Each cycle and
service stop has a durable record and a UART-visible kernel-log marker. A failed
or uncertain native sequence stops further trials without killing or retrying
the worker. Phosh remains masked during this measured test.

Then perform real Settings reopen/enrollment-retention checks, correct and wrong
finger feedback, both enrolled fingers unlocking Phosh, PIN fallback followed
by fingerprint, and persistence through a full reboot with PIN entered once.
Keep the user's existing credentials, biometric stores and recovery history.
The brief unreadable wrong-finger PAM message remains a separate minor UX issue.

Daily sam-sargo is serial `994AY18RSD`, with exclusive UART adapter `A5069RR4`.
The `test-sargo` adapter and handset remain owned by another task. Premouth
promotion received explicit release after final acceptance, with the fresh .12
snapshot, packages, masks and local overrides. This task stopped its dedicated
UART recorder cleanly and verified the daily device lock and adapter released;
see `out/fingerprint-pool-fix-20260913/uart-release.json`.


The completed image is
`sha256:2edfee4f076372f6ee03b2bec60da64d583d305697d2de355ceec874dbaf8069`,
with OCI manifest
`sha256:5a2858b7b500664c3d69aab747184f77db73f5bbcaa3bb6f340f8ef03ddf801d`.
It has 131 layers. Transfer reused the previous image cache and sent 253,321,466
bytes of new image data. The complete private staging bundle passed hash checks.

The first service launcher stopped at systemd's STDOUT setup before Python ran.
Using journal output resolved that launcher failure. The next attempt reached
the directory-ownership guard: rsync had preserved desktop UID 1000 on the
staging directory. Neither attempt started a deployment transaction. The task
directory and its top-level scripts/evidence were made root-owned; hardlinked
OCI cache metadata was left alone. The third service,
`sargo-fingerprint-pool-stage-owner-fixed-20260913.service`, passed all guards,
stopped the idle broker socket, masked activation and began the locked import.
Future bundle transfers should use `--no-owner --no-group`.

The retained private UART capture is in
`out/private/sargo-kernel12-installed-20260913/`, recorded by host unit
`sargo-fingerprint-kernel12-uart-20260913.service`, now stopped cleanly. Its observed marker matches
serial 994AY18RSD and boot d7644ec6-9578-47ac-8a8d-230ed0398484.
