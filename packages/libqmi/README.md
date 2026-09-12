# libqmi for ModemManager 1.25.95

Fedora-derived packaging updated to stable upstream `1.38.0`, satisfying
ModemManager `1.25.95`'s `qmi-glib >= 1.37.95` requirement. The package still
provides the normal runtime, development files and utilities, including QRTR
support and `libqmi-glib.so.5`. The independent
`pocketfed-qmicli-pdc-fixed` helper is retained unchanged.

Upstream tag [`1.38.0`](https://gitlab.freedesktop.org/mobile-broadband/libqmi/-/tags/1.38.0)
was created on 2 January 2026 and points to
`e3d79ed3f7fdc6a7fa8b374860b1c23a8f172812`. The source archive SHA256 is recorded
in `sources.sha256`.

Two existing fixes remain necessary because neither is in this tag:

- Upstream [`082bf3454c011e1481375e843a0c91c9e338d422`](https://gitlab.freedesktop.org/mobile-broadband/libqmi/-/commit/082bf3454c011e1481375e843a0c91c9e338d422)
  supplies missing nested GArray element annotations for PyGObject 3.56+. It
  fixes Python UIM application-ID and PDC profile-ID array decoding, without a
  C ABI change.
- PocketFed's existing `80384c0db2b5eaf376a23521d44ccec9c24299ca` removes
  `g_free()` on data borrowed from `GMappedFile` in qmicli PDC configuration
  loading. The mapped file retains ownership of that buffer.

The API reference now uses `gi-docgen` (the upstream option remains named
`gtk_doc`) and installs under `/usr/share/doc/libqmi-glib-1.0`, owned by the
development subpackage.

`%check` runs upstream's Meson tests and the generated-GIR regression check
for the affected PDC and UIM byte arrays. Hardware acceptance is separate from
package build success; no positioning, suspend, IMS or LTE result is implied
by this version update.

[build.json](build.json) records the upstream source, source RPM hash, COPR build
and target chroots for this version. The linked COPR results contain the binary
build logs and package test results.
