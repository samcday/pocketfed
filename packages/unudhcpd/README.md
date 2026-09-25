# unudhcpd

[unudhcpd](https://gitlab.postmarketos.org/postmarketOS/unudhcpd) 0.5.0 is
postmarketOS's single-lease DHCP server (Clayton Craft, `GPL-3.0-or-later`).
The usb-signaller developer-mode helper starts `unudhcpd@<iface>.service`, and
developer mode fails without it, so usb-signaller requires this package. Fedora
does not package it yet.

It hands the USB host 172.16.42.2 and advertises no router and no DNS, so the
phone's management link never becomes the host's default route.

The spec uses upstream's meson build and systemd template unit, and removes the
OpenRC script. `%check` runs upstream's meson tests. `sources.sha256` pins the
GitLab archive. Upstream status: nothing to carry. Two nits for Sam to report:
`meson.build` still says version `0.1`, and the OpenRC script's default server
address is 172.16.41.1.

Build it with the common `.copr/Makefile` (`make_srpm`), or locally with
`spectool -g`, `sha256sum --check sources.sha256` and `rpmbuild -bs`.

Retirement: Sam files the Fedora review; the review prep may run as a separate
session. Link the review bug here once filed, and delete this directory and the
COPR package once Rawhide ships `unudhcpd`.
