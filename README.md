# pocketfed

PocketFed is a small Fedora Rawhide base for pocket-computer experiments.

The first artifact is a kernel-included, headless base rootfs built with mkosi.
The top-level `Justfile` turns that rootfs into local development artifacts:

- `base/mkosi.output/rootfs/` for direct inspection and derivation.
- `base/mkosi.output/rootfs.ero` for `kboop` live-boot kernel bring-up.
- `base/mkosi.output/pocketfed-base.oci` as a bootc-shaped OCI layout.
- `base/mkosi.output/rootfs.ostree.ero` as a deployed OSTree sysroot EROFS
  for fastboop-style boot flows.
- `base/mkosi.output/fajita/images/` as static fajita userdata and boot
  images for `fastboot` bring-up.

## Build

```sh
just base
```

Useful smaller steps:

```sh
just base-summary
just kernel-build
just kernel-stage
just base-rootfs
just base-erofs
just base-bootc-rootfs
just base-oci
just base-ostree-erofs
just base-fajita-images
```

## Fastboop Iteration

The fastest device loop is `just base-erofs`. It builds the unprofiled base
rootfs and packs it as `base/mkosi.output/rootfs.ero`, skipping bootc lint,
OCI compose, OSTree deployment, dracut initrd generation, and aboot marker
generation.

Boot the resulting EROFS from the fastboop checkout:

```sh
cargo run --release --bin fastboop -- boot /var/home/sam/src/pocketfed/base/mkosi.output/rootfs.ero --device-profile oneplus-fajita --cmdline 'sysrq_always_enabled=1'
```

Use `just base-bootc-rootfs` or any target depending on `base-oci` when you
need the bootc/OSTree branch. Those targets build mkosi with the `bootc`
profile, which re-enables the bootc-specific postinstall and postoutput work.

Show configurable paths and image refs:

```sh
just vars
```

The local OCI ref defaults to the on-disk OCI layout. Override `PF_OCI_OUTPUT`
when inspecting or converting a different image ref:

```sh
PF_OCI_OUTPUT=docker://registry.example/pocketfed/base:rawhide just base-ostree-erofs
```

## Kernel

PocketFed's kernel is built as part of the image workflow from a local Linux
checkout. By default, `just kernel-fetch` prepares the ignored `.linux-src/`
checkout from the pinned `samcday/linux` integration branch:

```sh
just kernel-fetch
```

The default `just base` path depends on `just kernel-stage`, which cross-builds
the kernel on the host and stages it into `base/mkosi.local/kernel` for mkosi to
copy into the rootfs. PocketFed-owned config fragments live in `kernel/configs/`;
the kernel source tree only carries kernel code. No kernel RPM is built or
installed.

Useful kernel-only steps:

```sh
just kernel-build
just kernel-stage
just kernel-clean
```

Useful overrides:

```sh
PF_KERNEL_JOBS=16 just kernel-build
PF_KERNEL_TREE=/path/to/linux PF_KERNEL_BUILD_DIR=/path/to/build just kernel-stage
PF_KERNEL_REF=pocketfed/main PF_KERNEL_COMMIT= just kernel-fetch
PF_KERNEL_IMAGE=Image.gz just base
```

## Android Boot / OSTree Bring-Up

The base image carries enough Android boot metadata to make OSTree select its
`aboot` integration path:

- `/usr/lib/modules/$kver/aboot.img` is created as an empty mode marker.
- `/usr/lib/ostree-boot/aboot.cfg` carries fajita-compatible boot image layout
  values and requests late-bound DTB selection.
- `/usr/bin/aboot-deploy` implements the OSTree hook contract for initial
  installs and no-flash boot image generation.
- `/usr/bin/pocketfed-build-aboot-img` is a helper for generating a `boot.img`
  from an installed sysroot.

For fajita bring-up, avoid `bootc install` and generate static fastboot
artifacts offline from the local OCI layout:

```sh
just base-fajita-images
```

This writes:

- `base/mkosi.output/fajita/images/pocketfed-fajita-userdata.raw`
- `base/mkosi.output/fajita/images/pocketfed-fajita-userdata.simg`
- `base/mkosi.output/fajita/images/pocketfed-fajita-boot.img`
- `base/mkosi.output/fajita/metadata.json`
- `base/mkosi.output/fajita/flash.sh`

Flash userdata and boot the generated Android boot image:

```sh
fastboot flash userdata base/mkosi.output/fajita/images/pocketfed-fajita-userdata.simg
fastboot boot base/mkosi.output/fajita/images/pocketfed-fajita-boot.img
```

Or run the generated helper:

```sh
base/mkosi.output/fajita/flash.sh
```

For `oneplus,fajita`, `just base-fajita-images` enables `droid-exorcist` by
default. The Android `boot.img` kernel payload is prepared with
`droid-exorcist-assembler`, and the intended runtime command line is wrapped in
literal `<S>` and `<E>` markers so the shim can preserve it while filtering
ABL-injected junk such as `root=dm-1`. Override this with
`PF_DROID_EXORCIST=off` or pass explicit paths with
`PF_DROID_EXORCIST_ASSEMBLER=` and `PF_DROID_EXORCIST_SHIM=`.

The preserved runtime command line is short by default:

```text
root=LABEL=pfroot rw rootwait rootfstype=ext4 ostree=/ostree/root.a
```

The real `androidboot.*` tokens provided by ABL are preserved outside the
markers by `droid-exorcist`; if `androidboot.slot_suffix` is present, OSTree's
aboot path prefers that over the fallback `ostree=/ostree/root.a` target.

The offline OSTree deployment still carries the full BLS metadata and creates
both `/ostree/root.a` and `/ostree/root.b` in the userdata image. Runtime
partition flashing remains gated behind `POCKETFED_ABOOT_FLASH=1` and still
expects `aboot-gptctl`; use generated no-flash artifacts until A/B switching is
proven on-device.

Composefs is intentionally disabled in `ostree-prepare-root` for this bring-up
path while the aboot boot flow is stabilized. The physical sysroot remains
configured read-only through `/usr/lib/ostree/prepare-root.conf`.

## Base Contract

The `base/` mkosi config intentionally stays boring:

- Fedora Rawhide only.
- arm64 only for now.
- curated kernel from the pinned local checkout, staged directly into the image
  rather than packaged as an RPM.
- no mkosi-managed initramfs generation in the fast path; the `bootc` mkosi
  profile owns the dracut policy needed for OSTree boot.
- no bootupd or generic bootloader payload.
- Android boot image metadata for OSTree aboot experiments.
- no Linux firmware payloads; firmware is extracted from device partitions by
  `blob-wrangler` at boot.
- Qualcomm firmware-access services are enabled, with dependent modules and
  services deferred until `blob-wrangler.service` succeeds.
- no desktop environment.
- bootc/OSTree userspace is present, but bootc/OSTree artifacts are generated
  only through the `bootc` mkosi profile.

Desktop and device-specific work should layer on top of this base instead of
being folded into it.
