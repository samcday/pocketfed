# PocketFed Packages

Packaging for software that PocketFed needs before it exists in Fedora proper.

Image builds should consume packages from the `samcday/pocketfed` COPR instead
of building runtime components ad hoc during composition. Package sources should
stay as close as practical to Fedora-reviewable RPM packaging.

Kernel packaging is the exception that is not intended for Fedora review: it is
a temporary transport for the downstream PocketFed kernel branch until the image
can use Fedora's aarch64 kernel plus external modules and devicetrees.

## Modem package regression tests

`test-modem-packages` downloads the pinned ModemManager and 81voltd source
archives, verifies each package's `sources.sha256`, and applies the patches
declared in its spec. It then executes ModemManager's production-source bearer
counter regression and builds/runs 81voltd's Meson tests against a private
fake ModemManager D-Bus service. It does not access a modem or place a call.

The `modem-package-regressions` CI job runs these checks in Fedora Rawhide on
the existing Ubuntu ARM runner. RPM builds and their full `%check` suites remain
part of COPR; this job exercises the maintained regression tests directly.

On Fedora, install the test dependencies and run from the repository root:

```sh
sudo dnf install gcc patch meson ninja-build pkgconf-pkg-config \
  glib2-devel ModemManager-glib-devel libqmi-devel 'pkgconfig(qrtr)' \
  python3 python3-gobject-base dbus-daemon
packages/test-modem-packages --source-cache /tmp/pocketfed-modem-sources --fetch-only
packages/test-modem-packages --source-cache /tmp/pocketfed-modem-sources --offline
```

Use `--work-dir /path/to/new-directory` to retain the prepared trees and Meson
logs at a chosen location. Source downloads can happen separately from tests;
after fetching, the test command also works in a container with networking
disabled and the repository/source cache mounted read-only.
