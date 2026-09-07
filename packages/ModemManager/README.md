# ModemManager suspend fix

PocketFed forks Fedora's ModemManager packaging to fix an abort during suspend
cleanup on Qualcomm modems using multiplexed data bearers. The package also
retains PocketFed's existing netlink transaction lifetime correction.

The Fedora packaging base is dist-git commit
[`fc074fd1e3d35afc57da502beb7790c361bd73ef`](https://src.fedoraproject.org/rpms/ModemManager/c/fc074fd1e3d35afc57da502beb7790c361bd73ef),
whose `rpmautospec calculate-release` result is `5` (ModemManager 1.24.2-5).
PocketFed uses release `5.1.pocketfed` so this build upgrades both Fedora's
release 5 and the previous PocketFed release `4.1.pocketfed`.
Fedora's build flags, subpackages, service integration, and `%meson_test`
checks are retained. The downstream changes are the two patches, explicit
release and expanded changelog, plus the bearer regression check in `%check`.

## Source and patch provenance

The previous PocketFed package was based on Fedora dist-git commit
[`8fc8008d6bc39f95999ce7b7848ef291e7959217`](https://src.fedoraproject.org/rpms/ModemManager/c/8fc8008d6bc39f95999ce7b7848ef291e7959217),
ModemManager 1.24.2-4. The later Fedora release-5 commit is a mass rebuild;
the two commits' spec files are byte-identical and use the same source archive.
The previous build's spec, excluding release, patch declaration, and generated
changelog, also matches that Fedora spec.

The checked-in `sources` file is Fedora's unmodified lookaside record. The
source archive's SHA-512 was verified against it:

```
692d0699037845f7e189cc854f6fbaab90615c9eaaada83a00a02745d13bd87afac16349a4211425929a84cf373fda18475479bff64c9fe89cb35b361fb45663
```

`sources.sha256` records the same archive for PocketFed's common
[COPR SRPM helper](../../.copr/Makefile). Source archives and build outputs
remain outside Git.

- `ModemManager-1.24.2-fix-netlink-transaction-use-after-free.patch` is preserved
  byte-for-byte from the previous PocketFed
  [COPR build 10709915](https://copr.fedorainfracloud.org/coprs/build/10709915).
  It saves the completion callback before removing the transaction from its
  owning hash table. The original device packaging identified upstream
  `c0900eefe196` as the corresponding fix. The exact old
  [source RPM](https://packages.redhat.com/api/pulp-content/public-copr/samcday/pocketfed/fedora-45-aarch64/Packages/m/ModemManager-1.24.2-4.1.pocketfed.fc45.src.rpm)
  has SHA-256
  `15c4bfe0c21fff11864ac6d5096f62e445f9b279ff3bc4a48d6876e6e3d18942`.
- `ModemManager-1.24.2-fix-multiplexed-bearer-cleanup.patch` is the unmodified
  upstream commit
  [`0edcb916ad2b7267caf73bbd9a31e46da0727a00`](https://gitlab.freedesktop.org/mobile-broadband/ModemManager/-/commit/0edcb916ad2b7267caf73bbd9a31e46da0727a00),
  “base-manager: fix cleanup of multiplexed bearers.” It adds multiplexed
  capacity when counting ACTIVE or CONNECTED bearers. Both patches apply
  cleanly to the exact Fedora source archive.

The old COPR package was an uploaded SRPM, with no configured SCM source.
This directory is the maintained packaging fork for subsequent builds.

## Regression check

The Sargo crash core showed one ACTIVE bearer, a regular bearer limit of zero,
and a multiplexed limit of 254. The old counter compares that bearer against
zero and aborts before modem cleanup starts. See the
[device investigation](../../devices/google-sargo/modem-suspend.md).

`test-bearer-count.py` extracts the production enums and complete counter
functions from the prepared source tree, then compiles them unchanged against
small modem/bearer fixtures and GLib. It does not reproduce the counting
algorithm in the test. The nine cases cover the measured Sargo state,
multiple multiplexed bearers, mixed bearer types, filtering, state transitions,
a conventional modem, and an empty list.

Before patching, the Sargo case reproduces the `max >= ctx.count` abort.
With the upstream patch, all nine cases pass. This check is included in the
RPM's `%check` alongside Fedora's upstream test suite. It verifies the source
accounting fix; device suspend/resume and real voice calls remain separate
acceptance tests.

Run the check manually against a source tree after `%prep`:

```sh
python3 packages/ModemManager/test-bearer-count.py /path/to/ModemManager-1.24.2
```

## Build

The common `.copr/Makefile` can build this directory through the repository's
usual `make_srpm` flow; `sources.sha256` enables its checksum verification.
To prepare an uploaded SRPM from the repository root:

```sh
repo_dir=$PWD
srpm_dir=$(mktemp -d)
curl --fail --location \
  https://gitlab.freedesktop.org/mobile-broadband/ModemManager/-/archive/1.24.2/ModemManager-1.24.2.tar.bz2 \
  --output "$srpm_dir/ModemManager-1.24.2.tar.bz2"
(cd "$srpm_dir" && sha256sum --check "$repo_dir/packages/ModemManager/sources.sha256")
cp packages/ModemManager/*.patch packages/ModemManager/test-bearer-count.py "$srpm_dir/"
rpmbuild -bs \
  --define "_sourcedir $srpm_dir" --define "_srcrpmdir $srpm_dir" \
  --define 'dist .fc46' --define 'fedora 46' \
  packages/ModemManager/ModemManager.spec
copr-cli build --nowait \
  -r fedora-rawhide-aarch64 -r fedora-rawhide-x86_64 -r fedora-45-aarch64 \
  samcday/pocketfed "$srpm_dir/ModemManager-1.24.2-5.1.pocketfed.fc46.src.rpm"
```

The package is selected by version checks in the Sargo, Crosshatch, and Fajita
image definitions. When Fedora carries both corrections, validate its package
and retire the downstream pins and COPR override together.

[COPR build 10955548](https://copr.fedorainfracloud.org/coprs/build/10955548)
succeeded on all three requested targets. Each passed the nine bearer counter
cases and 32 upstream tests. [build.json](build.json) records source/RPM hashes,
verified signatures and image integration checks. Device suspend/call acceptance
remains separate from these build results.
