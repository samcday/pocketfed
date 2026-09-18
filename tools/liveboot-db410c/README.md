# liveboot-db410c

Host-side tooling for **liveboot v2** on the DragonBoard 410c (and similar
boards). Liveboot boots the board through Pocketboot's fastboot kexec loader:
there is no ABL/ABLX shim and the boot image is a plain Android v2 image. The
served root filesystem is a PocketFed Phosh OSTree image, exported over USB by
`smoo-host` and pinned to a product id, and the kernel is the board's own
kernel, supplied as a build output directory outside this repository. A dracut
initrd is built *inside* the served root image so it carries that image's
userspace plus the board kernel's modules, then wrapped into the Android v2 boot
image.

## Contents

- `build-initrd.sh` — generalised, flag-driven build. Loop-mounts the root image
  read-only, runs dracut in a `podman --rootfs <deployment>:O` container,
  strips the display module closure, post-processes the initrd, and calls
  `mkbootimg`.
- `dracut/95pocketfed-liveboot/` — the liveboot-only dracut module that enables
  root autologin on the serial console (see its README).

## Building

```
tools/liveboot-db410c/build-initrd.sh \
  --root-image   <pfroot.img> \
  --kernel-bundle <dir with Image.gz, qcom/apq8016-sbc.dtb, modules/lib/modules/<kver>> \
  --smoo-dracut  <smoo checkout containing modules.d/90smoo> \
  --smoo-gadget  <aarch64 smoo-gadget binary> \
  --out          <out dir> \
  --export-id    <smoo export id>
```

`--export-id` is the id `smoo-host` prints for the served image and becomes
`rd.smoo.root=`. Common options: `--deployment <hash>` (auto-detected when the
image has a single deployment), `--run-token`, `--product-id` (default
`0xBEE1`), `--cow-size`, `--edid-override`, `--autologin-root` and `--zram` (both on by default),
`--initrd-root-password-file`, `--drop-dm-udev-rules` and `--dry-run`. Run
`build-initrd.sh --help` for the full list. `--dry-run` prints the resolved plan
without mounting or building anything.

Outputs go to `--out`: `initrd-<run-token>.img`, `liveboot-<run-token>.img`,
`cmdline.txt` and build logs.

## Running liveboot

1. **Cold-boot the board into the lab Pocketboot resident** (its fastboot kexec
   loader). This is the loader that accepts the Android v2 image below.
2. **Serve the root image** on the host. `smoo-host` must be pinned to the same
   product id that the kernel command line advertises
   (`rd.smoo.product=`, `--product-id`); it prints the export id, which must
   match the `--export-id` used at build time (rebuild if it does not):

   ```
   smoo-host --product-id 0xBEE1 --file <pfroot.img>
   ```

3. **Boot the image** over fastboot:

   ```
   fastboot -s <serial> boot <out>/liveboot-<run-token>.img
   ```

4. **Watch the serial console.** The initrd brings up the USB gadget, waits for
   the export, snapshots it into a RAM copy-on-write root at `/dev/smoo-root`,
   and pivots into the OSTree deployment. On success `serial-getty@ttyMSM0`
   autologins root on the serial console.

### Host udev rule for the pinned product id

`smoo-host` opens the gadget's USB device, so on hosts that run it as a normal
user the device needs a permissive udev rule. The gadget uses vendor id `0xDEAD`
and the pinned product id (default product `0xBEE1`, i.e. `bee1`); if you build
with another `--product-id`, replace `bee1` below with that value in lower-case
hex, or the rule will not match the gadget:

```
# /etc/udev/rules.d/99-smoo-gadget.rules
SUBSYSTEM=="usb", ATTR{idVendor}=="dead", ATTR{idProduct}=="bee1", MODE="0666"
```

```
sudo udevadm control --reload-rules
sudo udevadm trigger
```

If the gadget is built with a non-default `--vendor-id`, match that vendor
instead.

## Known limits

- **1 GB RAM.** The served root is the *other* board's userspace, so it cannot
  load this kernel's modules. The liveboot dracut module therefore loads zram
  (+lz4) from the initrd before udev; the served root's own zram-generator then
  makes swap after switch-root. Without it (`--no-zram`) the RAM copy-on-write
  layer (`--cow-size`) is the only headroom and the greeter gets OOM-killed.
- **EDID override may be required.** Sinks that do not report HPD get no mode
  from the binder; the default `drm.edid_firmware=HDMI-A-1:edid/1280x720.bin`
  forces 720p. Pass `--edid-override none` for sinks that do advertise HPD.
- **`enforcing=0`.** The command line disables SELinux until smoo's SELinux
  module ships (see samcday/smoo#59). Do not flip it on before then.
- **The kernel bundle is out of scope.** This tooling takes a directory with
  `Image.gz`, the board DTB and the matching module tree; producing that bundle
  is a separate build.

## References

- [samcday/pocketfed#74](https://github.com/samcday/pocketfed/pull/74) — liveboot v2 tooling
- [samcday/smoo#59](https://github.com/samcday/smoo/pull/59) — smoo SELinux module and the dm udev-rule fix
