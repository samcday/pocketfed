# libcamera native RPM iteration

`build-native` builds libcamera RPMs on the phone from the **exact Fedora
0.7.2-4 source RPM** and a **pinned upstream clone**, so a trial can exercise
libcamera changes without waiting for a Fedora build or shipping an image. The
source clone and the compilation stay on the phone; this repository carries the
identity pins, the Fedora packaging contract and a static check.

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

- the Fedora IPA re-signing step (`ipa-sign-install.sh` after debug stripping);
- the exact subpackage set and their version-locked dependencies
  (`libcamera`, `-devel`, `-ipa`, `-tools`, `-qcam`, `-gstreamer`, `-v4l2`,
  `python3-libcamera`).

The helper refuses to run if the spec no longer re-signs IPA modules or if the
subpackage set differs. The build uses the `.fc46.native` distribution suffix
so the local RPMs are identifiable and sort above the Fedora release.

No sensor patch is included: the IMX363 gain/exposure proof is still pending,
so this package carries no speculative sensor changes.

## Phone workflow

Prerequisites (root owns the device):

1. Clone upstream at the pinned commit and check out `v0.7.2`; fetch the exact
   SRPM above.
2. Install the Fedora build dependencies for that SRPM (the spec's
   `BuildRequires`), for example with `dnf builddep` on the spec.

Then, as an unprivileged user with a dedicated build root under `/var/tmp`:

```sh
packages/libcamera/build-native --check \
    --build-root /var/tmp/pocketfed-libcamera-native \
    --srpm /path/to/libcamera-0.7.2-4.fc46.src.rpm \
    --clone /path/to/libcamera

packages/libcamera/build-native \
    --build-root /var/tmp/pocketfed-libcamera-native \
    --srpm /path/to/libcamera-0.7.2-4.fc46.src.rpm \
    --clone /path/to/libcamera
```

The helper verifies the SRPM hash, the SRPM's embedded upstream tarball, the
clone commit/tag/cleanliness and the Fedora spec layout before doing any work.
It regenerates the source archive from the clone, applies any task patches in
`packages/libcamera/patches/` in name order (none are shipped today), and runs
`rpmbuild -ba` with two jobs. The build root must be an absolute, non-symlink
directory under `/var/tmp` and outside the repository.

## Installing the trial

Install the matching runtime pieces together so the IPA plugins match the
library, instead of upgrading the rest of the system:

```sh
sudo dnf install \
    /var/tmp/pocketfed-libcamera-native/rpmbuild/RPMS/aarch64/libcamera-0.7.2-*.aarch64.rpm \
    /var/tmp/pocketfed-libcamera-native/rpmbuild/RPMS/aarch64/libcamera-ipa-0.7.2-*.aarch64.rpm \
    /var/tmp/pocketfed-libcamera-native/rpmbuild/RPMS/aarch64/libcamera-tools-0.7.2-*.aarch64.rpm \
    /var/tmp/pocketfed-libcamera-native/rpmbuild/RPMS/aarch64/libcamera-gstreamer-0.7.2-*.aarch64.rpm
```

Use `dnf install` with explicit local paths, not `dnf upgrade`. The disposable
liveboot overlay discards these packages on the next boot, so no persistent
deployment is changed. Add `libcamera-devel`, `libcamera-v4l2` or
`python3-libcamera` only when a trial actually needs them.

## Validation

`validation/test-build-native.py` is a static/argument check. It runs `bash -n`,
exercises the argument handling and the pure guard functions (pinned hashes,
build-root safety, clone identity and Fedora spec preservation), and confirms
the pins in `sources.sha256`. It does not build, install, or touch a device:

```sh
python3 packages/libcamera/validation/test-build-native.py
```

**No successful `build-native` RPM build has been verified or is claimed.**
The helper is prepared for the phone's native iteration and still needs a real
run there.

## Limitations

- Building needs the Fedora build dependencies and network for the clone; the
  helper is not offline.
- It never changes a deployment and never reboots. Persisting a build means
  composing an image or a package repository, which is out of scope here.
- It does not add, remove or reorder subpackages; a needed packaging change is
  a deliberate edit to the Fedora spec, not a helper option.
