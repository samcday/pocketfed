# Sargo camera native bootstrap

`native-bootstrap.sh` builds and locally installs the pinned
libdng/libmegapixels/Megapixels camera stack **on the phone, inside a
disposable PocketFed liveboot session**. It is the on-device counterpart to
`packages/megapixels/build-native`: the same helper does the clone/build, and
this wrapper adds platform guards, the root `dnf` phase and explicit local RPM
installs.

It exists so the camera userspace can be iterated without publishing packages,
building an image or staging a deployment: boot a liveboot USB-root session,
run this once, and test. Everything installed lives in the disposable liveboot
overlay and disappears on the next boot.

## Why no rpm-ostree overlay

A liveboot root is already a writable overlay over the read-only EROFS fixture,
so `rpm-ostree usroverlay` is neither needed nor used. The script deliberately
does not call `rpm-ostree`; it only runs `dnf install` and the build helper. If
the root filesystem is not that overlay, the script refuses to run.

## Safety guarantees

- **Platform guard.** Requires `uname -m == aarch64`.
- **Disposable-root guard.** Requires the root filesystem type to be `overlay`
  and the kernel command line to carry `pocketfed.liveboot=<run-id>`. It refuses
  a persistent root.
- **Run-identity guard.** `--expect-run-id` is mandatory and must match the
  liveboot run id exactly, so an install is bound to one known session. If
  `/run/pocketfed-liveboot/result.json` exists, it must report `result: pass`
  with `checks.disposable_root: true`.
- **No system transitions.** Never captures a frame, never changes a
  deployment, and never performs a power, sleep or boot transition. Only
  `dnf install` (deps, camera packages, freshly built RPMs) and local builds.
- **Bounded output.** All clones, RPM build trees and logs stay under
  `--build-root` (default `/var/tmp/pocketfed-camera-native-bootstrap`).
- `--check` performs every guard and prints the plan without changing anything;
  it is safe to run unprivileged.

The script intentionally uses an explicit Fedora package list rather than
`dnf builddep`, so a reviewer can see exactly what is installed.

## Operational steps

1. Boot the designated device into a liveboot USB-root session and read its run
   id from the UART report or `/proc/cmdline` (`pocketfed.liveboot=...`).
2. Have this repository tree available on the device, including `packages/` and
   `devices/` (a reviewable checkout or a prepared overlay).
3. Review the plan (safe, unprivileged):

   ```sh
   devices/google-sargo/camera-tests/native-bootstrap/native-bootstrap.sh \
       --check --expect-run-id RUN_ID
   ```

4. Run the bootstrap as root. It uses `$SUDO_USER` (or `--build-user`) for the
   unprivileged clone/build phase:

   ```sh
   sudo devices/google-sargo/camera-tests/native-bootstrap/native-bootstrap.sh \
       --expect-run-id RUN_ID
   ```

5. Verify and test:

   ```sh
   rpm -q libdng libmegapixels megapixels libcamera
   python3 devices/google-sargo/camera-tests/power-state.py --require-released
   # Optional camera diagnostics, once the stack is installed:
   sudo python3 devices/google-sargo/camera-tests/run-libcamera.py --output ./camera-raw-run
   ```

6. Ending the liveboot session discards everything installed here.

### Phases

1. Guards (architecture, disposable overlay root, run identity).
2. Root `dnf` phase: build dependencies, JPEG runtime dependencies and camera
   diagnostics, in one install transaction.
3. Unprivileged build phase, as the build user with 2 jobs, via
   `packages/megapixels/build-native`, in order: **libdng**, **libmegapixels**,
   **megapixels**.
4. After each library build, install its local RPMs (runtime, tools, `-devel`)
   so the next package's `pkg-config` `BuildRequires` resolve. The application
   is installed after the libraries.
5. Verify `rpm -q` and warn if libcamera is not 0.7.x.

## Dependencies

Host/device preconditions (root owns repos and network):

- PocketFed liveboot session with a writable `overlay` root and a known run id.
- `dnf` repository access (Fedora Rawhide/fc46) and general network access for
  the pinned Git clones.
- An unprivileged build user (default `$SUDO_USER`).
- `dnf`, `rpm`, `findmnt`, `python3`, `runuser`, `tee` before the root phase;
  `rpmbuild`, `rpmspec`, `git`, `gzip`, `meson` and `cc` for the build phase
  (installed by the root phase).

### Fedora packages installed

Build tooling: `rpm-build`, `redhat-rpm-config`, `systemd-rpm-macros`, `meson`,
`gcc`, `git`, `gzip`, `python3`, `pkgconf-pkg-config`, `scdoc`, `gperf`,
`desktop-file-utils`, `libappstream-glib`.

Spec `pkgconfig()` build requirements mapped to Fedora packages: `libtiff-devel`
(libdng), `libconfig-devel` (libmegapixels), and `gtk4-devel`,
`libfeedback-devel`, `zbar-devel`, `libepoxy-devel`, `libjpeg-turbo-devel`,
`pulseaudio-libs-devel`, `wayland-devel`, `libX11-devel`, `libXrandr-devel`
(megapixels).

JPEG runtime dependencies: `dcraw`, `ImageMagick`, `perl-Image-ExifTool`,
`hicolor-icon-theme`.

Camera diagnostics: `libcamera`, `libcamera-ipa`, `libcamera-tools`,
`libcamera-gstreamer`, `v4l-utils`. Fedora splits the stack, so both
`libcamera-tools` (the `cam` CLI) and `libcamera-ipa` (the software ISP) are
installed explicitly; `libcamera` 0.7.2-4.fc46 was the observed Rawhide build.
`pipewire-plugin-libcamera` is intentionally not installed here; add it only
for a PipeWire integration trial.

## Pinned sources

`packages/megapixels/build-native` verifies these exact commits after a shallow
clone and aborts on a mismatch:

| Package | Version | Commit |
| --- | --- | --- |
| libdng | 0.2.2 | `438df53ee06d9f21202e0398c90a9c3bf9e86591` |
| libmegapixels | 0.2.3 | `d50bf166972df4252d127f72f90986892f3cd901` |
| Megapixels | 2.1.0 | `5fb1f24f1aeef80ea18224ab5829fda85653a4e8` |

The helper writes the native RPMs with a `.native` distribution suffix, and
this wrapper installs them by explicit path from the build tree.

## Validation

`test-native-bootstrap.py` is a static/argument regression. It runs `bash -n`,
exercises the `--check` guards with simulated command lines and root types, and
scans the script for forbidden operations and destructive `dnf` verbs. It does
not run `dnf`, build, or touch a device:

```sh
python3 devices/google-sargo/camera-tests/native-bootstrap/test-native-bootstrap.py
```

## Limitations

- Builds require network access and a populated Fedora repository; this script
  installs nothing offline.
- It installs only the pinned camera stack and diagnostics. It does not add
  `pipewire-plugin-libcamera`, configure a desktop session, or run any capture.
- It does not validate image quality or lens behaviour; those remain device
  acceptance checks. See `../README.md` and
  `../../../../packages/megapixels/validation/prior-validation.md`.
