# Reproduce the Flatpak portal comparison

The trial uses the source RPM for the phone's exact Fedora package,
`flatpak-1.19.0-3.fc46`. It retains Fedora's `fd-conflation.patch` and
`eagain.patch`. The two portal executables differ only by
`flatpak-1.19.0-retry-instance-pid.patch`; the second build reuses the first
build's common objects. Neither a full RPM nor an image is built or installed.

Download the [source RPM from Fedora Koji](https://kojipkgs.fedoraproject.org/packages/flatpak/1.19.0/3.fc46/src/flatpak-1.19.0-3.fc46.src.rpm).
Its SHA-256 is
`60cf717e9f02f91e57d8f5857d6c5d92f13cc23db9fbfa5921ca95ffbd14e2ba`.
The Koji SRPM's header and payload digests passed `rpm -Kv`; this file does
not carry an RPM signature. `sources.sha256` also pins its source archive,
Fedora patches and expanded spec.

Run the build script in an aarch64 Fedora Rawhide environment. An x86-64 host
can use Podman with its registered `qemu-aarch64-static` binfmt interpreter.
A clean Fedora Rawhide container works after installing the following build
dependencies inside that container:

```sh
dnf install -y --setopt=install_weak_deps=False \
  gcc meson ninja-build pkgconf-pkg-config rpm-build cpio patch file \
  bison gettext-devel python3-pyparsing \
  appstream-devel dconf-devel fuse3-devel fuse3 gdk-pixbuf2-devel \
  glib2-devel gpgme-devel json-glib-devel libarchive-devel libseccomp-devel \
  libcurl-devel systemd-devel libxml2-devel libzstd-devel malcontent-devel \
  ostree-devel polkit-devel wayland-devel wayland-protocols-devel \
  libXau-devel libcap-devel bubblewrap xdg-dbus-proxy
```

Prepare a source directory containing the downloaded SRPM and an empty
output directory. Mount both and this recipe directory into the build
container; the source and recipe mounts can be read-only. For example, in
the container:

```sh
bash /recipe/build-portals.sh \
  --source-dir /sources --output-dir /output --jobs 8 \
  > /tmp/flatpak-build.log 2>&1
```

The script verifies the source hashes, extracts a fresh tree, applies Fedora's
patches, and builds only `portal/flatpak-portal`. It then applies the retry
patch and rebuilds that target. Both executables and their checksums, `ldd`
output, file metadata, build package list and input hashes are in
`/output/artifacts/`. Keep the build log alongside them. The script refuses
to overwrite a nonempty output directory and makes no network calls.

The configuration preserves `/usr`, `/etc` and `/var` paths, system Bubblewrap
and D-Bus proxy executables, parental controls and Wayland security contexts.
Documentation, introspection, SELinux module generation and upstream test
targets are disabled because they do not produce this executable. The
regression harness is run separately. These are debugoptimized Meson builds,
not byte-identical rebuilds of Fedora RPM binaries: Fedora RPM hardening
macros are not applied. They retain Chromium and Flatpak sandbox behavior.

## Original build evidence

The build completed on 2026-09-08 in a disposable ARM Rawhide container on
the x86-64 desktop. Both executables printed `Flatpak 1.19.0` under QEMU.
The patched executable links `libcrypto.so.4`, matching the phone's Rawhide
ABI. No installed phone libraries or packages were changed by the build.
The production-source regression harness also passed under aarch64 QEMU,
including the negative control demonstrating the baseline's lost startup
notification. See `validation/start-notification-aarch64.txt`.

| Artifact | SHA-256 |
| --- | --- |
| Unpatched portal | `a0acf5a8e8902e9c46085f71c4cf502accc2aae10c656936e3ce97f33ed25c4d` |
| Patched portal | `85cd5955c7991961a933fb78cdbe425792935f0237742b09e7231b607946ac8e` |
| Retry patch | `6b3995b40c3993d084444dcae642111aa79f6c8d1321059b00b7d50d9f1e0abe` |

Full build logs and executables are not part of this public evidence bundle.
The source pins, build script, dependency list, and binary hashes above allow
an independent rebuild. The recorded build first needed the missing
`python3-pyparsing` dependency; after installation it completed with a
nonfatal pre-existing warning in `flatpak-prune.c`.
