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
   - `flash.sh` (a guarded flashing helper that preserves the current slot)
   - `manifest.json` (source OCI provenance and installation policy)
   - `SHA256SUMS`

The OCI is the natural update and source-build boundary. Hosting the five
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
the device OCI through a temporary read-only OCI layout, and writes the five
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

The Fajita image has booted through the graphical session on hardware, but the
installation remains experimental. Flashing `userdata` destroys the phone's
existing user data. Unlock the bootloader, back up anything important, and be
prepared to restore the stock firmware.

Use the generated helper from bootloader fastboot. It verifies the artifacts,
requires a destructive-operation confirmation, reads the current slot, and
flashes `boot.img` back to that same slot:

```sh
cd out/oneplus-fajita
./flash.sh
```

Keeping the current slot is intentional. On Fajita, changing slots also changes
the complete Qualcomm firmware stack and the UFS XBL boot LUN. Do not run
`fastboot set_active` as part of a PocketFed installation.

The reported current slot must already be known to boot a coherent vendor
firmware chain. If the phone reached EDL or fastboot after a failed Android slot
transition, repair that firmware state before using these artifacts.

For a manual installation, first run `fastboot getvar current-slot`. Flash
`userdata.img`, then flash `boot.img` to the reported partition (`boot_a` when
the current slot is `a`, or `boot_b` when it is `b`), and reboot without changing
the active slot. This overwrites the current Android boot image, but preserving
it would require the unsafe whole-firmware slot transition; replacing userdata
already means the other Android slot is not a usable rollback path.

An existing pre-guard PocketFed installation must not use `rpm-ostree upgrade`
to reach a guarded image: OSTree executes `aboot-deploy` from the currently
booted deployment, whose old implementation ignores the staged policy. Install
the first guarded deployment using freshly generated `userdata.img` and the
current-slot `boot.img`; subsequent updates will fail safely until PocketFed has
a boot-only activation mechanism.
