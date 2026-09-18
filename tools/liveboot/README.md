# pocketfed-liveboot

Boots a PocketFed device image over USB without flashing it.

The phone runs **the image's own kernel and its own dracut initramfs** — the
`aboot.img` the image builder already produced, with the abl-exorcist shim
already in the kernel section. The only thing liveboot changes is the kernel
command line. Its root filesystem is served from the laptop over
[smoo](https://github.com/samcday/smoo) and layered with a RAM-backed
copy-on-write device, so the image on disk is never written to and every boot
starts clean.

That is the whole point of the design: what boots is what would have booted from
eMMC, so a liveboot run is evidence about the image rather than about the boot
harness.

## Usage

Three things on the laptop: the image builder's output for the device, a smoo
checkout with an aarch64 `smoo-gadget`, and `smoo-host`.

```sh
just fastboot-from-image ghcr.io/samcday/pocketfed-phosh-google-sargo:rawhide   # out/google-sargo/{boot,pfroot}.img
(cd ../smoo && cargo gadget-musl-aarch64 && cargo build --release -p smoo-host-cli)
```

Then build the liveboot image, serve the root and boot the phone (in fastboot):

```sh
tools/liveboot/build.sh --out out/google-sargo --smoo ../smoo
../smoo/target/release/smoo-host --file out/google-sargo/pfroot.img
fastboot -s 99NAY1AZG1 boot out/google-sargo/liveboot.img
```

`build.sh` reads the served image with `debugfs` (no mount, no root) to take the
kernel modules, `dmsetup` and `libdevmapper` the image's initramfs lacks,
stages them with the smoo dracut module into a tree, and appends that tree to
the image's own initramfs. Nothing is flashed: a power cycle restores whatever
was installed. The console is on the device's UART (`tio` at 115200); a run
that fails in the initrd reboots on its own after `rd.timeout`.

Proven on test-sargo on 2026-09-18: the stock rawhide image reached the phrog
greeter over the served root, with writes going to a 2 G RAM overlay.

### The builder on its own

```sh
cargo run --release --manifest-path tools/liveboot/Cargo.toml -- boot \
    --aboot out/google-sargo/boot.img \
    --root-image out/google-sargo/pfroot.img \
    --inject-tree out/google-sargo/liveboot-work/inject-tree \
    --append enforcing=0 \
    --output out/google-sargo/liveboot.img
```

It prints the command line it produced and a per-run token:

```
image: out/google-sargo/liveboot.img
bytes: 58720256
export_id: 2341277800
run_token: lb18d6456933e512d0
cmdline: <S> rw rootwait ostree=true init_on_alloc=0 module_blacklist=... root=/dev/smoo-root rootfstype=ext4 rd.smoo=1 rd.smoo.root=2341277800 rd.smoo.cow.size=2G pocketfed.liveboot=lb18d6456933e512d0 console=ttyMSM0,115200n8 earlycon sysrq_always_enabled=1 enforcing=0 <E>
```

### Options

| Flag | Meaning |
|---|---|
| `--aboot PATH` | The image's own Android boot image. Required. |
| `--root-image PATH` | The file `smoo-host --file` will serve; the export id is derived from it. One of this or `--export-id` is required. |
| `--export-id ID` | smoo export id serving the root filesystem, decimal or `0x` hex, for roots not served from a local file. |
| `--output PATH` | Where to write the liveboot image. Required. |
| `--run-token TOKEN` | Override the generated per-run token. |
| `--console SPEC` | Serial console, default `ttyMSM0,115200n8`. |
| `--cow-size SIZE` | Copy-on-write ceiling, e.g. `2G`. Defaults to the dracut module's `1G`. |
| `--append ARG` | Extra kernel argument, repeatable. Appended last. |

## What it does to the command line

- **Forces `root=/dev/smoo-root`.** PocketFed labels both the served image and
  the phone's internal eMMC root `pfroot`, so leaving the image's own
  `root=LABEL=pfroot` in place risks silently booting the installed system. That
  failure looks like success, which makes it the one worth engineering against.
- **Adds `rd.smoo=1 rd.smoo.root=<id>`** so the smoo dracut module brings up the
  gadget and picks the right export.
- **Adds `pocketfed.liveboot=<run-token>`**, unique per run. The UART harness
  gates on it, so a stale console capture can never be read as this run's output.
- **Adds `console=`, `earlycon` and `sysrq_always_enabled=1`**, and drops
  `quiet`, `rhgb` and `plymouth.ignore-serial-consoles`, because a liveboot run
  is diagnosed over the UART and a splash hides the console.
- **Keeps everything else** in its original order.

The image is verified before and after: a template that already fails its own
integrity checks is rejected up front, so a bad boot is never blamed on liveboot.

## Getting the smoo module onto the device

A device image's initramfs does not carry `smoo-gadget`, and sargo's
`dracut.conf` is `hostonly_mode=strict` with none of the datapath drivers in
`force_drivers`, so it has no ublk or gadget modules either. Waiting for the
smoo dracut module to reach the image through the COPR would put a whole
release train between a change and a boot trial, so `--inject-tree` appends
what is needed to the image's own initramfs as a second cpio archive. The
image's initrd is kept byte for byte: the kernel unpacks concatenated archives
in order and later entries win.

`stage-inject-tree.sh` lays out that tree: exactly what dracut's
`module-setup.sh` would have installed, plus the kernel modules the image's
initramfs leaves out, resolved through the image's own `modules.dep`,
decompressed (`insmod` cannot be relied on to decompress) and loaded by a
`pre-udev` hook in dependency order. `build.sh` drives it from the served
image; by hand it is:

```sh
tools/liveboot/stage-inject-tree.sh \
    --smoo ../smoo \
    --gadget ../smoo/target/aarch64-unknown-linux-musl/release/smoo-gadget \
    --modules /path/to/usr/lib/modules/<kver> \
    --extra /path/to/extra \
    --out /tmp/inject-tree
```

`--extra` is a directory copied onto the tree as-is, for binaries the image's
initramfs does not carry: on sargo that is `usr/sbin/dmsetup` and
`usr/lib64/libdevmapper.so.1.02`, taken from the same deployment. The COW
device is a `brd` RAM disk, so no loop device or sparse-file tooling is needed.

On sargo's 7.1.2 kernel this stages `ulpi`, `udc-core`, `dwc3`, `dwc3-qcom`,
`libcomposite`, `usb_f_fs` and `ublk_drv` (plus `brd`, which the root setup
loads itself with its size); `dm_mod`, `dm_snapshot` and `configfs` are built
in and correctly absent.

## Getting the export id

`smoo-host` derives it from what it serves: for a file, FNV-1a over
`file:<canonical path>`, the block size (512) and the block count. `--root-image`
reproduces that, so the id never has to be copied by hand; `--export-id` is for
roots `smoo-host` serves some other way (`--http`, `--device`).

## Requirements

- `debugfs` (e2fsprogs), `xz`, `file` and an aarch64-capable `strip`
  (`aarch64-linux-gnu-strip` or `llvm-strip`, optional) on the laptop.
- SELinux on the served system has to be permissive (`enforcing=0`, which
  `build.sh` adds) until the image carries smoo's policy module: the gadget
  runs as `kernel_t` and its ublk io_uring commands are otherwise denied once
  the served system loads its policy, stalling root I/O right after
  switch-root.
- The image's initramfs does not need the smoo dracut module; `--inject-tree`
  supplies it. Once the image ships it, the injection becomes optional.
- `vendor/abl-exorcist` tracks the `claude/bootimg-api` branch for
  `bootimg::{repack, verify}`. Re-pin it to `main` once
  samcday/abl-exorcist#3 merges.
