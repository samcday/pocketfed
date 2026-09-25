# rust-uapi-config

The crate [`uapi-config`](https://github.com/Arnavion/uapi-config) 0.2.0
implements the UAPI.6 configuration file search. usb-signaller needs it to
build, and Fedora does not package it yet.

The spec is unmodified rust2rpm 28 output; all customisation lives in
`rust2rpm.toml`, so regenerating reproduces the spec. The published crate omits
`test-files/`, which the unit tests read, so Source10 is the GitHub archive of
the same tag and `%prep` extracts only that directory. `Cargo.toml`'s `include`
list keeps it out of `-devel`. `sources.sha256` pins both archives. Upstream
status: shipping `test-files/` in the crate is an optional request for Sam to
file.

The crate is `AGPL-3.0-only`, which Fedora allows. Every binary that links it
must list that licence in its License tag.

Build it with the common `.copr/Makefile` (`make_srpm`), or locally with
`spectool -g`, `sha256sum --check sources.sha256` and `rpmbuild -bs`.

Retirement: Sam files the Fedora review; the review prep may run as a separate
session. Link the review bug here once filed, and delete this directory and the
COPR package once Rawhide ships `rust-uapi-config`.
