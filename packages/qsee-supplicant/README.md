# QSEECOM supplicant for the Sargo fingerprint trial

Source is pinned to upstream `36e06680cf7f690fccbdcd07abc2a64c4bb061d8`
(version 0.1.1). [Upstream project](https://github.com/wrobelda/qsee-supplicant).
The RPM includes the FS and GPFS listener daemon and ordinary app loader.

`0001-loader-shared-libraries.patch` adds explicit
`qsee-app-loader --shared cmnlib64` and `qsee-shared-loader@.service` for the
reviewed Sargo kernel's two-parameter privileged service-image loading ABI.
Shared-library lifetime belongs to the running secure firmware: closing this
loader's session must not send an application-unload request. The kernel caches
only confirmed successful loads; arbitrary load errors remain failures.

The patch also checks the TEE result before reporting readiness and closes the
signal-check/wait race in the loader. Tests check both session request shapes,
remote failure, mmap failure and cleanup, alongside upstream protocol,
filesystem confinement, readiness and app-acquisition tests. All pass locally.

The isolated COPR repository is `samcday/pocketfed:custom:fingerprint-trial`:

- [10973528](https://copr.fedorainfracloud.org/coprs/build/10973528): baseline
  `0.1.1-1.1.pocketfed.fc46`, successful ARM64 build.
- [10973582](https://copr.fedorainfracloud.org/coprs/build/10973582): patched
  `0.1.1-1.2.pocketfed.fc46`, successful ARM64 build. Downloaded RPM
  digests and signatures verified against the configured PocketFed COPR key;
  hashes are recorded in [build.json](build.json). Live compatibility remains untested.

No TA is bundled or selected automatically. Sargo image integration must
extract its own firmware and order the required shared library/app loaders
after the listener service. No service from this package has been installed or
started on the phone by this task.

The listener follow-up in `0002-listener-readiness-lifetime.patch` is packaged
as `0.1.1-1.3.pocketfed.fc46`, built successfully in
[COPR10973847](https://copr.fedorainfracloud.org/coprs/build/10973847).
All downloaded RPM signatures are verified in `readiness-build.json`.
It exits after losing a registered listener transport so systemd withdraws
readiness, preserves startup retries before readiness, and checks each TEE
registration status. Eight lifecycle and five registration scenarios cover
this boundary, alongside the existing upstream/loader tests. No service was
started on the phone or incorporated into the earlier masked image.

The local `1.4` candidate adds an optional `qsee-supplicant-sargo-rpmb`
subpackage. Its combined listener carries the tested RPMB framing and MMC
transport into a hardware-checked installed-service path. It ships an inactive
service template and performs no provisioning. Host tests and the full offline
ARM64 RPM build passed; runtime acceptance and activation remain pending.
See [the candidate details](sargo-rpmb/README.md) and
[build evidence](sargo-rpmb-build.json). The current liveboot continues using
its original, separately bounded receiver.
