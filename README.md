# pocketfed

PocketFed is a small Fedora Rawhide base for pocket-computer experiments.

The first artifact is a kernel-less, headless base rootfs built with mkosi. The
top-level `Justfile` turns that rootfs into local development artifacts:

- `base/mkosi.output/rootfs/` for direct inspection and derivation.
- `base/mkosi.output/rootfs.ero` for `kboop` live-boot kernel bring-up.
- a bootc-shaped OCI image, defaulting to `containers-storage:localhost/pocketfed/base:rawhide`.

## Build

```sh
just base
```

Useful smaller steps:

```sh
just base-summary
just base-rootfs
just base-erofs
just base-oci
```

Show configurable paths and image refs:

```sh
just vars
```

The OCI output defaults to containers storage. Override it with `PF_OCI_OUTPUT`:

```sh
PF_OCI_OUTPUT=oci:base/mkosi.output/oci just base-oci
```

## Base Contract

The `base/` mkosi config intentionally stays boring:

- Fedora Rawhide only.
- arm64 only for now.
- no kernel package.
- no initramfs generation.
- no bootloader or bootupd payload.
- no desktop environment.
- bootc/OSTree userspace and rootfs layout only.

Kernel and device-specific work should layer on top of this base instead of
being folded into it.
