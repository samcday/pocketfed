# 2026-09-17: unmodified Fedora rawhide kernel boots PocketFed on test-sargo

Milestone A of `hwe/PLAN.md`. Device: test-sargo (fastboot serial `99NAY1AZG1`),
liveboot USB-root via kboop, fixture exported from the cached device image
`localhost/sargo-premouth:20260913` (`59ef70b3f9d5…`), default overlay.

The derived liveboot profiles, initrd module lists and the UART diagnostic
overlay used for these runs are deliberately kept out of this branch (the
liveboot harness is being reworked separately); they live untracked under
`out/hwe/liveboot/` in the working checkout and can be recreated from the
descriptions below.

## Inputs

| Item | Value |
| --- | --- |
| Kernel | `7.3.0-0.rc3.260914g704340f1cd0d.32.fc46.aarch64` from koji (kernel-core `1e111d86ac36…`, kernel-modules-core `9134b1e7810d…`, kernel-modules `8d9e8b863a69…`, kernel-modules-extra `987b18ed26b5…`, kernel-modules-internal `db150c74d540…`) |
| Source | kernel-ark tag `kernel-7.3.0-0.rc3.704340f1cd0d.32` |
| Kernel patches | none |
| Out-of-tree kmods | `pinctrl-sdm670`, `qnoc-sdm670`, `panel-samsung-s6e3fa7`: verbatim upstream sources from that tag, built against the matching `kernel-devel` in an arm64 rawhide container (`hwe/kmods/sdm670-early`), because Fedora leaves `PINCTRL_SDM670`, `INTERCONNECT_QCOM_SDM670` and `DRM_PANEL_SAMSUNG_S6E3FA7` unset |
| DTB | Fedora's own `sdm670-google-sargo.dtb` plus one overlay adding the debug UART (`hwe/dt/overlays/sdm670-google-sargo-debug-uart.dtso`); composed blob `6d22dce698f3069e…` |
| Symbol reconstitution | the tag's DTS compiles byte-for-byte to Fedora's blob; `-@` recompile supplied 258 symbols and 124 extra phandles, existing phandles untouched (`out/hwe/A4/symbolise.json`) |
| Bundle | `out/liveboot/candidates/stock-rawhide-73rc3-05` (Image `029c7ab13e714fa6…`) |
| Profile | `out/hwe/liveboot/google-sargo-stock-nomsm.json`: the shared Sargo initrd module list minus the downstream-only `qcom_pmic_typec_smb2` and `qcom_fg`, minus `msm` (see open items), plus `panic=10` |

## Runs

| Run | Bundle / profile | Outcome |
| --- | --- | --- |
| `stock-rawhide-73rc3-02-01` | Fedora DTB unmodified | Bootloader handed off, then silence: Fedora's DTB has no `serial0` alias and no `serial@a90000`, so neither earlycon nor the console exist. USB gadget never appeared. Manual reset needed. |
| `stock-rawhide-73rc3-03-01` | + debug UART overlay, kmods compressed with default xz | Full console. kboop-init died at 3.4 s: `decompression failed with status 6` on `pinctrl-sdm670.ko.xz`. The in-kernel decompressor needs `--check=crc32 --lzma2=dict=1MiB` like `scripts/Makefile.modinst`. Manual reset needed. |
| `stock-rawhide-73rc3-05-01` | + crc32 kmods, `msm` still in the initrd list | All early modules loaded (polyfills included). Hard reset with `gcc_reset_status=SECURE_WDOG_EXPIRE` at ~4.4 s while inserting `ubwc_config`/`msm` (the modules following `qcom_smem`). The phone returned to fastboot by itself. |
| `stock-rawhide-73rc3-05-02` | `msm` removed from the initrd list, `multi-user.target` | **pass**. systemd exec at 18.1 s, handoff report: SELinux Enforcing, root overlay on USB EROFS, modules from `/dev/ublkb1`, `failed_units: []`, `sam-sargo login:` on the UART. From the root, udev loaded `msm`: DPU bound DSI and the panel, `[drm] Initialized msm 1.13.0`, `msmdrmfb` registered. GPU: `Unable to load qcom/sdm670/sargo/a615_zap.mbn` (firmware not in the fixture root), so no GPU acceleration in this run. SysRq reboot over UART worked. |
| `stock-rawhide-73rc3-05-03` | same, `graphical.target` | **pass** handoff (Enforcing, `failed_units: []`), msm display up, and Sam confirmed the `phosh-first-boot` greeter on the panel. Touch input did not work even though `rmi4_i2c 0-0020` probed and registered `Synaptics S3706B` as input0 at 20.2 s (open item). |

