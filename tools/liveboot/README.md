## build

On Linux, install Rust 1.91+, a C compiler, pkg-config, libusb development headers and e2fsprogs; tests also need device-tree-compiler. From `tools/liveboot`, run `cargo build --release --locked` and `cargo test --locked`. Fastboop and gibblox are temporarily pinned Git dependencies; keep the lockfile. Release builds make hashing large root images much faster.

## use

Supply a raw ext4 root, its kernel and DTB, and a prepared smoo-aware dracut initrd with matching gadget/ublk/COW modules, tools and services that survive switch-root. Input extraction and initrd preparation are still separate work. Choose a profile matching the bootloader: `profiles/uboot-db410c.yaml` or `profiles/google-sargo-ablx-v2.yaml` cover the validated devices. Sargo also requires `--shim /path/to/raw-device-shim.bin`.

Put the deployment's `ostree=...`, `rootfstype=ext4`, `rd.smoo.cow.size=...` and any device arguments in `cmdline.txt`. Fastboop supplies the root/export selection, COW enablement and shim markers; omit installed-root arguments, old export IDs and `<S>`/`<E>`. Set `TARGET_SERIAL` to fastboot's `getvar serialno` value. The example uses ordinary smoo interfaces; use `--impersonate-fastboot=true` only if the initrd uses fastboot-style descriptors.

```sh
target/release/pocketfed-liveboot bundle \
  --root-image pfroot.img --kernel Image.gz --initrd liveboot-initrd.img \
  --dtb board.dtb --device-profile profiles/uboot-db410c.yaml \
  --serial "$TARGET_SERIAL" --cmdline-file cmdline.txt --out trial
target/release/pocketfed-liveboot image trial --output trial.img
target/release/pocketfed-liveboot boot trial --wait 30
```

`bundle` packages boot inputs and an inspectable fastboop channel; `image` constructs the payload without USB. The root is referenced read-only by absolute path, and guest writes use disposable RAM COW. Keep the root and bundle in place and unchanged; regenerate after changing inputs. Existing outputs are refused, and failed bundling may leave an incomplete directory. Bundles contain local paths and the device serial.

To provision the guest with [Ignition](../../base/ignition.md), build the initrd with `--add pocketfed-ignition` and pass `--ignition config.ign` to `bundle`. The config is appended to the initrd as `/etc/ignition/user.ign` and `ignition.firstboot ignition.platform.id=metal` is added to the command line, so leave `ignition.*` arguments out of `cmdline.txt`. Configs must not fetch remote resources or change kernel arguments or storage layout. The bundle directory is made private; the bundle, images made from it and fastboop's cache then contain the config. Every boot of the bundle is a first boot: the root's changes live in the disposable COW.

`bundle` refuses command lines that could exceed 511 bytes, since U-Boot and Pocketboot read only the first Android header field; `--allow-long-cmdline` overrides this for bootloaders that read both. Headless Ignition trials can drop display arguments and shorten markers to make room.

For `boot`, put the target in fastboot with host USB permissions configured and keep the process running until the guest shuts down. At this pinned revision, runtime smoo discovery matches interfaces rather than serials, so connect only one available smoo target. Sargo and DB410c reached visible greeters and passed disposable-write checks; reconnects, GPU stability and enforcing SELinux remain unvalidated.
