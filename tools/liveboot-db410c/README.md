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
- `gen-edid.py` — writes the 1280x720@60 EDID block the builder ships as the
  `drm.edid_firmware` override (generated so the timings stay reviewable).
- `dracut/95pocketfed-liveboot/` — the liveboot-only dracut module: root
  autologin on the serial console, zram from the initrd, and the EDID staging
  hook (see its README).

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
  from the bridge; the default `drm.edid_firmware=HDMI-A-1:edid/1280x720.bin`
  forces 720p from a block that `gen-edid.py` writes into the initrd's
  `/usr/lib/firmware`. The served root has no copy, so the dracut module also
  stages it in `/run/pocketfed-fw` before the pivot and the command line adds
  `firmware_class.path=/run/pocketfed-fw`; otherwise every re-probe after
  switch-root loses the EDID. Pass `--edid-override none` for sinks that do
  advertise HPD.
- **511-character command line.** Pocketboot's boot-image loader passes only the
  512-byte cmdline field and ignores `extra_cmdline`, so a longer line is
  silently cut (that is how `firmware_class.path` went missing in early
  trials). The builder refuses to produce one; drop options rather than
  exceeding it.
- **`enforcing=0`.** The command line disables SELinux until smoo's SELinux
  module ships (see samcday/smoo#59). Do not flip it on before then.
- **The kernel bundle is out of scope.** This tooling takes a directory with
  `Image.gz`, the board DTB and the matching module tree; producing that bundle
  is a separate build.

## References

- [samcday/pocketfed#74](https://github.com/samcday/pocketfed/pull/74) — liveboot v2 tooling
- [samcday/smoo#59](https://github.com/samcday/smoo/pull/59) — smoo SELinux module and the dm udev-rule fix

## Samsung Galaxy A5U trial

`--device samsung-a5u-eur` selects the A5 DTB, native DSI panel, touchscreen,
MUIC and regulator drivers. It omits the DB410c HDMI mode and EDID override,
and adds `oops=panic` for panic recovery. The default remains `db410c`.
This is an experimental RAM-boot path; A5 PocketFed greeter boot is not yet
validated. It builds on [#75](https://github.com/samcday/pocketfed/pull/75) and
[the DB410c results](https://github.com/samcday/pocketfed/issues/79).

The kernel bundle must contain `qcom/msm8916-samsung-a5u-eur.dtb` and matching
modules, including `panel-samsung-ea8061v-ams497ee01`. Use the same six
[MSM8916 patches](https://github.com/samcday/pocketboot/tree/main/patches/kernel/msm8916)
as the DB410c trial. In addition to its Fedora configuration, enable:

```text
CONFIG_ARM64_SPIN_TABLE_KEXEC=y
CONFIG_DRM_PANEL_SAMSUNG_EA8061V_AMS497EE01=m
CONFIG_PSTORE=y
CONFIG_PSTORE_RAM=y
CONFIG_PSTORE_CONSOLE=y
```

The destination DT must retain the A5 firmware memory reservations, disable
unused secure IOMMU contexts, and reserve the ECC-protected ramoops region as
in Pocketboot's A5 overlay. Pocketboot propagates the running spin-table CPU
contract during kexec. Do not substitute the DB410c DTB.

```sh
tools/liveboot-db410c/build-initrd.sh \
  --device samsung-a5u-eur \
  --root-image <pfroot.img> --kernel-bundle <a5-kernel-bundle> \
  --smoo-dracut <smoo-checkout>/dracut --smoo-gadget <aarch64-smoo-gadget> \
  --out <a5-output> --export-id <export-id> \
  --product-id 0xBEE2 --run-token lb-a5
```

Use a separate `smoo-host --product-id 0xBEE2 --file <pfroot.img>` so an
existing DB410c session on `0xBEE1` remains independently served. Start from
lk2nd and RAM-boot an A5 Pocketboot resident first; only then send the generated
Android v2 image to Pocketboot with `fastboot -s <a5-serial> boot ...`.
No partition writes are needed.

There is no attached UART in this trial. Serial autologin alone does not
provide host access; physical display confirmation and another diagnostic
transport are still needed. Preserve ramoops after a failure using the
[Pocketboot recovery procedure](https://github.com/samcday/pocketboot/blob/main/docs/a5u-ramoops.md),
substituting the connected device's verified serial. Keep raw captures local.

On 2026-09-21 the connected A5 identified as `samsung,a5u-eur` in lk2nd.
Read-only queries and crash-log retrieval succeeded, but the resident image
upload stalled before the boot command. A USB connection reset restored
queries; a bounded 16 KiB transfer also stalled after passing 1 MiB. This is
an upload failure, not evidence of destination kernel entry.

After a physical port change and firmware reboot, the same resident uploaded
in under a second and started Pocketboot with four CPUs online and 16/16
completed display flips. The user nevertheless confirmed a blank panel with
lit touchkeys, and the USB connection subsequently disappeared. No Fedora
destination has been booted in this trial yet. Recover the retained log and
resolve this resident failure before treating it as an installation candidate.

Gzip packaging reduces the same resident kernel/preboot payload to about
5 MiB. A compressed resident with the display-subsystem node disabled booted
and remained responsive through 54 seconds; its subsequent kexec also returned
successfully. This isolates a useful headless path, but does not yet establish
the cause of the displayed resident’s failure. The physical boot partition
was backed up before considering installation.


The A5 Fedora kernel and matching modules subsequently built successfully.
The 43 MiB Android v2 image passed kernel/ramdisk/DTB byte comparisons; its
initramfs contains the panel, MUIC, touch input, regulator, zram and smoo
components. Pocketboot accepted it, and the destination exposed `dead:bee2`
and connected to its dedicated root server. The screen remained blank;
successful smoo heartbeats established responsiveness but did not establish
that Fedora reached the greeter. Reproducible resident compression is tracked in
[Pocketboot #26](https://github.com/samcday/pocketboot/pull/26).

Further A5 diagnosis is moving to an installed SD root and the carkit UART.
Composite USB diagnostics are left to fastboop. The compressed headless
Pocketboot resident has been installed in internal boot and its payload
verified by reading back the physical partition. The internal postmarketOS
userdata installation was erased at the owner's request. The SD trial reuses
the tested kernel with a normal MMC-root initrd, matching modules in a copied
deployment, and serial root autologin. It is a local diagnostic image, not a
rebuilt A5 release. The SD root's full 8 GiB readback matches the prepared
image, its boot files match their inputs, and both filesystem checks passed.
UART showed that the first installed boot stopped in Pocketpreboot with
`bad payload`, before Linux. Correcting A5's configured preboot load address
to `0x80080000` in Pocketboot #26 allowed boot through Samsung ABL into the
UART shell with all four CPUs online. The installed resident discovered the
PocketFed SD entry as directly bootable. SD handoff and greeter validation
remain pending.
