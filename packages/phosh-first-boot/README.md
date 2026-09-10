# Phosh First Boot

The signed `0.1.1-1.4.pocketfed` RPMs built successfully for Rawhide aarch64 and x86_64 in
[COPR build 10967574](https://copr.fedorainfracloud.org/coprs/build/10967574).
`build.json` records the uploaded SRPM, submitted packaging-file hashes, signed
RPM hashes, and both architectures' passing package-configuration checks.
The manifests in `builds/` preserve the earlier signed builds' provenance and
the compiled-path defect discovered by hardware testing in releases `1.1`–`1.3`.
Upstream's Rust test suites contain no tests, so the separate runtime fixture
below provides additional coverage.

This package starts from the Fedora Mobility packaging on
[`samcday/packages`, commit d64dc5a](https://forge.fedoraproject.org/samcday/packages/commit/d64dc5a)
and updates it to upstream 0.1.1. The annotated `v0.1.1` tag resolves to
`0d39c507d7464dc77bdfe256b22460d91e7c0414`. The first patch imports the
upstream dependency update from `b21ff7f74a227ac5b203d205d31a487d5b3b8d8e`
so the GTK, GLib and gettext Rust bindings use compatible versions.

The runtime patch adds a searchable time-zone selector backed by systemd's
local zone database, exposes locale failures with a retry action, and writes
the settings handoff before creating the homed account. The new account is
cached through AccountsService so Phrog can offer it for login immediately.

Release `1.2` also handles a nullable display name from libpms when the requested
translation locale is not installed. The assistant shows the locale identifier
instead of aborting. The original libpms-rs 0.0.3 binding incorrectly assumes
that the C API always returns a string; adding ISO language data alone does not
fix this case.

Release `1.3` commits navigation when account creation starts. Back navigation
is disabled while creation is pending and after the account exists, including
on the Done page, so setup cannot change the saved keyboard settings afterward.
A failed account-creation request restores Back so the user can edit and retry.

Release `1.4` preserves the RPM's Meson configuration during Cargo builds. This
fixes the incorrect development paths that prevented settings export and loaded
defaults from the wrong location in earlier releases. RPM validation checks both
the generated constants and the installed application's paths and `--help`.
It also keeps setup visible until Get started is pressed, and enables timezone
search by city name with case-insensitive substring matching.

The assistant uses `greetd` for setup and systemd-homed for account creation.
Fedora supplies the homed executable in `systemd-udev`, so the RPM requires
the executable rather than a nonexistent `systemd-homed` package. The created
user belongs to Fedora's `wheel` group. Image configuration must also enable
homed and the homed PAM integration.

Both the assistant and importer use `/var/lib/phosh-first-boot`; setup choices
therefore survive a reboot before the user's first login. The importer only
runs when exported settings exist and skips system users, non-Wayland sessions
and users with a completed-import marker. The image enables its global user
unit. The image also guards Phrog's `first-run` command on systems with an
existing regular user and preserves the greeter's dconf state.

## Rebuild

The release archive and vendored crates are pinned by `sources.sha256`. Run
`prepare-sources` with Cargo, curl, patch, GNU tar and xz installed:

```sh
packages/phosh-first-boot/prepare-sources /tmp/phosh-first-boot-sources
rpmbuild -bs --define '_sourcedir /tmp/phosh-first-boot-sources' \
  packages/phosh-first-boot/phosh-first-boot.spec
mock -r fedora-rawhide-aarch64 --rebuild /path/to/phosh-first-boot.src.rpm
```

Set `CARGO=/path/to/cargo` to choose the source-preparation toolchain. Cargo
uses the committed lockfile without updating dependencies. RPM builds are
offline after source preparation. Submit the complete SRPM to COPR; a plain
SCM build cannot fetch the locally generated vendor archive on its own.

The RPM runs the upstream Meson validation and Rust tests, ships a generated
linked-dependency license inventory and original license notices, and declares
the vendored crates through the Fedora Rust macros. The separate `validation/`
fixture exercises timezone failure and retry paths against a private D-Bus
service; its supplemental test patch is deliberately outside the published
runtime patch. See its README for commands and source mappings. Device setup
and login still require hardware testing.
