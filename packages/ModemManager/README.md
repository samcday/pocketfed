# ModemManager

PocketFed packages upstream [1.25.95-dev](https://gitlab.freedesktop.org/mobile-broadband/ModemManager/-/tags/1.25.95-dev),
the latest tagged release checked on 12 September 2026. This is an upstream
development release. Its Meson project version is `1.25.95`; the RPM uses
`1.25.95-1.pocketfed`, and the separate `upstream_tag` macro preserves the
`-dev` suffix in the source URL and extracted directory name.

The packaging retains Fedora's build flags, subpackages, service integration,
and upstream Meson tests. Its Fedora base is dist-git commit
[`fc074fd1e3d35afc57da502beb7790c361bd73ef`](https://src.fedoraproject.org/rpms/ModemManager/c/fc074fd1e3d35afc57da502beb7790c361bd73ef)
(ModemManager 1.24.2-5). The upstream release requires **libqmi >= 1.37.95**;
libmbim >= 1.32.0 and libqrtr-glib >= 1.0.0 remain sufficient.

## Source and patch provenance

The annotated upstream tag points to commit
`61e2f69d489eceb51c0ac21c2989c18c3f00f734`. Its source archive was compared with
`git archive` of that tag: all 875 regular files match byte-for-byte.
`sources` records the archive's SHA-512, and `sources.sha256` records its
SHA-256 for PocketFed's common [COPR SRPM helper](../../.copr/Makefile).
These are records for the upstream tag archive, not Fedora lookaside uploads.
Source archives and build outputs remain outside Git.

- The release already contains upstream
  [`0edcb916ad2b7267caf73bbd9a31e46da0727a00`](https://gitlab.freedesktop.org/mobile-broadband/ModemManager/-/commit/0edcb916ad2b7267caf73bbd9a31e46da0727a00),
  “base-manager: fix cleanup of multiplexed bearers.” The old downstream
  bearer patch is removed; the production-source regression remains in `%check`.
- `ModemManager-1.24.2-fix-netlink-transaction-use-after-free.patch` remains
  byte-for-byte from [COPR build 10709915](https://copr.fedorainfracloud.org/coprs/build/10709915).
  The tag still reads `tr->completion_fn` after removing the transaction from
  its owning hash table. The retained patch saves that callback first and
  applies without fuzz. Its filename records its original backport base.
- The tag includes the SDM670 GNSS support from
  [upstream merge request 1340](https://gitlab.freedesktop.org/mobile-broadband/ModemManager/-/merge_requests/1340)
  and the later
  [engine-unlock correction](https://gitlab.freedesktop.org/mobile-broadband/ModemManager/-/commit/9c4aeeb33a1abdc513f315247bbd8120780675ed).
  This provides the upstream GNSS changes missing from PocketFed's old 1.24.2
  package. Location fix quality and wake-to-LTE latency still require device
  measurements; this version update does not change suspend policy or establish
  those acceptance results.

The COPR package historically used uploaded SRPMs. This directory is the
maintained packaging source for subsequent builds.

## Regression check

The original Sargo suspend crash had one ACTIVE multiplexed bearer, a regular
bearer limit of zero, and a multiplexed limit of 254. ModemManager 1.24.2 without
the fix compared the bearer against zero and aborted before cleanup. See the
[device investigation](../../devices/google-sargo/modem-suspend.md).

`test-bearer-count.py` extracts the production enums and complete counter
functions from the prepared source tree, then compiles them unchanged against
small modem/bearer fixtures and GLib. The nine cases cover the measured Sargo
state, multiple multiplexed bearers, mixed types, filtering, transitions,
a conventional modem, and an empty list. All nine pass against 1.25.95-dev.
The RPM runs them alongside the full upstream Meson test suite.

```sh
python3 packages/ModemManager/test-bearer-count.py /path/to/ModemManager-1.25.95-dev
```

The repository's `packages/test-modem-packages` helper also checks the exact
pinned archive and applies the spec's remaining patch before running this
regression and 81voltd's fake D-Bus lifecycle tests. No modem is accessed.

## Build

The common `.copr/Makefile` builds this directory through the repository's
usual `make_srpm` flow, verifying `sources.sha256`. To prepare an uploaded SRPM
from the repository root:

```sh
repo_dir=$PWD
srpm_dir=$(mktemp -d)
curl --fail --location \
  https://gitlab.freedesktop.org/mobile-broadband/ModemManager/-/archive/1.25.95-dev/ModemManager-1.25.95-dev.tar.bz2 \
  --output "$srpm_dir/ModemManager-1.25.95-dev.tar.bz2"
(cd "$srpm_dir" && sha256sum --check "$repo_dir/packages/ModemManager/sources.sha256")
cp packages/ModemManager/*.patch packages/ModemManager/test-bearer-count.py "$srpm_dir/"
rpmbuild -bs \
  --define "_sourcedir $srpm_dir" --define "_srcrpmdir $srpm_dir" \
  --define 'dist .fc46' --define 'fedora 46' \
  packages/ModemManager/ModemManager.spec
copr-cli build --nowait \
  -r fedora-rawhide-aarch64 -r fedora-rawhide-x86_64 -r fedora-45-aarch64 \
  samcday/pocketfed "$srpm_dir/ModemManager-1.25.95-1.pocketfed.fc46.src.rpm"
```

Build the required libqmi package in the same COPR targets first. The Sargo,
Crosshatch, and Fajita image definitions require this ModemManager RPM version.
Retire the COPR override and version pins together after a suitable Fedora
package is validated.

[The historical build record](builds/1.24.2-5.1.pocketfed.json) preserves the previous
COPR and deployment verification. The previous
[COPR build 10955548](https://copr.fedorainfracloud.org/coprs/build/10955548)
was 1.24.2-5.1.pocketfed and passed nine bearer cases plus 32 upstream tests on
all three targets; those historical counts are not evidence for this release.

[build.json](build.json) records the upstream source, source RPM hash, COPR build
and target chroots for this version. The linked COPR results contain the binary
build logs and package test results.
