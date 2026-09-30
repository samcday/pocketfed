# Native Sargo FPC libfprint package

This source package adds an experimental `fpcqsee` driver to the public
[Wrobelda libfprint tree](https://github.com/wrobelda/libfprint/tree/430e24e538ba137b6edcfe2e1b3b8cc29c66fa6a).
It uses that tree's misc-device enumeration, with independently implemented
Sargo protocol, transport, sensor and enrollment-broker code. It retains
Fedora's regular driver selection; the device-specific fprintd configuration
is isolated in the optional `libfprint-fpc-qsee` subpackage.

Files:

- `0001-fpcqsee-native-sargo-driver.patch`: driver, protocol helpers, tests and
  source documentation. Apply to commit `430e24e538ba137b6edcfe2e1b3b8cc29c66fa6a`.
- `0002-goodixqsee-include-protocol-header.patch`: add the missing declaration
  header required to compile the existing Goodix driver in the full selection.
- `libfprint.spec`: Fedora-style source package, building all drivers and
  introspection data. Its check phase runs hardware-free unit/FPC tests.
- `90-fpc-qsee.conf`: optional fprintd dependency and device-access configuration.
- `sources.sha256`, `validation/artifacts.json`: checksums of the source inputs
  and produced source RPM.
- `validation/fpc-tests.*`: ARM64 test results from the FPC-enabled development
  build. These are simulated-boundary tests, not real fingerprint captures.

The implementation handles sensor initialization, actual TA-qualified capture,
enrollment, listing/deletion, and gallery-bound verify/identify. Enrollment
requires the root-owned Unix token broker defined in
`../fpc-qsee/auth-broker.h`. Unavailable authorization, malformed responses,
transport errors, failed persistence, wrong-finger decisions and out-of-gallery
matches never produce successful enrollment/authentication. Cancellation wins
over a match even if it arrives during the TA call.

The driver completes each successful identification with target11 command4,
which also returns the firmware algorithm to a state that accepts another scan.
It does not persist adaptive template changes: the next operation reloads the
saved database, including after an out-of-gallery match. An IRQ only wakes the
capture loop. The 1.6 candidate and its failure/cancellation tests are recorded
in `finalization-build.json`; hardware validation of this correction is pending.

## Service and storage contract

Stock Fedora fprintd already permits AF_UNIX, has a writable
`StateDirectory=fprint`, and can read `/var/lib/qsee-supplicant` under its
`ProtectSystem=strict` sandbox. The optional drop-in adds only `/dev/fpc1020`
and `/dev/tee0` through `/dev/tee15` to its device allowlist. Linux's TEE core
reserves those names for unprivileged clients; the privileged TEE devices are
not admitted. No additional writable filesystem mount is needed to connect to
`/run/pocketfed-fpc-auth/token.sock`.

Required activation order is device-local stock firmware preparation,
cmnlib64 shared loader, `fpctzappfingerprint` app loader, then fprintd. The
device-specific firmware/common-library dependencies live under
`devices/google-sargo/fingerprint-trial`; this package does not enable or start
those units. It does not dynamically load Keymaster: it attaches to the resident
`keymaster64` application.

QSEE's listener namespace must be its default root-owned0700 directory
`/var/lib/qsee-supplicant`. The FPC client uses dedicated Linux group1 and the
TA filename `pocketfed/fpc-sargo-v1.db`; Android stores are never selected.
The root-owned control directory `/var/lib/fprint/fpc-qsee` holds the device
lock. Other FPC clients must respect that lock because the TA's database and
sensor state are shared across sessions.

The TA cannot distinguish absent database files from other open failures.
First initialization consequently requires an explicit root-owned0600 empty
`initialize-empty` marker in the control directory **and an entirely empty
QSEE listener namespace**. Existing QSEE contents prevent this path, even with
the marker. The package creates neither the marker nor an empty database, and
never erases QSEE contents. A verified narrower FTS namespace mapping is needed
before initializing FPC alongside preexisting QSEE storage.

## Validation

The ARM64 development build uses `drivers=fpcqsee,virtual_device`, documentation
and introspection disabled. The driver and all resulting build targets compile.
Core suites `fpi-device`, `fpi-ssm`, `fpi-assembling` and the existing Goodix
protocol suite passed;33 replay/introspection-dependent suites were skipped.
The two added test executables pass, covering six named cases:

- exact broker framing and partial stream transfers;
- rejecting an untrusted peer, unavailable broker, invalid version/challenge,
  unsuccessful response, truncation, timeout and cancellation;
- sensor capture command order and negative verify outcomes;
- identification restricted to the requested gallery;
- enrollment blocked by unavailable authorization or failed database storage;
- cancellation arriving during a successful simulated TA match.

Source RPM creation succeeds and `%prep` applies the patch with zero fuzz.
The source archive contains no `.mbn`/`.mdt` firmware or private analysis files.
The initial [ARM64 COPR build](https://copr.fedorainfracloud.org/coprs/samcday/pocketfed/build/10973647/)
stopped on the existing Goodix driver's missing response-parser declaration.
Release `1.2.pocketfed` adds that header and removes the Fedora-derived hwdb
file expectation: this source tree leaves those rules to current systemd.
The corrected all-driver ARM64 development build completes all 174 targets,
with introspection and installed tests disabled. Its seven selected unit/FPC
executables pass, recorded in `validation/all-driver-tests.json`.
Fedora's LTO subsequently exposed a test-linker interception problem in
[build 10973694](https://copr.fedorainfracloud.org/coprs/samcday/pocketfed/build/10973694/).
Release `1.3.pocketfed` compiles the same driver action source with explicit
test-only hardware/broker function names. Production sources and optimization
remain unchanged. All five selected FPC/core tests pass on ARM64 with LTO and
hardening enabled, recorded in `validation/lto-tests.json`.
The complete Fedora ARM64 all-driver RPM build now passes in
[COPR 10973705](https://copr.fedorainfracloud.org/coprs/samcday/pocketfed/build/10973705/),
with signed artifact hashes recorded in `build.json`. Live hardware/desktop
acceptance remains separate: these builds and tests do not establish successful
Sargo enrollment or screen unlocking.


## Local corrected-driver build, 12 September

Release 1.5 adds `0003-fpcqsee-handle-empty-database-identification.patch`.
Identification checks the actual TA template list first and returns a nonmatch
only for a successfully enumerated empty database. Enumeration failures remain
errors. A recognized print outside the caller gallery is reported separately
from the null authentication match, as fprintd duplicate checking requires.

The complete local ARM64 RPM build passed all seven required unit/FPC tests,
with distribution hardening and LTO, introspection, and installed tests enabled.
[The build record](local-rpm-build-20260912.json) includes source/artifact hashes
and the verified dependency on the corrected auth package (0.4 or newer).
The obsolete NSS build dependency was removed after verifying that this pinned
source uses OpenSSL. No package was published or installed by this build.
`sources.sha256` now describes 1.5; the historical 1.3 file is retained under
`validation/sources-1.3.sha256`.

On test-sargo, the corrected empty-database path has reached real enrollment.
Its next failure is a denied connection to the enrollment broker's activation
socket. Enrollment and biometric matching remain unaccepted until that policy
boundary and the real touch-driven sequence pass.
