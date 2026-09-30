# Fingerprint desktop integration for Sargo

Sam selected **PIN once after reboot, then fingerprints** on 12 September.
Keep the encrypted homed home and PIN recovery. Sam subsequently narrowed the
goal to Settings enrollment and the **Phosh lockscreen**, removing Phrog login.
The Phrog candidates and cold-start alternatives below are historical background;
do not activate them for this revised goal. See the
[acceptance target](../../devices/google-sargo/fingerprint-trial/acceptance.md).

On 12 September, daily sam-sargo passed physical right-index enrollment through
GNOME Settings, matching and nonmatching feedback, and a Phosh fingerprint unlock
without a PIN. The installed kernel is .11, SELinux is enforcing, and the encrypted
home and existing PIN route are retained. See the
[daily acceptance record](../../devices/google-sargo/fingerprint-trial/daily/desktop-first-acceptance-20260912.json).

Adding a second finger exposed an asynchronous ordering bug in Settings 51.rc.1:
the live match tester's `VerifyStop` had not completed when `EnrollStart` ran,
so fprintd rejected it with `AlreadyInUse: Verification already in progress`.
[The ordering patch](0003-users-wait-for-verification-before-enrollment.patch)
queues enrollment until the stop reply, including an already pending stop, and
discards pending enrollment on cancellation, dialog close, screen lock, or device
loss. [The regression](test-fingerprint-enrollment-order.py) compiles the actual
patched functions with delayed D-Bus callbacks; host and ARM64 runs pass, and
restoring the old ordering fails the ordering assertion. Settings
`51~rc.1-1.2.fingerprint.fc46` was applied live on daily sam-sargo, but an
unexpected reboot discarded the unfinalized update. Sam then enrolled a second
finger on the original version and reported another freeze with USB connected.
UART captured a kernel stall in cross-CPU synchronization, with CPU 1 not
responding to the diagnostic backtrace request. The initiating cause is
unconfirmed. Physical acceptance
of the ordering fix remains pending. No GNOME full-suite pass is claimed.

The inventory and initial constraints below are historical. Prepared on
11 September 2026, this directory initially contained a desktop integration
prototype and fresh read-only evidence. It does not provide a sensor driver or
claim a successful biometric match at that point. No phone authentication or service was
changed, and no enrollment, verification, or account activation was invoked.

## Current device and concrete missing pieces

The later [current inventory](live-desktop-current-20260911.json) supersedes the
initial package absence below: patched Phosh `0.57.0-1.5.fingerprint.fc46`,
Settings `51~beta-1.1.fingerprint.fc46`, fprintd/fprintd-pam `1.94.5-6.fc45`,
libfprint `1.94.100-1.3.pocketfed.fc46`, and both auth helper packages are now
installed. The home is active. fprintd is inactive/static; the native auth and
Phosh fingerprint sockets remain masked. The Keymaster startup service is
not installed, and greetd retains its original PIN PAM policy. This inventory
used read-only SSH and home1's basic GetHomeByName method; it did not run an
authentication transaction, activate a service, or read secret home fields.
The initial snapshot below is retained as historical evidence.

The [live inventory](live-desktop-2026-09-11.json) records Phosh
`0.57.0-1.fc46`, Phrog `0.53.0-3.fc45`, greetd `0.10.3-10.fc46`, GNOME Settings
`51~beta-1.fc45`, systemd `262~rc1-6.fc46`, and authselect `1.8.0-1.fc46`.
`fprintd`, `fprintd-pam`, and `libfprint` were not installed. `phrog.service`
runs greetd using `/etc/phrog/greetd-config.toml`; the separate `greetd.service`
is inactive. Phrog uses the `greetd` PAM service, not a `phrog` PAM service.

The current Phosh and greetd services use `system-auth`. Authselect has the
`local` profile with `with-systemd-homed` and `with-silent-lastlog`.
`fingerprint-auth` currently reports `authinfo_unavail`. The read-only
`authselect test` output shows that enabling `with-fingerprint` would insert
`pam_fprintd` before `pam_systemd_home` in `system-auth`; no feature was enabled.

