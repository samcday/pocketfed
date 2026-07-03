PocketFed Kernel Config Fragments
=================================

These fragments build lean Fedora-capable kernels for pocket computers without
copying the Fedora ARK config sprawl.  They are plain Kconfig fragments intended
for the upstream kernel `scripts/kconfig/merge_config.sh` workflow.

The layout is deliberately shallow:

- `arch/` contains architecture baseline policy.
- `policy/` contains userspace contracts that are not tied to a board.
- `soc/` contains SoC-family hardware enablement.
- `device/` contains board-specific enablement.
- `profiles/` contains ordered fragment lists for concrete kernels.

Merge from `allnoconfig` so every enabled subsystem is intentional.  Pick one
profile from `profiles/`:

```sh
profile=oneplus-fajita-fedora
kernel_tree=vendor/kernel
config_root=$PWD/kernel/configs
mkdir -p /tmp/pocketfed-$profile
mapfile -t fragments < <(grep -vE '^[[:space:]]*($|#)' "$config_root/profiles/$profile.list")
for i in "${!fragments[@]}"; do fragments[$i]="$config_root/${fragments[$i]}"; done
ARCH=arm64 "$kernel_tree/scripts/kconfig/merge_config.sh" -n -r \
  -O /tmp/pocketfed-$profile /dev/null "${fragments[@]}"
```

Then inspect unmet symbols and size impact before building:

```sh
scripts/diffconfig .config /tmp/pocketfed-$profile/.config
ARCH=arm64 LLVM=1 make O=/tmp/pocketfed-$profile olddefconfig
```

Policy
------

The SDM845 core fragment keeps platform plumbing built in: clocks, pinctrl,
RPMh, SPMI, regulators, interconnect, IOMMU, GENI buses, UFS root storage, and
the DWC3 controller.  The SDM670 core fragment follows the same rule but uses
SDM670 TLMM/interconnect support and built-in SDHCI/eMMC root storage instead
of UFS.  Large or optional phone features are modules: display/GPU, remoteprocs,
IPA, Wi-Fi, Bluetooth, audio, panels, charger/fuel-gauge, and other per-device
peripherals.

Some useful phone symbols exist only in downstream patchsets and are not present
in this source tree today.  Keep those out of the verified profile until the
matching patches are in-tree; otherwise every merge produces noise.  In
particular, the live SDM670 device tree does not yet expose sargo Wi-Fi,
remoteproc, IPA, or audio nodes, and the live tree lacks a selectable LG SW49410
panel driver for judyln.  The judyln DTS also notes that UFS may need the
`clk_ignore_unused` boot argument; pass that through the bootloader rather than
forcing a profile-wide kernel command line.
