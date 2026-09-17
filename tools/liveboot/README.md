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

Build the liveboot boot image:

```sh
cargo run -p pocketfed-liveboot -- boot \
    --aboot out/google-sargo/aboot.img \
    --export-id 2863311530 \
    --output out/google-sargo/liveboot.img
```

It prints the command line it produced and a per-run token:

```
image: out/google-sargo/liveboot.img
bytes: 52428800
export_id: 2863311530
run_token: lb18f3c2a9d41
cmdline: <S> rw rootwait ostree=true init_on_alloc=0 module_blacklist=... root=/dev/smoo-root rootfstype=ext4 rd.smoo=1 rd.smoo.root=2863311530 pocketfed.liveboot=lb18f3c2a9d41 console=ttyMSM0,115200n8 earlycon sysrq_always_enabled=1 <E>
```

Then serve the root filesystem and boot it:

```sh
smoo-host --file out/google-sargo/pocketfed.img
fastboot boot out/google-sargo/liveboot.img
```

### Options

| Flag | Meaning |
|---|---|
| `--aboot PATH` | The image's own Android boot image. Required. |
| `--export-id ID` | smoo export id serving the root filesystem, decimal or `0x` hex. Required. |
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
dracut module to land, reach the COPR and get into an image is a long road for a
boot trial, so `--inject-tree` appends what is needed to the image's own
initramfs as a second cpio archive. The image's initrd is carried through byte
for byte — the kernel unpacks concatenated archives in order and later entries
win.

`stage-inject-tree.sh` lays out that tree: exactly what dracut's
`module-setup.sh` would have installed, plus the kernel modules the image's
initramfs leaves out, taken from the image's own module tree and decompressed
(`insmod` cannot be relied on to decompress) and loaded by a `pre-udev` hook.

```sh
tools/liveboot/stage-inject-tree.sh \
    --smoo ../smoo \
    --gadget ../smoo/target/aarch64-unknown-linux-musl/release/smoo-gadget \
    --modules /mnt/pfroot/ostree/deploy/pocketfed/deploy/<commit>.0/usr/lib/modules/<kver> \
    --out /tmp/inject-tree
```

On sargo's 7.1.2 kernel this stages `ublk_drv`, `loop`, `libcomposite` and
`usb_f_fs`; `dm_mod`, `dm_snapshot` and `configfs` are built in
(`CONFIG_BLK_DEV_DM=y`, `CONFIG_DM_SNAPSHOT=y`, `CONFIG_CONFIGFS_FS=y`) and
correctly absent.

## Getting the export id

`smoo-host` derives it from the file it serves — an FNV-1a hash over
`file:<canonical path>`, the block size and the block count. Take it from
`smoo-host`'s output for now; deriving it here so `--export-id` can be optional
is a follow-up.

## Requirements

- The device image's initramfs must contain the `smoo` dracut module
  (`smoo-dracut` installed, `dracut --add smoo`). Without it the phone brings up
  no gadget and the boot stalls waiting for a root device.
- `vendor/abl-exorcist` currently tracks the `claude/bootimg-api` branch for
  `bootimg::{repack, verify}`. Re-pin it to `main` once
  samcday/abl-exorcist#3 merges.