### Touch investigation (runs 05-04 to 05-06, 07-01)

A diagnostic overlay (`out/hwe/liveboot/overlay-diag`, service `hwe-touch-diag`)
prints to the UART while Sam taps the panel.

| Run | Variation | Result |
| --- | --- | --- |
| 05-04 | baseline | rmi4 probed, `Synaptics S3706B` on seat0 with `ID_INPUT_TOUCHSCREEN`, libinput lists it, SELinux labels fine. IRQ 111 (`msmgpio 125 Edge rmi4_i2c`) stays at 0 across taps, 0 bytes from `event0`. Not a userspace problem. |
| 05-05 | + `/sys/kernel/irq` and debugfs dumps | hwirq 125, type edge, wakeup disabled; no IRQ debugfs (`GENERIC_IRQ_DEBUGFS` off in Fedora). |
| 07-01 | `pinctrl-sdm670` variant with the PDC wake map disabled (`hwe/kmods/sdm670-early-nopdc`) | Still 0 interrupts. The 7.2/7.3 PDC pass-through rework is **not** the cause (DeepSeek's code audit in `out/hwe/R1/REPORT.md` reached the same conclusion). |
| 05-06 | unbind/bind `rmi4_i2c 0-0020` after the display is up, then tap | The IRQ counter moved to 1 and i2c traffic resumed. |

Working theory: the touch IC shares its reset/power sequencing with the display
panel. In these profiles `msm` and the panel driver load late from the root,
after `rmi4_i2c` probed at 19.6 s, so the panel bring-up re-initialises the
touch IC and the driver's interrupt configuration is lost. The downstream
liveboot loaded `msm` in the initrd, before rmi4, which hides this. The proper
fix is the same as the msm open item below: get `msm` loading in the initrd
without the TZ reset, or otherwise order rmi4 after the panel.

## What this establishes

- The stock Fedora aarch64 kernel image and module set boot sargo with zero
  source patches. The only additions are three unmodified upstream drivers
  Fedora does not build, and one devicetree overlay.
- The "Fedora DTB as input contract" model works: symbols can be reconstituted
  from the public kernel-ark tag with a byte-identical equivalence check, and
  `fdtoverlay` then applies a normal `.dtso`.
- The Sargo initrd module list is usable on the stock kernel with the two
  downstream-only modules dropped.

## Open items

- `msm` in the initrd triggers a TZ-side reset on this kernel, while loading
  it from the root works. The downstream `.11` kernel tolerated `msm` in the
  same kboop initrd. Differences to bisect: kernel 7.1.2 vs 7.3-rc3, and
  Fedora's `QCOM_SMEM=m` versus `=y`. Milestone B's production dracut config
  force-loads `msm`, so this needs an answer before B.
- Ask Fedora to enable `PINCTRL_SDM670`, `INTERCONNECT_QCOM_SDM670` and
  `DRM_PANEL_SAMSUNG_S6E3FA7` (all tristate, no dependencies Fedora lacks).
  Until then they stay polyfills.
- Fedora's DTB lacks the debug UART, remoteprocs, wifi, audio, venus, camss,
  Type-C, haptics and fingerprint nodes. The debug UART is the first overlay;
  the rest follow the same path.
- The GPU zap shader path should be checked on a fixture whose root has the
  vendor firmware.
