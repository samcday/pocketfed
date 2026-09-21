# Mesa a3xx Patch A trial

This is Fedora `mesa-26.2.2-6.fc46` with **only Patch A** from
[PocketFed #80](https://github.com/samcday/pocketfed/issues/80). It disables
UBO-to-push-constant lowering for fragment shaders on `compiler->gen < 4`.
Vertex shaders and a4xx+ retain the normal lowering. No WFI workaround,
Patch B/C, runtime debug knobs, or freedreno-only build is included.

The spec differs from Fedora only in release, Patch0 and changelog. Fedora's
full package layout, driver selection and normal `%meson` build mode are
preserved. In particular, a Mesa debug build can mask this hang by adding WFI.
The release `6.2.pocketfed.a3xxfs` supersedes the old COPR WFI experiment
`6.1.pocketfed.a3xxwfi` without incorporating its patch.

## Reproduce the source RPM

Start at this repository's root on a Fedora host with curl, rpm-build, cpio
and coreutils. Submission additionally requires `copr-cli`, a configured COPR
API token in `~/.config/copr`, and build permission on the trial project.
Use a fresh absolute build directory:

```sh
package_dir="$PWD/packages/mesa"
build_dir=$(mktemp -d /tmp/pocketfed-mesa.XXXXXX)
mkdir -p "$build_dir"/{SOURCES,SPECS}
curl -fL -o "$build_dir/fedora.src.rpm" \
  https://kojipkgs.fedoraproject.org/packages/mesa/26.2.2/6.fc46/src/mesa-26.2.2-6.fc46.src.rpm
printf '%s  %s\n' \
  845057b5424d10ecaf00e179a1667c9784a73070b732ded14d1ab01e6b940fe7 \
  "$build_dir/fedora.src.rpm" | sha256sum -c -
(cd "$build_dir/SOURCES"; rpm2cpio ../fedora.src.rpm | cpio -idm --quiet)
cp "$package_dir/mesa.spec" "$build_dir/SPECS/"
cp "$package_dir/A-fd3-no-fs-push-ubo.patch" "$build_dir/SOURCES/"
(cd "$build_dir/SOURCES"; sha256sum -c "$package_dir/sources.sha256")
rpmbuild -bs --define "_topdir $build_dir" --define 'dist .fc46' \
  "$build_dir/SPECS/mesa.spec"
copr-cli build --nowait -r fedora-rawhide-aarch64 samcday/adreno-a3xx-trial \
  "$build_dir/SRPMS/mesa-26.2.2-6.2.pocketfed.a3xxfs.fc46.src.rpm"
```

The patch is byte-identical to the issue's upstream candidate (SHA-256
`dc4b96925ef7b3c2f072ca63ff6150cc85c82dba75fcadacbe218e28a5a02bc8`).
It applies to this tarball with zero fuzz and an eleven-line offset.
Its commit message predates the final DB410c runs; the linked issue evidence
below supersedes the older hardware-validation paragraph.

## A5 image integration

`devices/samsung-a5u-eur/mesa-version` pins every installed subpackage built
from the Mesa source RPM, plus the required EGL/GBM/GL/DRI packages. The
transaction explicitly permits downgrades: Rawhide has already moved to 26.2.3,
while the hardware evidence is for this 26.2.2 source. It selects packages only
from the trial COPR, verifies signatures, and fails if the exact version is
unavailable. The COPR remains disabled for ordinary package transactions.

`pocketfed-verify-mesa` rejects missing core packages or mixed versions,
including optional Mesa packages inherited from the Phosh base. It also checks
the EGL, GBM, Gallium and msm DRI files. The final A5 OCI verifier calls it again.
The shared Phosh image and other device images are not changed.

## Evidence and remaining checks

The [exact Patch A experiment](https://github.com/samcday/pocketfed/issues/80#issuecomment-5758800870)
passed the full R3 trace and 450/450 animated probe frames on DB410c in default
GMEM without debug overrides. Settings panel switching and pixel comparisons
were performed on the equivalent V2/V3 knob builds, not on this RPM build.
[Stock controls](https://github.com/samcday/pocketfed/issues/80#issuecomment-5758932277)
still hang; do not repeat stock GMEM merely to obtain a reference image.

[COPR build 11018894](https://copr.fedorainfracloud.org/coprs/build/11018894)
is compiling for `fedora-rawhide-aarch64`; verification of the resulting RPMs
is pending. Completed checks: source checksums, zero-fuzz patch application,
SRPM creation, shell syntax/ShellCheck, rejection of stock 26.2.3 by the image
verifier, and failure of the exact install transaction while the pin is absent. This is not yet
A5 GPU validation: its earlier working greeter used Pixman/Cairo with
`msm.skip_gpu=1`. The next accelerated trial also needs the GPU IOMMU enabled,
working firmware/driver initialization, and removal of those software-rendering
overrides. Retain UART and a known-working software image for recovery.

After boot, confirm the loaded packaged driver and hardware renderer, then run
the R3 trace, animated probe and Settings in default GMEM. Exact-Patch-A pixel
comparison and performance across hardware remain open. Sam will handle the
upstream Mesa submission separately.
