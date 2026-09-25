# rust-tokio-udev

The crate [`tokio-udev`](https://github.com/jeandudey/tokio-udev) 0.10.0
provides the asynchronous udev monitor that usb-signaller uses. Fedora does not
package it yet.

The spec is rust2rpm 28 output (run with `-I`); all customisation lives in
`rust2rpm.toml`. The published crate contains no licence texts, so Source10 and
Source11 are the REUSE `LICENSES/Apache-2.0.txt` and `LICENSES/MIT.txt` from the
matching upstream tag, installed with the crate. `sources.sha256` pins the
crate and both texts. Upstream status: asking upstream to ship the licence texts
in the crate is a report for Sam to file.

The licence is `Apache-2.0 OR MIT`. The crate has no tests, so `%check` only
compiles the library and the `usb_hotplug` example.

Build it with the common `.copr/Makefile` (`make_srpm`), or locally with
`spectool -g`, `sha256sum --check sources.sha256` and `rpmbuild -bs`.

Retirement: Sam files the Fedora review; the review prep may run as a separate
session. Link the review bug here once filed, and delete this directory and the
COPR package once Rawhide ships `rust-tokio-udev`.
