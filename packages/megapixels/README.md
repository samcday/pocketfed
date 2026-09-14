# Megapixels 2 camera packages

This packages upstream Megapixels **2.1.0**, with libmegapixels **0.2.3** and
libdng **0.2.2**, for the Pixel 3a camera trial. Fedora's current Megapixels
package is still 1.8.3. The 2.x stack provides the upstream Pixel 3a media
pipeline configuration and manual lens controls, independently of libcamera.

The stable 2.1.0 release uses its bundled `postprocess.sh`; it does not require
postprocessd. `dcraw`, ImageMagick and ExifTool are required so a successful
capture produces a JPEG and keeps its metadata. The application also retains
its upstream video helpers, but video recording is not part of this trial.

Sources are pinned by release tag, commit and `sources.sha256`:

| Package | Tag | Commit |
| --- | --- | --- |
| Megapixels | 2.1.0 | `5fb1f24f1aeef80ea18224ab5829fda85653a4e8` |
| libmegapixels | 0.2.3 | `d50bf166972df4252d127f72f90986892f3cd901` |
| libdng | 0.2.2 | `438df53ee06d9f21202e0398c90a9c3bf9e86591` |

The libraries intentionally publish their ABI version in pkg-config, so their
pkg-config versions are higher than their release versions. No version checks
are bypassed in the application build.

`libmegapixels` installs `google,sargo.conf` as an alias of upstream's older
`google,b4s4-sdm670.conf` name. Discovery reads the device-tree compatible list.
The upstream configuration selects the rear IMX363's 4032×3024 RGGB10P mode
with 90-degree rotation. libmegapixels release 2 places the Rear section
before Front so it is selected at startup. Lens discovery follows the media graph. Whether lens
movement works remains a hardware/runtime validation requirement; installing
these packages does not itself establish working autofocus.

## Building

### Native phone iteration

`build-native BUILD-ROOT PACKAGE` runs as an unprivileged user on the device,
clones the release tags above, verifies their exact commits, and builds RPMs
with the same patches and checks as the release specs. It records each Git
tree and generated source archive hash. The archive hashes differ from
GitLab's downloadable archives because they are generated with `git archive`;
the commit pins are the source identity for this path.

Install build dependencies with `dnf`, then build **libdng**,
**libmegapixels**, and **megapixels** in that order, installing each library's
runtime, tools and `-devel` RPMs before the next package. Only installation
needs root. The helper limits compilation to two jobs and adds `.native` to the
distribution suffix so trial RPMs can be installed over an earlier build.
Build dependency versions must match the device's installed packages; a
temporary `rpm-ostree usroverlay` is not retained across restarts.

### Source RPMs for maintained builds

On a Fedora packaging host with `rpm-build`, `redhat-rpm-config`, `curl` and
`coreutils`, run from the repository root:

```sh
packages/megapixels/build-srpms /tmp/pocketfed-camera-rpmbuild
```

The helper downloads the three release archives, verifies their SHA-256 sums
and generates one SRPM per package. It reuses archives already in `SOURCES`
after verifying them. Build order is **libdng, libmegapixels, megapixels**;
install both library `-devel` packages before building the application. Each
spec uses Fedora Meson/RPM macros and declares its build dependencies.

The library `%check` sections run upstream tests. libmegapixels additionally
lints the Pixel 3a configuration and checks its installed alias. The app
checks desktop metadata, schemas and the postprocessor's shell syntax. Its
calibration regression test compiles the actual lookup functions from the
patched source and checks missing profiles, sensor-specific names, path
precedence, the home-directory fallback, and filename bounds.

The metadata patch adopts upstream's corrected `~alpha` version spelling so
Fedora's AppStream validator sorts the older prereleases correctly.
The calibration patch corrects the 2.1.0 profile search loop and its user
profile filename. The Pixel has no bundled DCP profile, so the normal
missing-profile path must return without walking beyond the path array.
Release 2 also returns discarded blank frames to the capture queue and
corrects software control requests: exposure adjustment preserves unrelated
sensor values, a neutral frame does not write controls, and selecting a new
sensor refreshes its controls and limits. Production-function regressions
cover the finite buffer queue, initial exposure decisions, sensor replacement,
and transitions to manual controls.

Release 3 fixes nonblocking dequeue handling found during the native phone
trial. `EAGAIN` means no frame was dequeued; it must not dispatch a callback
with an uninitialized buffer. The original behavior could attempt to
requeue buffers still active in the kernel. A production-function regression
checks repeated empty reads before and after a valid frame, for single-plane
and multiplanar buffers, and rejects the original source.

Release 4 publishes changed burst state before starting capture processing,
including when an inactive preview has left the state clean. Otherwise the
processing thread can retain its initial zero burst length and never save a
DNG or invoke JPEG postprocessing. It also tags buffers with an IO stream
generation, so delayed returns from before a mode switch cannot requeue an
index already active in the new stream. Both regressions reject the original
source. All six app regressions passed on the development host and in the subsequent
native phone build. Release 4 installed successfully and produced real rear
DNG/JPEG captures after the sensor flips were corrected. The first target
image is blurred with a strong green cast, so image-quality acceptance remains
open. See the prior-validation summary for the fresh-boot Bayer-order mismatch
and the libmegapixels fix under test.

Release 5 stores the reciprocal preview white-balance gains in DNG
`AsShotNeutral`. DNG decoders divide by this tag, whereas the preview
multiplies by its correction gains. A regression using the actual export
statement checks nonidentity neutral samples and rejects release 4. The
native build and installation passed; live image-quality validation remains
pending after a separate camera transport failure and diagnostic kernel hang.

The [prior-validation summary](validation/prior-validation.md) records what was
actually built, captured and checked. A passing source regression is not a
successful camera capture.

To check the installed processing stack without a camera, install
`libdng-tools` alongside these runtime packages and run:

```sh
packages/megapixels/validation/test-postprocess-jpeg /tmp/camera-jpeg-check
```

Use a new output directory for each run. This generates a small synthetic
packed RAW10 image, wraps it as DNG, and runs the application's installed
postprocessor. It checks JPEG creation, retained DNG, camera metadata,
temporary-burst cleanup, and both quarter-turn orientations. Sargo's rear
90-degree setting uses DNG orientation 8. The resulting JPEG pixels must be
rotated with an absent or normal orientation tag, so viewers do not rotate
the image twice. This validates processing and packaging; it does not
establish camera image quality or readable document capture.

The local aarch64 Rawhide build on 2026-09-10 passed these checks, all five
library test targets, and the application calibration regression. The runtime
libraries and specs passed rpmlint without warnings; the application has only
the upstream missing-manpage warning. These local RPMs are unsigned trial
artifacts.

Current camera trials use the local `tools/liveboot` kboop/fastboop workflow
with a cached userspace fixture and USB-root boot, so public CI, COPR and a
published image are not prerequisites for an ephemeral test. Publish successful
runtime builds through `samcday/pocketfed` COPR before adding them to the image
package list, as required by `packages/README.md`. Phone validation should
include preview, a saved JPEG, manual focus/exposure, orientation, repeated
capture and reopening. Check suspend/resume and reboot after the chosen
kernel/userspace combination is installed persistently.
