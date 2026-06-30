# pocketfed

PocketFed is a small Fedora Rawhide base for pocket-computer experiments.

The first artifact is a kernel-included, headless base rootfs built with mkosi.
The top-level `Justfile` turns that rootfs into local development artifacts:

- `base/mkosi.output/rootfs/` for direct inspection and derivation.
- `base/mkosi.output/rootfs.ero` for `kboop` live-boot kernel bring-up.
- `base/mkosi.output/pocketfed-base.oci` as a bootc-shaped OCI layout.
- `base/mkosi.output/rootfs.ostree.ero` as a deployed OSTree sysroot EROFS
  for fastboop-style boot flows.

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
just base-ostree-erofs
```

Show configurable paths and image refs:

```sh
just vars
```

The local OCI ref defaults to the on-disk OCI layout. Override `PF_OCI_OUTPUT`
when inspecting or converting a different image ref:

```sh
PF_OCI_OUTPUT=docker://registry.example/pocketfed/base:rawhide just base-ostree-erofs
```

## Base Contract

The `base/` mkosi config intentionally stays boring:

- Fedora Rawhide only.
- arm64 only for now.
- kernel package from the `samcday/pocketfed` COPR.
- no initramfs generation.
- no bootloader or bootupd payload.
- no desktop environment.
- bootc/OSTree userspace and rootfs layout only.

Desktop and device-specific work should layer on top of this base instead of
being folded into it.
