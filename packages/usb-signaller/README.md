# usb-signaller

Upstream [usb-signaller](https://codeberg.org/DylanVanAssche/usb-signaller)
0.4.2, Dylan Van Assche's USB gadget mode daemon. The Sargo, Crosshatch and
Fajita images use it for the USB developer link. It replaces the personal-fork
snapshot those images pinned from the `samcday/usb-signaller` COPR (build
10712403, fork commit `bf2f2d6`).

The spec is written for Fedora review. The source is the PGP-signed upstream tag
`v0.4.2` (commit `d79fae5`); its Codeberg archive matches `git archive v0.4.2`
and `sources.sha256` pins it. `0001` replaces net-tools `ifconfig` with
`ip link set dev X down` in the developer and tethering helpers. Upstream
status: prepared, not yet sent; Sam files it on Codeberg.

PocketFed carries the declared-gadgets series as `Patch1001`-`Patch1011`
(`1007`-`1011` are review fixes), with release `1.2.pocketfed` and an explicit
`%changelog` in place of the rpmautospec macros (the Mesa fork pattern). The
patches are `git format-patch` of `samcday/usb-signaller` branch
`claude/declared-gadgets` (`064c7b0`, on `v0.4.2`), draft PR
[samcday/usb-signaller#5](https://github.com/samcday/usb-signaller/pull/5);
Sam files the Codeberg MR. Together they make usb-signaller:
- merge TOML drop-ins field-wise and read `/run/usb-signaller/` as well, so an
  initramfs can declare its gadget (smoo's liveboot root) at runtime;
- leave declared and foreign gadgets alone, adopt a declared gadget in place,
  and keep its pinned functions linked across mode switches;
- refuse `host_mode` while a declared gadget with pins, or a foreign gadget
  under `foreign_gadgets = "preserve"`, is bound;
- serialise D-Bus mode switches and report failures to the caller;
- test the planner, configuration and fake configfs unprivileged in `%check`.

The series adds a direct `libc` dependency (Fedora `rust-libc-devel`).
Drop each patch when a Dylan release contains it; once none remain, restore
`%autorelease`/`%autochangelog` so the spec matches the Fedora review again.

Packaging decisions:
- The License tag includes `AGPL-3.0-only`, because the binary links
  `uapi-config`. Upstream does not state this yet.
- `%systemd_postun` without restart: stopping usb-signaller tears down the
  gadget, which may carry the session doing the upgrade.
- The package owns `/usr/lib/usb-signaller/usb-signaller.toml.d/` and
  `/etc/usb-signaller/usb-signaller.toml.d/` for vendor and admin drop-ins, and
  nothing under `/run`.
- Developer mode starts `unudhcpd@<iface>.service`, so the package requires
  `unudhcpd` (`../unudhcpd`). MTP mode needs `umtprd`, which Fedora does not
  ship. The OpenRC scripts are not installed.

Build `rust-uapi-config`, `rust-tokio-udev` and `unudhcpd` first. The common
`.copr/Makefile` builds this directory with `make_srpm`. For a local SRPM, run
`spectool -g`, check `sources.sha256`, copy the patches next to the sources, then
`rpmbuild -bs` with `_sourcedir` pointing there.

Retirement: Sam files the Fedora package reviews for this package and its three
dependencies; the review prep may run as a separate session. Link the review
bugs here once filed. When usb-signaller reaches Rawhide, delete this directory,
the COPR package and the image pins together.
