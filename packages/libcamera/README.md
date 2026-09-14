# libcamera native RPM iteration

`build-native` builds versioned libcamera RPMs on the phone from the **exact
Fedora 0.7.2-4 source RPM** and a **pinned upstream clone**, so a trial can
exercise libcamera changes without waiting for a Fedora build or shipping an
image. The source clone and the compilation stay on the phone; this repository
carries the identity pins, the Fedora packaging contract and a static check.

Pinned inputs (`sources.sha256`):

| Input | SHA256 |
| --- | --- |
| `libcamera-0.7.2-4.fc46.src.rpm` | `22708eba16c1f17a918e602da7e2d5372dabb7024ee71f9a2e0365a1f99f01fc` |
| `libcamera-v0.7.2.tar.bz2` | `6f35dd479dd634a1ec50852fa9716c9da81a6c07af93bbf2990f7bbd829f0dfd` |

Upstream clone: `v0.7.2` = `191e202178f02430b5942397c70d215cdd2056fa`.

## What is preserved

The helper uses the Fedora spec, the two downstream patches
(`0001-disable-rpi-pisp.patch`, `0002-fix-ov01a10-flickering.patch`) and the
auxiliary sources (`qcam.desktop`, `qcam.metainfo.xml`, `70-libcamera.rules`)
unmodified from the verified SRPM. It therefore keeps:

- the Fedora IPA re-signing step (`ipa-sign-install.sh` after debug stripping),
  with one path correction: the spec globs `%{_libdir}/libcamera/ipa_*.so`,
  but 0.7.2 installs its IPA modules under `%{_libdir}/libcamera/ipa/`, so the
  re-sign script silently matched nothing. The helper rewrites exactly that
  line to `%{_libdir}/libcamera/ipa/*.so` in the packaged spec;
- the exact subpackage set (`libcamera`, `-devel`, `-ipa`, `-tools`, `-qcam`,
  `-gstreamer`, `-v4l2`, `python3-libcamera`);
- every version-locked subpackage dependency,
  `Requires: %{name}%{?_isa} = %{version}-%{release}`.

The helper refuses to run if the spec no longer re-signs IPA modules, if the
expected re-sign glob is absent or not a single occurrence, if fewer than all
subpackages keep that exact `Requires`, or if the subpackage set differs. It
corrects the glob path only and does not verify module signatures.

The candidate adds the pinned postmarketOS IMX363 tuning file; see
[tuning provenance](tuning-provenance.md). Its colour remains unvalidated.
Sensor gain conversion, delays and lens mapping are unchanged.

## Phone workflow

Prerequisites (root owns the device):

1. Clone upstream at the pinned commit and check out `v0.7.2`; the checkout
   stays at `/var/tmp/libcamera-native-20260914/source`.
2. Fetch the exact SRPM above and install the spec's `BuildRequires`
   (for example with `dnf builddep`).

Then, as an unprivileged user, choose a dedicated build root. Use
`/var/tmp/pocketfed-libcamera-native-*` when the overlay has room, or a
dedicated `/run/pocketfed-libcamera-native-*` directory when the overlay is
nearly full (`/run` is tmpfs and discarded on reboot). The path must be
absolute, must not be a symlink, and must be outside the repository.

`--iteration N` is mandatory and positive; the release becomes
`4.fc46.native.N` so successive builds are distinct. `--check` verifies
everything in temporary scratch without compiling:

```sh
packages/libcamera/build-native --check \
    --build-root /run/pocketfed-libcamera-native-1 --iteration 1 \
    --srpm /path/to/libcamera-0.7.2-4.fc46.src.rpm \
    --clone /var/tmp/libcamera-native-20260914/source

packages/libcamera/build-native \
    --build-root /run/pocketfed-libcamera-native-1 --iteration 1 \
    --srpm /path/to/libcamera-0.7.2-4.fc46.src.rpm \
    --clone /var/tmp/libcamera-native-20260914/source
```

`--check` verifies the SRPM hash, the SRPM's embedded upstream archive hash,
the Fedora spec layout (IPA re-signing, exact `Requires`, subpackage set), the
clone commit/tag/cleanliness and the build root. The build run regenerates the
source archive from the clone, applies any task patches in
`packages/libcamera/patches/` in name order (the current candidate adds IMX363 tuning), and runs
`rpmbuild -ba` with two jobs.

## Generated manifest

The build writes a private manifest at `$build_root/manifest.json` (never
committed). It records the iteration and `.fc46.native.N` release, the upstream
commit and tag, the original SRPM name/hash, the expected and regenerated
source archive hashes, the Fedora and task patch names/hashes, the original and
packaged Fedora spec hashes with the exact IPA re-sign glob change, the
toolchain (`arch`, `gcc`, `meson`, `ninja`, `rpm`, `rpmbuild`) and each built
RPM path with its SHA256.

## Installing the trial

Install the exact matching subpackages from a single iteration together --
`libcamera`, `-ipa`, `-tools`, `-gstreamer` and `-qcam` (qcam is now installed
on the device) -- using the explicit paths from the helper output or the
manifest. Do not use wildcards: they can mix iterations or pick up stale RPMs.

```sh
R=/run/pocketfed-libcamera-native-1/rpmbuild/RPMS/aarch64
sudo dnf install \
    "$R/libcamera-0.7.2-4.fc46.native.1.aarch64.rpm" \
    "$R/libcamera-ipa-0.7.2-4.fc46.native.1.aarch64.rpm" \
    "$R/libcamera-tools-0.7.2-4.fc46.native.1.aarch64.rpm" \
    "$R/libcamera-gstreamer-0.7.2-4.fc46.native.1.aarch64.rpm" \
    "$R/libcamera-qcam-0.7.2-4.fc46.native.1.aarch64.rpm"
```

Use `dnf install` with explicit local paths, not `dnf upgrade`. The disposable
liveboot overlay discards these packages on the next boot, so no persistent
deployment is changed. Add `libcamera-devel`, `libcamera-v4l2` or
`python3-libcamera` only when a trial actually needs them.

## Validation

`validation/test-build-native.py` is a static/argument check. It runs `bash -n`,
exercises argument handling (including the mandatory positive `--iteration`)
and the pure guard functions (pinned hashes, `/var/tmp` and `/run` build-root
safety, clone identity, Fedora spec preservation and manifest generation), and
confirms the pins in `sources.sha256`. It does not build, install, or touch a
device:

```sh
python3 packages/libcamera/validation/test-build-native.py
```

**No successful `build-native` RPM build has been verified or is claimed.**
The helper is prepared for the phone's native iteration and still needs a real
run there.

## Build tree retention

`rpmbuild` removes the build tree after packaging by default (`--clean` is the
documented default), so the helper passes `--noclean` and the Meson build tree
under `<build-root>/rpmbuild/BUILD/` survives the build. The helper still
builds from source every run and does not offer a resume or repackage mode.

## Limitations

- Building needs the Fedora build dependencies and network for the clone; the
  helper is not offline.
- The helper never installs, changes a deployment or reboots; persistence is a
  separate image or repository step.
- It does not add, remove or reorder subpackages; a needed packaging change is
  a deliberate edit to the Fedora spec, not a helper option.
