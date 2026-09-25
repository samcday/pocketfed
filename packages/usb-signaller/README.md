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
`spectool -g`, check `sources.sha256`, copy the patch next to the sources, then
`rpmbuild -bs` with `_sourcedir` pointing there.

Retirement: Sam files the Fedora package reviews for this package and its three
dependencies; the review prep may run as a separate session. Link the review
bugs here once filed. When usb-signaller reaches Rawhide, delete this directory,
the COPR package and the image pins together.
