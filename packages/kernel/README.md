# PocketFed Kernel Package

This package builds the downstream PocketFed kernel branch into a COPR RPM named
`pocketfed-kernel` for image composition. The package still provides the usual
`kernel`, `kernel-core`, `kernel-modules`, and related capabilities, but images
request `pocketfed-kernel` so Fedora's repositories cannot satisfy the package
request with their own kernel build.

The kernel config fragments are intentionally not stored in this package
directory. They live in the downstream kernel tree under `pocketfed-configs/` so
config policy changes stay tied to the Kconfig symbols and device trees they
depend on.

When the downstream kernel tree changes:

1. Commit and push the kernel tree changes to `samcday/linux:pocketfed/main`.
2. Update `%global commit` in `kernel.spec` to the pushed commit.
3. Rebuild the COPR package.

The RPM deliberately does not run `dracut` or `kernel-install` in scriptlets.
Device images own initramfs and Android boot image generation.

Build an SRPM locally from this directory with:

```sh
make -f ../.copr/Makefile srpm outdir="$PWD"
```