`sam` is an active homed account using a LUKS2 loopback at `/var/home/sam.home`
and Btrfs through `/dev/mapper/home-sam`. The cryptsetup status and selected
homed fields were recorded; credential fields, keys, and biometric data were
not emitted.

## GNOME Settings enrollment

The installed Settings release already speaks fprintd's system-bus API. It
needs a device returned by `net.reactivated.Fprint.Manager.GetDevices`, an
AccountsService user whose UID equals the Settings process UID, and usable
fprintd authorization for enrollment. Its manager distinguishes a device with
no enrolled prints (Disabled) from no device (the row is hidden).
[Manager source](https://github.com/GNOME/gnome-control-center/blob/51.beta/panels/system/users/cc-fingerprint-manager.c)
and [fprintd device contract](https://fprint.freedesktop.org/fprintd-dev/Device.html).

There is a second independent blocker: the phone does **not** have the compiled
`org.gnome.login-screen` schema. In Settings `51.beta`, the row's visibility
condition requires that optional GDM schema to exist and its
`enable-fingerprint-authentication` key to be true.
[Exact row condition and optional schema lookup](https://github.com/GNOME/gnome-control-center/blob/51.beta/panels/system/users/cc-user-page.c).

The [Settings patch](0002-users-allow-fingerprint-enrollment-without-gdm.patch)
allows the enrollment UI when the optional GDM schema is absent, while honoring
an explicit false setting when it exists. Current-user and device checks are
preserved. This changes UI availability, not system authentication policy.
Installing GDM's unmodified schema is another route, but running GDM is not a
requirement of the fprintd enrollment API.

## Phosh: independent scan and PIN transactions

Stock Phosh `0.57.0` starts its PAM transaction after a nonempty PIN submission.
Its original conversation does not accept standalone informational PAM
messages, which `pam_fprintd` sends. The existing PocketFed rejected-PIN patch
fixes conversation behavior, but it does not start a scan or make it
independently cancellable. Merely putting `pam_fprintd` in the existing stack
therefore does not provide fingerprint-only unlock.
[Phosh auth source](https://gitlab.gnome.org/World/Phosh/phosh/-/blob/v0.57.0/src/auth.c)
and [lockscreen source](https://gitlab.gnome.org/World/Phosh/phosh/-/blob/v0.57.0/src/lockscreen.c).

The prepared implementation has three pieces:

- [Socket client](phosh-fingerprint-auth.c) and [PAM worker](phosh-fingerprint-worker.c):
  the client is an ordinary unprivileged process; a systemd socket starts a
  root worker. The worker derives the account from the kernel's `SO_PEERCRED`
  and uses only the fixed `phosh-fingerprint` service. It accepts no request
  data, password, account name, or service name. The client verifies its peer
  is root and reads framed messages/results. Secret prompts fail. Success
  requires `pam_authenticate`, `pam_acct_mgmt`, and cleanup to succeed.
- [Fingerprint PAM service](phosh-fingerprint.pam): bounded `pam_fprintd`
  verification, followed by account checks. Homed failures, including an
  unavailable encrypted home, fail this method. The existing PIN service stays
  separate. No authselect change is required for this service.
- [Phosh patch](0001-lockscreen-add-cancellable-fingerprint-auth.patch): starts
  a helper when its normal lockscreen is visible and usable, passes PAM status
  messages to the status label, and cancels when the user types a PIN, the
  display blanks, or the widget goes away. Closing the client connection makes
  the independent worker supervisor kill and reap its PAM child, closing the
  fprintd connection. A stale or cancelled completion cannot unlock a screen.
  Phrog and other lockscreen subclasses are excluded because their selected
  user and greetd transactions have a different owner.

The [GIO client](fingerprint-auth.c) keeps cancellation separate from reaping:
the wait always completes after killing a cancelled child. Cancellation wins
even if a successful exit races with it. The UI uses a weak reference plus
transaction identity, so a completed scan cannot authenticate a replacement
lockscreen. PIN typing does not wait for the scanner timeout.

The helper is packaged by [phosh-fingerprint-auth.spec](phosh-fingerprint-auth.spec).
It installs two executables, one new PAM service, and an `Accept=yes` systemd
socket/service pair. It has no setuid binary or installation scriptlets. A
trial image must explicitly enable `phosh-fingerprint-auth.socket`; this has
not been enabled on the phone. Connections are capped at 16, and each worker
is limited to 90 seconds. The full Phosh build carries both this source patch
and the existing `0001-auth-do-not-replay-a-rejected-token.patch`.

## Phrog and greetd

Phrog `0.53.0` starts a greetd conversation when entering the selected user's
keypad page and explicitly acknowledges fprintd's informational messages.
[Released Phrog source](https://github.com/samcday/phrog/blob/0.53.0/src/lockscreen.rs).
The existing upstream [fingerprint activity issue](https://gitlab.gnome.org/World/Phosh/phosh/-/work_items/1070)
records successful Phrog/greetd fingerprint login on different hardware after
Settings enrollment. That corroborates the architecture, not Sargo operation.

The [scoped greetd PAM candidate](greetd.pam.candidate) tries fingerprint first.
Success skips only the existing password-auth substack; absent enrollment,
rejection, failure, or timeout follows the existing PIN route. SELinux, nologin,
account, session, and optional keyring hooks are retained. The extra strict
homed account check prevents a home-activation failure being silently ignored.
This candidate is deliberately not installed by the helper package.

Phrog's current greetd transport serializes request/response handling, so this
candidate offers a bounded scan followed by PIN, not simultaneous methods.
Entering digits while an informational scan is outstanding and swiping away
need explicit testing: upstream [issue 1201](https://gitlab.gnome.org/World/Phosh/phosh/-/work_items/1201)
describes a related sensitivity/retry race. A claim of polished immediate PIN
switching requires resolving that interaction, not merely a successful match.

## Encrypted home and keyring behavior

A biometric match is an authentication result, not a decryption secret.
Homed's account/session path first calls `RefHome` for an already active or
unencrypted home; an inactive or locked encrypted home requires `AcquireHome`
and a usable credential. `RefHome` is a privileged D-Bus method: an unprivileged
fingerprint-only PAM process cannot use it even for an active home. The root
worker above is necessary for that account check; the existing PIN path can
instead obtain its reference through authenticated `AcquireHome`.
[Method privilege declarations](https://github.com/systemd/systemd/blob/8b8d819944b6713bcb8b05d8e643c21de3770d08/src/home/homed-manager-bus.c).
Thus:

| State | Fingerprint result alone |
| --- | --- |
| Active Phosh session, home still active | Can authenticate the lockscreen after a real match and account checks |
| Phrog login while the LUKS home is already active | Can authenticate and acquire a home reference |
| Cold boot or inactive/locked LUKS home | Cannot supply the missing decryption secret; the PIN is still required |

[Homed PAM implementation](https://github.com/systemd/systemd/blob/8b8d819944b6713bcb8b05d8e643c21de3770d08/src/home/pam_systemd_home.c)
and [PAM module documentation](https://www.freedesktop.org/software/systemd/man/latest/pam_systemd_home.html).

Concrete architectures that preserve PIN recovery are:

1. Keep the existing LUKS home. Require PIN activation after boot or home
   deactivation, then allow fingerprint unlock while it stays active. This is
   compatible with the current storage and keeps cold-boot key material absent.
2. For fingerprint-only cold GUI login, provide a separate cryptographic home
   unlock method, such as a supported FIDO2/PKCS#11 credential, or a reviewed
   hardware-gated key-release implementation. The built-in FPC reader is not
   established as a FIDO2 authenticator. A root daemon releasing a stored PIN
   merely because fprintd reports true is not hardware-gated key release.
3. Redesign storage around boot-time device encryption and a directory-backed
   homed account, retaining a boot PIN and login PIN fallback. That changes the
   storage/security model and requires a migration plan; no migration is
   prepared or performed here.

The PIN route also remains necessary for password-encrypted keyrings after a
login that supplies no password. Preserve the existing keyring hooks; do not
remove their encryption to hide a later password prompt.

## Validation and promotion

`make check` compiles production helper/client code with warnings as errors.
Synthetic PAM tests cover informational batches, rejection of secret prompts,
authentication rejection, account denial, missing home credentials, cleanup
failure, and fixed service/username. Root build-container tests also exercise
the production worker supervisor over a socket pair, including killing a
blocked synthetic PAM transaction on disconnect. Subprocess tests cover success, nonzero
exit, termination, pre-cancellation, and cancellation racing with success.
These tests do not load host PAM modules or communicate with fingerprint
hardware. They are not biometric positive/negative controls.

`prepare-phosh-patch.py /path/to/phosh-v0.57.0.tar.gz` verifies the recorded
archive SHA-256 and regenerates the integration patch. Build artifacts and logs
live under `build/` and are ignored by Git. [Build results](build-results.json)
record the actual isolated x86_64 RPM builds and source RPM hashes. Phosh's
full package suite passed 45 tests; the exact Fedora GNOME Settings source
RPM also built successfully (its spec contains no `%check` suite). These are
build and synthetic integration results, not device validation. ARM64 COPR
results and signature checks are recorded separately in the build metadata.
No RPM has been uploaded or installed on the phone by this subtask.

The original Phosh `1.2.fingerprint` package (COPR 10973639) is superseded: its
PAM source used `pam_unix` directly and would replace the base system-auth policy.
[The corrected spec](phosh.spec) ships [the exact existing Fedora policy](phosh-system-auth.pam)
as `%config(noreplace)`, retaining the systemd-homed PIN path and keyring hooks.
Release `1.3.fingerprint` preserves both code patches, compares the staged policy
in `%check`, and passed all 45 Phosh tests. The final binary RPM policy also
matches the verified base image byte for byte. [Packaging validation](phosh-packaging-validation.json)
records the source RPM and payload hashes. The GNOME Settings and helper
packages are unchanged.

Phosh `1.3.fingerprint` then reached 44/45 tests on ARM64 COPR 10973732, with
`status-icon` failing to open the X display before reaching its assertions.
Release `1.4.fingerprint` changes only the spec harness: tests receive a private
mode-0700 runtime directory, select X11, and run under an automatically allocated
Xvfb display with `-noreset` and visible server errors. No test is removed or
retried. The full local RPM build passed all 45 tests and final policy verification;
[the harness validation record](phosh-harness-validation.json) records the source
RPM and evidence. The failed log establishes display initialization failure; it
does not prove that a server reset was the sole cause.

ARM64 COPR 10973738 exposed a separate mockbuild restriction: reopening
`/dev/stderr` failed before the tests started. Release `1.5.fingerprint` changes
only logging to use a regular file within the private runtime directory, printed
through inherited stderr during cleanup while retaining the test exit status.
[Non-root validation](phosh-mockbuild-logging-validation.json) reproduced the old
failure and passed actual Xvfb/GTK startup, failure-status, diagnostic-output,
and cleanup checks as UID 65534. The unchanged product code was not rebuilt
locally for this logging-only change; all 45 package tests remain enabled.

For the revised goal, required daily-phone acceptance is Settings enrollment,
Phosh fingerprint unlock after initial PIN login, wrong-finger rejection, scan
cancellation, PIN fallback, and persistence across reboot. Dedicated test-sargo
has now produced verified enrollment, matches, nonmatches and restored-record
persistence through the packaged native service chain. Those laboratory results
do not complete daily-phone desktop acceptance. Phrog login and home-reference
retention are outside the revised goal.


The [12 September home-lifetime metadata](home-lifetime-metadata-20260912.json)
shows Linger disabled and two Sam SSH sessions alongside Phosh and its user
manager. Homed being active in that state does not establish the intended warm
Phrog login behavior: those sessions can retain home references. Source review
confirms that `pam_systemd_home` releases its reference on session close and
requests home release. That was relevant to the earlier Phrog scope, which Sam has since removed;
it is not a condition of the current Phosh lockscreen goal. No session was
closed or altered for that inspection.
