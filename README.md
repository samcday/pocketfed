# pocketfed

Some fed in your pocket.

## OnePlus 6T (fajita) flash artifacts

PocketFed uses two layers for device installation:

1. A device OCI contains the immutable system, kernel, DTB, initramfs, and
   Android boot image.
2. The image builder installs that OCI into an OSTree userdata filesystem and
   emits a flashable artifact set:

   - `boot.img`
   - `userdata.img` (Android sparse ext4, 8 GiB before first-boot growth)
   - `SHA256SUMS`

The OCI is the natural update and source-build boundary. Hosting the three
flash artifacts separately is optional and does not change their format.

### Build everything from this checkout

Install `git`, `just`, `podman`, and `skopeo`. On an x86-64 host, Podman also
needs working arm64 binfmt/QEMU support. Then run:

```sh
PF_DEVICE=oneplus-fajita \
PF_ROOT_SSH_AUTHORIZED_KEYS="$HOME/.ssh/id_ed25519.pub" \
just fastboot
```

This builds the Fajita device OCI and image-builder container locally, exports
the device OCI through a temporary read-only OCI layout, and writes the three
artifacts to `out/oneplus-fajita/`. The userdata image temporarily requires 8
GiB plus space for the OCI and sparse output. Temporary files stay on the output
filesystem instead of consuming `/tmp`. Override the logical size with
`PF_IMAGE_SIZE` and the output directory with `PF_OUTPUT_DIR`.

The future update source embedded in userdata defaults to
`ghcr.io/samcday/pocketfed-phosh-oneplus-fajita:rawhide`, even when the source
OCI was built locally. Override it explicitly with `PF_TARGET_IMAGE_REF`.

### Build artifacts from the published device OCI

Once the Fajita device OCI has been published, no checkout is required:

```sh
mkdir -p out/oneplus-fajita

sudo podman run --rm --pull=always --privileged --arch arm64 \
  -v "$(realpath out/oneplus-fajita):/out:Z" \
  -v "$(realpath "$HOME/.ssh/id_ed25519.pub"):/run/pocketfed/authorized_keys:ro" \
  -e PF_ROOT_SSH_AUTHORIZED_KEYS=/run/pocketfed/authorized_keys \
  ghcr.io/samcday/pocketfed-image-builder:rawhide \
  oneplus-fajita phosh rawhide
```

The builder needs `--privileged` for its temporary loop-mounted ext4 image.
It is arm64-only; `--arch arm64` uses binfmt/QEMU on a configured x86-64 host.

Verify the completed artifact set before flashing:

```sh
(cd out/oneplus-fajita && sha256sum --check SHA256SUMS)
```

### Experimental flashing

This initial Fajita image has build-time verification but has not yet completed
a hardware boot test. Flashing `userdata` destroys the phone's existing user
data. Unlock the bootloader and back up anything important. Using the inactive
boot partition avoids overwriting both boot images, but it is not an Android
rollback path: both slots share the userdata that this procedure replaces. Be
prepared to restore the stock firmware if PocketFed does not boot.

Check the current slot with `fastboot getvar current-slot`. If it reports `a`,
flash PocketFed to `boot_b` and activate `b`; if it reports `b`, use `boot_a`
and activate `a`. For example, when Android currently uses slot `a`:

```sh
cd out/oneplus-fajita
fastboot flash userdata userdata.img
fastboot flash boot_b boot.img
fastboot set_active b
fastboot reboot
```

Do not flash both boot slots until the first boot, storage, watchdog, display,
touch, USB networking, and SSH have been validated on the device.
