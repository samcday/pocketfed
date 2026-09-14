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

The helper uses the Fedora spec with the IPA path correction below, the two downstream patches
(`0001-disable-rpi-pisp.patch`, `0002-fix-ov01a10-flickering.patch`) and the
auxiliary sources (`qcam.desktop`, `qcam.metainfo.xml`, `70-libcamera.rules`)
from the verified SRPM. The patches and auxiliary sources are unchanged. It keeps:

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

Patch 0001 adds the pinned postmarketOS IMX363 tuning file; see
[tuning provenance](tuning-provenance.md). Patch 0002 adds optional bounded
saving to qcam; see [qcam trial options](qcam-bounded-save.md). The completed
`.native.1` build contains only patch 0001. Image quality remains unvalidated.
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
`libcamera`, `-ipa`, `-tools`, `-gstreamer` and `-qcam` -- using the explicit
paths from the helper output or the manifest. Do not use wildcards: they can
mix iterations or pick up stale RPMs. The example paths below refer to the
`native.1` build root on the phone. It is currently unreachable after the host
reboot. The private RPM backup survived, but this iteration has the signing
defect described below; use a corrected iteration for acceptance.

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

`validation/verify-ipa-signatures` is an explicit post-build check for one
IPA RPM. It decodes the payload from `rpm2cpio` with a bounded newc reader
that writes only the ten expected aarch64 members
`./usr/lib64/libcamera/ipa/<module>.so[.sign]`; no package script is run,
and symlinks, non-regular files, duplicates and unexpected names are
rejected without ever using an archive name as a path. It verifies the
packaged bytes of exactly `ipa_mali_c55`, `ipa_rkisp1`, `ipa_rpi_vc4`,
`ipa_soft_simple` and `ipa_vimc` with `openssl dgst -sha256` against each
module's `.so.sign`. `--key` takes the build public key (PEM or DER) or the
private key, from which it derives the public key without prompting and
without printing key material. It prints one JSON document with the module
statuses, the RPM SHA256 and the public-key SHA256, and exits nonzero if any
module is missing, has no signature or fails to verify.

Running it on the retained native.1 IPA RPM reports all five modules
invalid. The key used was the public key embedded in that build's shipped
`libcamera.so.0.7.2` (the build private key was lost in the phone reboot),
and the RPM SHA256 matched the build manifest. An unrelated key would also
report invalid, so this corroborates the recorded defect rather than proving
it independently.

```sh
packages/libcamera/validation/verify-ipa-signatures \
    --rpm <build-root>/rpmbuild/RPMS/aarch64/libcamera-ipa-<nvr>.aarch64.rpm \
    --key <build-root>/rpmbuild/BUILD/libcamera-v0.7.2/build/src/ipa-priv-key.pem

python3 packages/libcamera/validation/test-verify-ipa-signatures.py
```

The test builds throwaway RPMs from generated keys and covers a valid
package, a modified module, a missing module, a missing signature, an empty
package, a wrong key, public/private/DER key inputs and an encrypted key
that must not prompt. It also drives the reader directly with crafted
traversal, key-collision, symlink and duplicate members. The verifier is not
wired into `build-native` and does not build, install or run a package.

The helper was later run on the phone; the result is recorded under
[Native iteration 1](#native-iteration-1-4fc46native1).

## Native iteration 1 (`4.fc46.native.1`)

Iteration 1 built successfully on the phone from the pinned clone and SRPM,
applying only the IMX363 tuning task patch (`0001`). The run produced 16 binary
and debug RPMs plus a source RPM, which were backed up privately, and an
independent SHA-256 check of that backup matched the manifest hashes. A
specifically selected set of 20 non-camera libcamera library tests passed with
no failures.

The artifacts have a known defect: all five IPA modules **failed signature
verification against the build public key**. The Fedora spec's post-strip
re-sign step still uses the obsolete glob
`%{_libdir}/libcamera/ipa_*.so`, but 0.7.2 installs the modules under
`%{_libdir}/libcamera/ipa/`, so the re-sign matched nothing and left stale
signatures. The helper rewrites that glob in the packaged spec for the next
build, and its default patch directory now also carries the optional
`0002-qcam-bounded-save.patch`, which was **not** part of this build.

Iteration 1 is **not installed**, and the installed stack remains stock Fedora
`0.7.2-4.fc46`. No capture or image quality is claimed for it, and the RPMs
should not be installed as-is; rebuild with the corrected glob so the IPA
modules re-sign.

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
