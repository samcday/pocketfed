# A5 accelerated SD trial

This local image combines the panel-capable `7.1.0-rc6+` kernel from the
September 21 successful SD boot with the signed Patch A Mesa RPMs from
[#90](https://github.com/samcday/pocketfed/pull/90). It enables the GPU IOMMU,
replaces `qcom_tsens.ko` with the
[deferred-probe lifetime fix](https://github.com/samcday/linux/pull/4), and
selects Phoc GLES2 and GTK GL rendering. It contains no GPU skip parameter,
thermal blacklist, Pixman override, or liveboot transport.

The normal device Containerfile remains separate: its pinned 7.2 COPR kernel
still needs the panel and thermal work packaged. This trial uses an explicit
external kernel bundle, as did the successful hardware bring-up. It is not a
claim that the production image or GPU has been validated on the A5.

## Inputs

Use a copy of the successful A5 kernel bundle, not the headless resident's
kernel. Its source is `samcday/linux` base
`d87323486b79a31b9b25eb6fe30f1b503f142ff2` plus Pocketboot's
[six MSM8916 patches](https://github.com/samcday/pocketboot/tree/f211b1cb0c494e4b8c1180c208009d6e0e356971/patches/kernel/msm8916).
The locally applied series is commit `741551db171eea97f806aa11a20e270673d2115a`
(that local commit is not a published GitHub ref). Retain its A5 kernel
configuration and matching modules; the configuration SHA-256 is
`ede32630eea96eb1f8c42b73d8064a2ea6835551f5f4c8b752a26db31a064f61`. The bundle layout is:

```
Image.gz
kernel.config
modules/lib/modules/7.1.0-rc6+/...
qcom/msm8916-samsung-a5u-eur.dtb
```

In the copied bundle, replace `kernel/drivers/thermal/qcom/qcom_tsens.ko`
with the fixed module built against that same kernel build directory. Remove
the host-only `modules/lib/modules/7.1.0-rc6+/build` symlink. Enable the frozen
A5 DTB's GPU IOMMU:

```sh
fdtput -t s "$bundle/qcom/msm8916-samsung-a5u-eur.dtb" \
  /soc/iommu@1f08000 status okay
```

The verifier pins the exact trial kernel, DTB, and fixed module hashes, checks
the GPU/IOMMU references and kernel drivers, verifies both A300 firmware blobs
and the complete Mesa package set, and rejects software-rendering overrides.
It also verifies that all eight TSENS callbacks remain in `.text`.

## Build

```sh
sudo podman build --layers=false --arch arm64 \
  --volume /usr/bin/qemu-aarch64-static:/usr/bin/qemu-aarch64-static:ro \
  --build-context kernel-bundle="$bundle" \
  -f devices/samsung-a5u-eur/Containerfile.accelerated-trial \
  -t localhost/pocketfed-phosh-samsung-a5u-eur:accelerated-20260922 .
```

The QEMU bind is only for an x86 host whose binfmt interpreter is not registered
with the `F` flag. It is not copied into the image. The Phosh base is pinned by
digest; Mesa is pinned to `26.2.2-6.2.pocketfed.a3xxfs.fc46.aarch64`.

Use the existing `builder/bootc-to-fastboot samsung-a5u-eur phosh` with the
local OCI as `PF_SOURCE_IMAGE_REF` and `PF_A5_BOOTLOADER=pocketboot` to compose
root, boot and ESP filesystem images. This keeps BLS/UUID validation, skips
UEFI/GRUB installation, and emits an empty FAT ESP. The trial disables the
UEFI-only updater; Pocketboot reads the BLS entries directly. Its Android names do not authorize writing internal partitions. For
the SD trial, convert sparse boot/root images to raw and map them to the
verified SD layout; preserve the generated UUIDs and BLS references. Do not
repartition or flash without checking the currently attached A5 identity.

The final stage installs the renderer settings in both `/etc/environment`
(PAM login sessions) and `environment.d` (user services), and explicitly prefixes
the greeter command. greetd 0.10.3 constructs the child environment from PAM;
variables on the daemon's systemd unit alone do not reach its children.
`TRIAL_BASE_IMAGE` may select an already built `trial-core` stage for session-only
iteration without repeating the kernel, Mesa, and initramfs composition.

## Update policy

This local OCI is not published as an update channel. Set the installer's
`PF_TARGET_IMAGE_REF=ghcr.io/samcday/pocketfed-phosh-samsung-a5u-eur:rawhide`
explicitly to record the eventual production destination, but **keep upgrades
disabled for this trial**: that destination does not retain the trial kernel
and accelerated configuration. Do not run `bootc upgrade` or enable automatic
updates until an accelerated update image is published or a return to the
production image is intentional. Test iterations replace the SD artifacts.

Both `bootc-fetch-apply-updates.timer` and `rpm-ostreed-automatic.timer` are
already disabled in the finished image, with disabled first-boot presets;
this was checked against the final image. Keep those settings unchanged.

## Validation status

Local arm64 OCI composition and its hardware-support assertions passed.
The existing builder completed the Pocketboot filesystem mode. BLS asset,
OSTree deployment, fstab/UUID, filesystem integrity, raw conversion, checksum,
and historical SD partition size checks all passed. Reading the raw root also
confirmed the final login settings, Mesa version and fixed TSENS module hash.

Final image ID:
`e391b595a5dcba288d831d7d0ee979de29d9a004b770e6d150e05faa39150dfc`.
Raw SD artifact SHA-256 values:

- Root (8 GiB): `0c360f7005484030efc2dceaa734ecb6c338ebc8e7d81292e7f25e73eb06c854`
- Boot (1 GiB): `b53efb5f4f2d1f4b9a3cf31f7262c8c93e856e1572d1d329b10e311466470567`
- Empty ESP (200 MiB): `2403f658333a0ace2eb8b18f27c35930607f595c702d8f24fad5202cecdcf6d4`

CI runs the standard images; the explicit external-bundle trial was built and
validated locally. Hardware acceptance is
still pending: confirm native MSM KMS and Adreno 306 rendering in both the
greeter and Phosh, exercise GTK4 applications, and check UART for GPU faults,
resets, or thermal-probe errors. No fresh A5 boot is claimed here.
