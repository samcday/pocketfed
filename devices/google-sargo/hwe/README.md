# google-sargo on Fedora's rawhide kernel

`PF_KERNEL=fedora just device PF_DEVICE=google-sargo` builds the Sargo image on
Fedora's own rawhide kernel instead of the COPR `kernel-sdm670-mainline` stream.
The default `PF_KERNEL=copr` path is unchanged.

## What the variant adds

- The pinned Fedora `kernel`, `kernel-core`, `kernel-modules`,
  `kernel-modules-core`, `kernel-modules-extra` and `kernel-modules-internal`
  aarch64 packages, from the Fedora repositories.
- Three out-of-tree modules that Fedora ships disabled
  (`PINCTRL_SDM670`, `INTERCONNECT_QCOM_SDM670`,
  `DRM_PANEL_SAMSUNG_S6E3FA7`), built from verbatim kernel-ark sources against
  the matching `kernel-devel`. See `kmods/`.
- One devicetree overlay that adds the SDM670 debug UART (uart12, QUP1 SE4).
  Fedora's `sdm670-google-sargo.dtb` has no `serial0` alias and no
  `serial@a90000`, so the console never appeared. The overlay is applied to
  Fedora's own blob after `__symbols__` are reconstituted from the matching
  kernel-ark tag; `tools/hwe/dtb-symbolise.py` fails the build unless the
  recompiled tag DTS is equivalent to the installed blob. See `tools/hwe/`.

The two downstream-only early modules `qcom_pmic_typec_smb2` and `qcom_fg` do
not exist upstream, so the image's dracut config is generated with those two
entries removed. The modem (`rmnet`) is not built by Fedora and is out of scope
for this variant.

## Picking a kernel

    PF_KERNEL=fedora \
    PF_FEDORA_KERNEL=7.3.0-0.rc3.260914g704340f1cd0d.32.fc46 \
    just device PF_DEVICE=google-sargo

`PF_FEDORA_KERNEL` is the aarch64 kernel release without the trailing
`.aarch64`. `PF_KERNEL=copr` ignores it. The validated release is
`7.3.0-0.rc3.260914g704340f1cd0d.32.fc46` (source tag
`kernel-7.3.0-0.rc3.704340f1cd0d.32`); the tag is derived from the release by
dropping the `.fcNN` suffix and the leading `YYMMDDg` date from the commit
field.

## Re-pinning the kmod sources

`kmods/sources.txt` lists the six kernel-ark paths;
`kmods/sources.sha256` pins each file's sha256 and the build fails with a
re-pin hint on any mismatch. To move both to a new tag:

    tag=kernel-7.3.0-0.rc3.704340f1cd0d.32
    while read -r path; do
        curl -fsSL "https://gitlab.com/cki-project/kernel-ark/-/raw/$tag/$path" -o /tmp/kmod-src
        printf '%s  %s\n' "$(sha256sum /tmp/kmod-src | cut -d' ' -f1)" "$path"
    done < devices/google-sargo/hwe/kmods/sources.txt \
        > devices/google-sargo/hwe/kmods/sources.sha256

The third fetch in the `hwe-dtb` stage (`include/uapi/linux/input-event-codes.h`)
supplies the target of a symlink that `input.h` pulls in when only the
`include/dt-bindings` slice of the tree is fetched.

## Evidence (2026-09-17)

The unmodified rawhide kernel `7.3.0-0.rc3.260914g704340f1cd0d.32.fc46` with
these three modules and the debug-UART overlay booted Sargo to
`graphical.target`: SELinux enforcing, `failed_units: []`, Phosh greeter on the
panel, display up when `msm` loaded from the root. Touch input did not work in
that run: `rmi4_i2c` probed before the panel re-initialised the touch IC, and
its interrupt stopped firing. That ordering issue is the open item; it is not
caused by these kmods.

## Evidence (2026-09-18): the image itself, via liveboot v2

`PF_KERNEL=fedora PF_FEDORA_KERNEL=7.3.0-0.rc3.260916g9b87fdc9af2f.34.fc46 just device`
built `localhost/pocketfed-phosh-google-sargo:fedora-kernel` (source pinning by
tag derivation, DTB equivalence gate and kmod export checks all passed at build
time). `just fastboot-from-image` plus `simg2img userdata.img pfroot.img` and
`tools/liveboot/build.sh` produced the liveboot image; `smoo-host --product-id
0xBEEF --file pfroot.img` served the root; `fastboot boot liveboot.img`.

Result on test-sargo: the image's own dracut initramfs on the Fedora kernel
brought up the smoo root at 10.6 s, switched root, and reached `login:` at
78 s with no failed units on the console. `pinctrl-sdm670`, `qnoc-sdm670` and
`panel-samsung-s6e3fa7` loaded from `updates/sdm670-hwe`, msm initialised the
display from the root, and Sam confirmed the Phosh greeter on the panel **with
working touch**. The 2026-09-17 touch failure did not reproduce on this path
(same driver order: rmi4 in the initrd, msm from the root); differences are the
kernel snapshot (.34 vs .32) and SELinux permissive in liveboot v2, so the
touch item stays open only as "understand why the kboop run differed".

Harness notes: a second smoo gadget (the DB410c, served by another session)
made the unpinned `smoo-host` stall on the wrong device, so pin
`--product-id`; `--append rd.emergency=reboot` did not take effect, so a failed
initrd waits in a locked emergency shell and needs SysRq-b over the UART;
always SysRq-reboot the phone *before* stopping `smoo-host`, or it wedges.
