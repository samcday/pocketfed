# Samsung Galaxy A5U bring-up

Current integration work is tracked in [#88](https://github.com/samcday/pocketfed/issues/88).
The 2026-09-21 trial establishes installed boot and SD-root startup. The
physical screen remains blank, including with a running software-rendered
Phrog greeter. Display/GPU diagnosis continues separately in Pocketboot.

## Verified boot path

Stock Samsung bootloader → compressed Pocketboot in Android `boot` → SD BLS
entry → PocketFed MMC/OSTree initrd → Fedora with a root carkit UART shell.
All four CPUs are online in both Pocketboot and Fedora. The SD root's full
8 GiB readback matches the prepared image; boot artifacts and filesystem
checks pass. Internal userdata was erased with the owner's authorization.

The resident artifact was `pocketboot-a5-arm64-headless.img`, about 5 MiB,
installed in the physical Android `boot` partition and verified by readback.
It is distinct from the generated Android v2 liveboot image, which is only
passed to `fastboot boot`. The installed resident deliberately disables its
display; no Pocketboot UI is expected from that diagnostic build. An earlier
display-enabled resident also showed a blank panel despite completed flips,
and subsequently lost USB.

[Pocketboot #26](https://github.com/samcday/pocketboot/pull/26) adds whole-envelope
gzip and corrects A5 preboot placement to `0x80080000`. Before that correction,
the compressed image RAM-booted via lk2nd but stock startup stopped at
`bad payload`. After it, the installed resident reaches UART and discovers
the directly bootable SD entry. The boot partition is 13 MiB; lk2nd exposes
its payload after a 512 KiB prefix, while Pocketboot targets the full physical
partition. Verify the active implementation before any recovery write.

## Trial limitations

This was a local diagnostic image copied from a tested Sargo deployment with
matching **7.1.0-rc6+** trial modules and a normal MMC-root initrd. It does not
validate the A5 Containerfile's pinned **7.2 COPR** kernel or a fresh A5 OCI
build. It uses root UART autologin, permissive SELinux and a pre-pivot
breakpoint. Those settings are not normal installation defaults.

| Area | Evidence | Remaining work |
| --- | --- | --- |
| Native display | With `msm.skip_gpu=1`, MSM DRM replaces simpledrm and reports connected, active DSI at 720×1280. | Panel remains physically blank. Investigate resident initialization and kexec handoff without assuming causality. |
| Greeter | `WLR_RENDERER=pixman GSK_RENDERER=cairo` lets Phrog own the output without restarting. | A visible, usable greeter and input are unverified. Default rendering fails EGL with the GPU skipped. |
| GPU | The trial DT enables Adreno but disables its IOMMU, causing `ENODEV` and preventing display component binding. | Reconcile the DT and validate acceleration; unloading after this failed bind also faults in `adreno_remove`. |
| Thermal | Deferred TSENS probing calls freed `__init` text. The display-only trial excludes `qcom_tsens` and has no Oops. | Validate and package the [callback-lifetime fix](https://github.com/samcday/linux/pull/4), then remove the exclusion. |
| Installed system | SD root and UART startup work. | Rebuild an A5-native deployment, reconcile module labels/ownership and kernel handoff support, remove trial overrides, and verify repeatable reboot. |

The device's custom internal GPT differs from the stock Samsung PIT and the
builder's cache/system/userdata assumptions. The successful recovery was a
BOOT-only Heimdall write, not a repartition. Do not use the stock PIT as a
layout template for this device. Preserve local backups and verify device
and partition identities before writes.

## Diagnostic workflow

Use the existing installed SD root and 115200-baud carkit UART, coordinating
USB/UART cable swaps. A pre-pivot breakpoint allows the cable to be switched
after Pocketboot starts the SD entry. Keep raw UART logs, serial numbers and
backups local. Changes to the current trial should be recorded separately
from packaged-image validation.

The earlier [A5 liveboot profile](../../tools/liveboot-db410c/README.md#samsung-galaxy-a5u-diagnostic-profile)
is retained for reproducing the RAM-boot trial. Future USB diagnostics should
use released fastboop, tracked in [#74](https://github.com/samcday/pocketfed/issues/74),
rather than adding USB networking or composite-gadget infrastructure here.
