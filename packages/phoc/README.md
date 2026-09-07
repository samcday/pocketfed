# Phoc touch-up lifetime hotfix

PocketFed carries a Phoc fix for a compositor crash while releasing a touch on
Phosh's top panel. Gesture handling can cancel the touch and free its wlroots
record while the touch-up handler is still using it. Losing Phoc ends the
graphical session even though the phone remains running. Opening the panel is
enough to enter this path; toggling Wi-Fi is not required.

The packaging base is Fedora Rawhide dist-git commit
[`5cc17f1c3a62dbbe55323152d6865d08799a9e71`](https://src.fedoraproject.org/rpms/phoc/c/5cc17f1c3a62dbbe55323152d6865d08799a9e71),
Phoc 0.57.0-2. PocketFed uses release `2.1.pocketfed` to upgrade that package.
Fedora's build flags, dependencies, installed files, and upstream Meson tests
are retained. The downstream changes are the touch-up patch, explicit release
and expanded changelog, and the `phoc-touch-up-lifetime-fix = 1` capability.

## Source and patch provenance

- `805.diff` is copied byte-for-byte from Fedora's packaging. It backports
  [upstream merge request 805](https://gitlab.gnome.org/World/Phosh/phoc/-/merge_requests/805)
  to make the existing screenshot tests wait for matching frames.
- `phoc-0.57.0-touch-up-lifetime.patch` reacquires the touch point after
  gesture dispatch so the handler does not use a record freed by cancellation.
  Its regression test is registered in the upstream Meson suite and runs
  through the retained RPM `%check`. The crash corresponds to
  [upstream issue 408](https://gitlab.gnome.org/World/Phosh/phoc/-/issues/408).
- `sources` is Fedora's unmodified SHA-512 lookaside record. Both the Phoc
  release archive and pinned gvdb archive were verified against it.
  `sources.sha256` pins those same archives for the common
  [COPR SRPM helper](../../.copr/Makefile). Archives and build outputs stay
  outside Git.

## Rebuild the uploaded SRPM

From the PocketFed repository root:

```sh
repo_dir=$PWD
srpm_dir=$(mktemp -d)
curl --fail --location \
  https://gitlab.gnome.org/World/Phosh/phoc/-/archive/v0.57.0/phoc-v0.57.0.tar.gz \
  --output "$srpm_dir/phoc-v0.57.0.tar.gz"
curl --fail --location \
  https://gitlab.gnome.org/GNOME/gvdb/-/archive/4758f6fb7f889e074e13df3f914328f3eecb1fd3/gvdb-4758f6fb7f889e074e13df3f914328f3eecb1fd3.tar.gz \
  --output "$srpm_dir/gvdb-4758f6fb7f889e074e13df3f914328f3eecb1fd3.tar.gz"
(cd "$srpm_dir" && sha256sum --check "$repo_dir/packages/phoc/sources.sha256")
cp packages/phoc/805.diff packages/phoc/*.patch "$srpm_dir/"
rpmbuild -bs \
  --define "_sourcedir $srpm_dir" --define "_srcrpmdir $srpm_dir" \
  --define 'dist .fc46' --define 'fedora 46' packages/phoc/phoc.spec
copr-cli build --nowait \
  -r fedora-rawhide-aarch64 -r fedora-rawhide-x86_64 \
  samcday/pocketfed "$srpm_dir/phoc-0.57.0-2.1.pocketfed.fc46.src.rpm"
```

The targets are Rawhide aarch64 and x86_64. The existing Fedora 45 COPR target
is left unchanged; it does not receive this hotfix build.

## Image selection and retirement

The Phosh image enables `samcday/pocketfed` at priority 50, restricted to
`phoc,phoc-*`. It explicitly installs `phoc-touch-up-lifetime-fix` with
`--allow-vendor-change`, allowing DNF to select the COPR rebuild over Fedora's
package. CI checks that the resulting image contains a provider for that
capability. The device repo files retain the Phoc allowlist when they replace
the desktop repo definition, alongside their existing modem packages.

Once a Fedora Phoc build containing the lifetime correction passes the
regression and top-panel touch testing, remove the image's virtual-capability
requirement and CI assertion, remove `phoc,phoc-*` from the COPR allowlists,
and retire the COPR Phoc package. Remove the Phosh COPR file and its `COPY`
only if it has no remaining hotfix packages. Repository priority must not
keep selecting the older downstream build over the fixed Fedora release.
