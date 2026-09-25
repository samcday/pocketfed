## build

On Linux, install Rust 1.91+, a C compiler, pkg-config, libusb development headers and e2fsprogs; tests also need device-tree-compiler. From `tools/liveboot`, run `cargo build --release --locked` and `cargo test --locked`. Fastboop and gibblox are temporarily pinned Git dependencies; keep the lockfile. Release builds make hashing large root images much faster.

## use

Supply a raw ext4 root, its kernel and DTB, and a prepared smoo-aware dracut initrd with matching gadget/ublk/COW modules, tools and services that survive switch-root. Input extraction and initrd preparation are still separate work. Choose a profile matching the bootloader: `profiles/uboot-db410c.yaml` or `profiles/google-sargo-ablx-v2.yaml` cover the validated devices. Sargo also requires `--shim /path/to/raw-device-shim.bin`.

Put the deployment's `ostree=...`, `rootfstype=ext4`, `rd.smoo.cow.size=...` and any device arguments in `cmdline.txt`. Fastboop supplies the root/export selection, COW enablement and shim markers; omit installed-root arguments, old export IDs and `<S>`/`<E>`. Set `TARGET_SERIAL` to fastboot's `getvar serialno` value. The example uses ordinary smoo interfaces; use `--impersonate-fastboot=true` only if the initrd uses fastboot-style descriptors.

For a Sargo image, whose usb-signaller policy selects `developer_mode`, `cmdline.txt` looks like this (fill in the deployment path and COW size):

```text
ostree=/ostree/boot.1/fedora/<checksum>/0 rootfstype=ext4 rd.smoo.cow.size=<size> rd.smoo.functions=ncm.usb0
```

Bundle for Sargo with its profile and the shim:

```sh
target/release/pocketfed-liveboot bundle \
  --root-image pfroot.img --kernel Image.gz --initrd liveboot-initrd.img \
  --dtb board.dtb --device-profile profiles/google-sargo-ablx-v2.yaml \
  --shim /path/to/raw-device-shim.bin \
  --serial "$TARGET_SERIAL" --cmdline-file cmdline.txt --out trial
```

For the DB410c, bundle with its profile and no shim:

```sh
target/release/pocketfed-liveboot bundle \
  --root-image pfroot.img --kernel Image.gz --initrd liveboot-initrd.img \
  --dtb board.dtb --device-profile profiles/uboot-db410c.yaml \
  --serial "$TARGET_SERIAL" --cmdline-file cmdline.txt --out trial
```

Then, for either device:

```sh
target/release/pocketfed-liveboot image trial --output trial.img
target/release/pocketfed-liveboot boot trial --wait 30
```

`bundle` packages boot inputs and an inspectable fastboop channel; `image` constructs the payload without USB. The root is referenced read-only by absolute path, and guest writes use disposable RAM COW. Keep the root and bundle in place and unchanged; regenerate after changing inputs. Existing outputs are refused, and failed bundling may leave an incomplete directory. Bundles contain local paths and the device serial.

For `boot`, put the target in fastboot with host USB permissions configured and keep the process running until the guest shuts down. At this pinned revision, runtime smoo discovery matches interfaces rather than serials, so connect only one available smoo target. Sargo and DB410c reached visible greeters and passed disposable-write checks; reconnects, GPU stability and enforcing SELinux remain unvalidated.

## USB gadget handover

This describes the smoo dracut gadget layout and usb-signaller's adoption of it, both still in draft review. The image must carry PocketFed's patched usb-signaller: stock 0.4.2 with `default_mode` set replaces the bound gadget, which here carries the root filesystem, and the guest stalls.

- The initrd creates `/sys/kernel/config/usb_gadget/smoo` with device class `EF/02/01` and links `ffs.smoo` first into `configs/c.1`, so smoo stays interface 0. The serial number comes from `rd.smoo.serial` and defaults to `0001`.
- `rd.smoo.functions=ncm.usb0` links an NCM function into the same config before the single UDC bind. usb-signaller then finds its developer mode already composed and does not re-enumerate. Without it, or when the image selects another default mode, usb-signaller recomposes the gadget with one visible re-enumeration, which is harmless.
- The initrd writes `/run/usb-signaller/usb-signaller.toml.d/50-smoo.toml`, which declares the gadget, pins `ffs.smoo` and asks usb-signaller to adopt the gadget rather than replace it. The image carries no smoo configuration; its `foreign_gadgets = "preserve"` keeps the root safe even if that file is lost.
- The fastboop pin (`1e6d64b3`) matches smoo by interface and passes no serial. Newer fastboop requires `--smoo-serial` for supplied initrds; once the pin moves past `1e6d64b3`, pass `--smoo-serial` equal to `rd.smoo.serial` (default `0001`).
- The Sargo Type-C host helper refuses to swap data roles on a liveboot (`rd.smoo` on the cmdline, or `/run/smoo/smoo-gadget.pid` present), because the swap removes the UDC.
