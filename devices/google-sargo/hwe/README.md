# google-sargo on Fedora's own kernel (`-vanilla`)

`PF_KERNEL=fedora just device PF_DEVICE=google-sargo` builds the Sargo image on
Fedora's rawhide kernel instead of the COPR `kernel-sdm670-mainline` stream,
tagged `pocketfed-phosh-google-sargo-vanilla`. CI builds it next to the default
image and publishes it from `main`. `PF_KERNEL=copr`, the default, is unchanged.

The design this grows into is pocketfed issue #76; the tracker is #64.

## What the variant adds on top of Fedora

- **Kernel packages**: `kernel`, `kernel-core`, `kernel-modules`,
  `kernel-modules-core`, `kernel-modules-extra` and `kernel-modules-internal`
  for the pinned release, unmodified. `tools/hwe/fetch-fedora-kernel` takes
  them from the Fedora repositories, or from koji's signed copies once the
  rawhide compose has moved past the pin (it carries one kernel NVR at a time),
  and refuses anything without a valid Fedora signature.
- **No out-of-tree modules.** kernel-ark MR 4753 (in rawhide from
  `7.3.0-0.rc4.*.40`) builds `PINCTRL_SDM670` and `INTERCONNECT_QCOM_SDM670` in
  and `DRM_PANEL_SAMSUNG_S6E3FA7` as a module.
- **Devicetree patches**, in upstream form, listed in
  `dt-patches/series`. Today that is v5 of the SDM670 debug-UART series
  (`serial0` on uart12), which Fedora's `sdm670-google-sargo.dtb` lacks.

The dracut policy drops `qcom_pmic_typec_smb2` and `qcom_fg`, which exist only
in the downstream kernel. Fedora does not build `rmnet`, so the modem is out of
scope for now.

## How the boot DTB is built

`tools/hwe/patch-dtb.py`, in the `hwe-dtb` stage:

1. Compile the DTS of the kernel-ark tag that built the pinned kernel (derived
   from the release: drop `.fcNN` and the `YYMMDDg` date prefix), with
   dt-bindings headers from the signed `kernel-devel` of the same build. The
   result must be **byte-identical** to the DTB in the signed `kernel-core`.
2. Apply `dt-patches/series` with `git apply`: no fuzz, no three-way. A patch
   that no longer applies fails the build with "refresh it against that tag";
   one that is already in the tag fails with "drop it from the series".
3. Compile again. The output is Fedora's blob plus exactly the patches and has
   no `__symbols__`, so a vendor DTBO applied by ABL cannot resolve anything
   against it.

The `bootimg` stage then checks the DTB inside `aboot.img`: `serial0` is the
debug UART, USB stays peripheral-only at high speed, and there is no Type-C
connector (no PD contract can be negotiated, so the COPR image's PD policy
checks have nothing to check; a connector appearing upstream fails the build
until it gets its own checks).

To add a patch, drop the `git format-patch` output (numeric prefix stripped)
into `dt-patches/` and list it in `series`. When the pin moves, run the build:
it names every patch that needs a refresh or has landed.

## Picking a kernel

    PF_KERNEL=fedora \
    PF_FEDORA_KERNEL=7.3.0-0.rc4.260924g62f4c998b297.41.fc46 \
    just device PF_DEVICE=google-sargo

`PF_FEDORA_KERNEL` is the kernel release without `.aarch64`; the default is the
Justfile pin.

## Evidence

| Date | Kernel | Carried | Result on test-sargo (liveboot, nothing flashed) |
| --- | --- | --- | --- |
| 2026-09-17 | `.32` | 3 kmods + UART overlay (kboop) | greeter, touch dead (probe order, kboop only) |
| 2026-09-18 | `.34` | 3 kmods + UART overlay (image) | greeter with touch, `login:` at 78 s |
| 2026-09-25 | `.41` | UART overlay only | greeter with touch, `login:` at 72 s, no failed units |

ABL on test-sargo rejects its `dtbo` partition (`Not valid dtbo found, use only
SoC dtb`), so vendor-overlay interaction is untested against a valid dtbo. The
GPU zap firmware (`a615_zap.mbn`) is not in the image yet.
