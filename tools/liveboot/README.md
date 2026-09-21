# PocketFed liveboot through fastboop

This is the first slice of the replacement for [the v2 liveboot tool](https://github.com/samcday/pocketfed/pull/73).
It consumes separate root image, kernel, **prepared initrd**, and DTB inputs.
The `fastboop-bootpro`, `fastboop-core` and `fastboop-environment-std` crates
compile the profile, construct the Android payload, perform fastboot RAM boot,
and serve the read-only root through smoo. No external fastboop or smoo-host
executable is involved.

PocketFed owns the image's OSTree arguments and preparation of its dracut initrd.
Fastboop owns device geometry, kernel encoding, payload assembly, root export
identity, USB handoff and root serving. This tool neither parses nor repacks an
existing Android boot image. It does not flash partitions.

## Current boundary

- `bundle` and `image` work without USB, mounting, or root privileges.
- `boot` uses the same fastboop preparation path, then boots and serves the root.
  [DB410c direct-U-Boot validation](DB410C.md) reached the visible greeter and
  verified disposable writes. Other device paths still need hardware validation.
- **Sargo consumes draft [fastboop #139](https://github.com/samcday/fastboop/pull/139)**
  for supplied-initrd shim composition. Pass `--shim` with the raw device shim;
  `image` and `boot` refuse Sargo bundles without it. Other shim-requiring devices
  must be identified with `--requires-shim`. This dependency is not yet merged or
  hardware-proven.
- Input extraction from an image and smoo/dracut initrd construction are not
  implemented in this first patch. An existing prepared initrd is required.
  The image recipes in [#75](https://github.com/samcday/pocketfed/pull/75) and its
  device follow-ups remain independent work.

## Build

Linux host requirements: Rust 1.91 or newer, a C compiler, pkg-config, libusb
development headers, and `mkfs.ext4` (e2fsprogs). The host tests also need Python 3
and `dtc` (device-tree-compiler), plus liblz4 for independent ABLX payload decoding.

```sh
cd tools/liveboot
cargo build --locked
cargo fmt --check
cargo clippy --locked --all-targets -- -D warnings
python3 tests/host.py
```

The draft pins fastboop Git revision
`1e6d64b3c375d46f2029122902f4564d36f5498b` (supplied-initrd shim support), with
explicit gibblox Git patches in this consumer's manifest. Cargo does not inherit
a Git dependency's workspace patches. `Cargo.lock` also fixes the transitive Git
and registry dependency graph; smoo uses the published `0.0.2-rc.7` crates. Use
`--locked`. Switch to released crates in a separate update once the upstream
release graph is usable.

For real multi-gigabyte images, build with `cargo build --release --locked` and
use `target/release/pocketfed-liveboot`. Compiling the profile hashes the entire
root image; an unoptimized build is substantially slower.

## Inputs and runtime contract

Prepare these inputs for the same device and image deployment:

1. A raw ext4 root image, such as `pfroot.img`.
2. Its kernel and DTB, as separate files.
3. Its dracut initramfs with smoo's `90smoo` module, the gadget binary, matching
   kernel modules (USB gadget, ublk and dm-snapshot/brd), and userspace COW tools.
   The gadget services must survive switch-root. An ordinary distribution
   initrd without this preparation cannot consume the exported root.
4. A fastboop DevPro YAML matching the **actual bootloader**, including Android
   header geometry and kernel encoding. A stock DB410c profile is not a profile
   for DB410c running Pocketboot. Start with the profiles at the pinned
   [fastboop revision](https://github.com/samcday/fastboop/tree/1e6d64b3c375d46f2029122902f4564d36f5498b/devprofiles.d)
   and use the profile appropriate to the bootloader in use.
5. A text file with the image's kernel arguments: the actual `ostree=...` path,
   `rootfstype=ext4`, `rd.smoo.cow.size=...`, and device/debug arguments as needed.
   There is no universal OSTree path or COW size; take these from the image and
   device recipe. Do not carry over an installed `root=LABEL=...` or a previous
   run's `rd.smoo.root=...` export ID.

Fastboop sets `root=/dev/smoo-root`, `rd.smoo=1`, `rd.smoo.force_root=1`,
`rd.smoo.cow=1`, the actual root export ID, and `rd.smoo.mimic_fastboot`.
Conflicting arguments fail before boot. The default gadget interface mode is
ordinary smoo (`--impersonate-fastboot=false`), matching the existing dracut
recipe. Pass `--impersonate-fastboot=true` only for an initrd prepared for that
interface mode. Filesystem writes go to the guest's disposable COW layer.

## Prepare, inspect, boot

These commands assume the five inputs above already exist in the current
directory. `TARGET_SERIAL` is the target's **fastboot `getvar serialno`** value.

```sh
target/debug/pocketfed-liveboot bundle \
  --root-image pfroot.img \
  --kernel Image.gz \
  --initrd liveboot-initrd.img \
  --dtb board.dtb \
  --device-profile device.yaml \
  --serial "$TARGET_SERIAL" \
  --cmdline-file cmdline.txt \
  --out trial

# Host-only preparation; does not connect to USB.
target/debug/pocketfed-liveboot image trial --output trial.img

# With the target already in fastboot and USB permissions configured:
target/debug/pocketfed-liveboot boot trial --wait 30
```

For Sargo, add `--shim /path/to/raw-device-shim.bin` to `bundle`. Use the
DevPro from the pinned revision, including its `0x04000000` ramdisk offset.
Fastboop encodes the shim in the Android kernel section and places the real
kernel and unchanged initrd in an `ABLXRD1` ramdisk; it owns the `<S>`/`<E>`
command-line markers too. Do not supply marker strings in the command line.
The raw shim is copied into the bundle as `shim.bin`.

`bundle` copies the three small boot inputs into `boot-artifacts.ext4` and
compiles a fastboop `boot: initrd` channel. `profile.yaml`, `device.yaml` and
`bundle.json` record the selected inputs and device; `channel.fb` is the binary
channel actually consumed. The exact serial probe is added to the supplied
device profile. A local DevPro that would shadow it is rejected.

The root image is referenced by canonical absolute path and opened read-only,
not copied. The bundle's artifact references are also absolute. Keep the root
and bundle in place and unchanged for the trial; regenerate after moving them
or changing inputs. Treat bundles as local artifacts: they contain host paths
and the device serial. Existing output directories/files are refused. A failed
`bundle` may leave an incomplete new directory; use a new path on retry.

Keep the boot process running until the guest has shut down, then press Ctrl-C.
Stopping it removes the guest's backing storage. The serial probe constrains the
fastboot handoff. At this pinned revision, fastboop's subsequent smoo discovery
uses interface descriptors rather than a serial filter: use one available smoo
target per host during trials.

## Validation and next increments

`tests/host.py` builds real ext4 fixtures and runs the compiled consumer through
fastboop's profile resolver and supplied-initrd preparation. It independently
checks Android v2 geometry, kernel encoding, unchanged initrd/DTB contents,
and ABLX shim/container placement with independent LZ4 decompression,
generated root/COW arguments, and the unchanged source root. It also checks
output refusal, conflicting arguments, DevPro shadowing and the shim gate.
The synthetic kernel and initrd are deliberately not bootable; this is host
integration coverage, not hardware proof.

Keep subsequent work separate: image/initrd input preparation, acceptance of the upstream shim dependency,
a controlled device trial, and the registry dependency switch.
The first hardware trial should establish root handoff and disposable writes
before device-specific desktop, display, or modem work is added.
