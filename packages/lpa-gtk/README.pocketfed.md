# eSIM Manager for Fedora / PocketFed

This directory packages upstream **lpa-gtk 0.4**, tag commit
`35e272af38405ef1e138d89bce7acb5ac8e305fb`, without application patches.
The archive digest is recorded in `sources.sha256`. The noarch RPM uses Fedora's
Python, PyGObject, GTK4 and libadwaita, and the existing PocketFed lpac package.
No Python dependencies are vendored. The code is GPL-3.0-only, documentation
and AppStream metadata CC-BY-SA-4.0, and the icon CC0-1.0; upstream's license
texts and REUSE attribution are retained.

## Build and checks

With the four Source files and the downloaded archive in an RPM SOURCES
directory, build `lpa-gtk.spec` normally with rpmbuild/mock. Submit the resulting
source RPM to `copr-cli build samcday/pocketfed /path/to/lpa-gtk.src.rpm`.
COPR targets are Fedora Rawhide aarch64/x86_64 and Fedora 45 aarch64.

The RPM runs upstream's offline AppStream validation, desktop-file validation,
and a headless staged-install GUI test using Xvfb and a private D-Bus session.
The GUI test loads the installed Python modules/resources and checks the main
window, dummy profile list, add-profile page and slot selector. Only upstream's
dummy backend is allowed; constructing a real lpac backend fails the test.
These are packaging checks, not evidence of real eUICC access or provisioning.

## Manual testing

Installation does not launch the application or change SIM routing, profiles,
boot preference, system services, repo allowlists or image package selections.
On an ordinary Fedora installation with this COPR enabled and unfiltered:

```sh
sudo dnf install lpa-gtk
```

PocketFed image repo allowlists may not include this optional GUI. For initial
rpm-ostree testing, install the exact signed COPR RPM URL from the build record
with `sudo rpm-ostree install <rpm-url>`, then reboot when convenient. Do not
assume an unqualified package name bypasses an existing repo allowlist. The
existing lpac package is a dependency, not a bundled executable.

Launch **eSIM Manager** from Phosh, or run `lpa-gtk` as the normal desktop user.
For UI-only experimentation without modem/carrier access, instead use:

```sh
LPA_GTK_BACKEND=dummy lpa-gtk
```

The unmodified app accepts an activation-code string; it does not scan or import
QR images. Ordinary startup discovers backends and may process pending carrier
notifications, so it is not strictly read-only. Profile enable/disable/delete
actions can interrupt service. Do not reuse consumed, single-use activation codes.
Avoid sharing unredacted app logs: upstream logs can contain profile identifiers.

This package does not add Sargo-specific backend discovery, permissions,
physical/logical routing or ModemManager recovery integration. Real-device GUI
behaviour remains for manual testing. The existing lower-level eSIM enablement
and personal boot preference are separate from this packaging-only increment.
