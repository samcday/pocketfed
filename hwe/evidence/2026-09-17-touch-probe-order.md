# 2026-09-17: sargo touch on the stock Fedora kernel, probe order and the IC

Follow-up to the touch investigation in
`2026-09-17-stock-rawhide-liveboot.md` (pocketfed #64, PR #71). Same kernel
(`7.3.0-0.rc3.260914g704340f1cd0d.32.fc46`, bundle
`out/liveboot/candidates/stock-rawhide-73rc3-05`), same fixture image
(`localhost/sargo-premouth:20260913`, `59ef70b3f9d5…`), device test-sargo.
Untracked working material lives under `out/hwe/liveboot/` (profiles,
`overlay-order` diagnostic overlay) and `out/hwe/A8`, `A9`, `R2`.

## Question

Run 05-06 showed IRQ 111 (`msmgpio 125 Edge rmi4_i2c`) moving from 0 to 1 after
`rmi4_i2c 0-0020` was unbound and rebound with the display up, and the working
theory was that the touch IC shares reset or power with the panel, so `rmi4`
has to initialise after `msm`. This note checks that theory from the sources
and on the phone.

## What the device trees actually say

| Signal | Downstream (bonito 4.9, `sdm670-b4s4-touch.dtsi` at `ab4493f31457`) | Mainline (`sdm670-google-common.dtsi`, kernel-ark 7.3-rc3) |
| --- | --- | --- |
| Touch power | pm660 gpio12 strapped `output-high` by the touch node's pinctrl; no regulator requested | `vio-supply = <&ts_1p8_supply>`: `regulator-fixed` on pm660 gpio12, enabled by `rmi_i2c` at probe; no `vdd-supply` (dummy) |
| Touch reset | `synaptics,reset-gpio = <&tlmm 99>`; driver pulses it low 1 ms at probe, waits 20 ms | pinctrl `output-high` on gpio99 only; the driver never resets the IC by GPIO, only the F01 software reset |
| Touch IRQ | tlmm 125, `0x2008` = level low, oneshot | tlmm 125, `IRQ_TYPE_EDGE_FALLING` |
| tlmm 135 "switch" | driven 0 while running, `switch-ssc-state` (1) while suspended | pinctrl `output-low`, static |
| Panel | reset tlmm 75, TE tlmm 10, `vci-supply = <&pm660l_l6>` (3.008 V) | reset tlmm 75, TE tlmm 10, `power-supply = <&vreg_l6b_3p3>` (declared, the s6e3fa7 driver never requests it) |
| Panel/touch coupling | none in DT. Downstream re-initialises the IC from a DRM/FB blank notifier on every unblank (`FB_READY_RESET`) | none |

Neither tree shares a regulator or a reset line between the touch IC and the
panel. The mainline touchscreen node is byte-identical in the working PocketFed
`.11` DTB and in Fedora's blob, so the DT is not what differs between the
kernels. Details and `file:line` citations: DeepSeek audit `out/hwe/R2/REPORT.md`
(brief `hwe/briefs/R2-touch-power-reset-audit.md`).

Two other candidates were ruled out from source: the regulator core's 30 s
unused-regulator cleanup never disables rpmh regulators (their `is_enabled`
returns `-EINVAL` until Linux has voted, and `regulator_late_cleanup` skips
`<= 0`), and no `disabling` line appears in any run; and
`CONFIG_DRIVER_DEFERRED_PROBE_TIMEOUT=-1` on this kernel, so fw_devlink
supplier waits are never relaxed.

## Runs

Diagnostic service `hwe-touch-order` (overlay `out/hwe/liveboot/overlay-order`,
fixture `sargo-premouth-20260913-order2`): reads tlmm 99/125/135 and pm660
gpio12 through the GPIO character device without changing their configuration,
waits for the DSI panel to bind, optionally loads `rmi_i2c` only then
(`hwe.touch=late`, `modprobe.blacklist=rmi_i2c`, `rmi_i2c`/`rmi_core` dropped
from the initrd list), and then logs per 20 s window the IRQ delta, the bytes
read from the rmi input node and 100 Hz samples of the ATTN line.

| Run | Candidate / mode | What happened |
| --- | --- | --- |
| 05-07 | 05, `hwe.touch=late` | Panel bound at 38.5 s. Before `rmi_i2c` loaded (93 s): tlmm 99 (reset) reads 0, 125 (ATTN) reads 0, 135 reads 0, `ts_1p8_supply` use count 0 (pm660 gpio12 driven low by the fixed regulator), i2c9 IRQ count 0. `modprobe rmi_i2c` at 99.9 s: probe fine, S3706B found, gpio99 and ATTN read 1 afterwards. IRQ 133 stayed 0 and `/dev/input/event3` produced 0 bytes through eight 20 s windows and 60 s monitors to 385 s. |
| 05-08 | 05, `hwe.touch=late`, ATTN sampled at 100 Hz | Same late probe at 95 s. Six windows: IRQ 0, 0 bytes, ATTN sampled ~1830 times per window, never low. Then a 1 ms low pulse on tlmm 99 and unbind/bind: IRQ went 0 to 3 during the re-probe (reset attention edges), then six more windows with IRQ stuck at 3, 0 bytes, ATTN never low. |
| 08-03 | 08 (`panel = <&panel>` overlay), `hwe.touch=monitor`, `rmi_i2c` in the initrd as before | `0-0020` gained `supplier:mipi-dsi:ae94000.dsi.0`; `rmi4_i2c` probed at 42.56 s, 0.1 s after `[drm] Initialized msm` at 42.46 s, instead of at 15 s: fw_devlink held the probe until the panel bound. IRQ 0, 0 bytes, ATTN never low across six windows; hardware reset pulse plus rebind gave IRQ 3, then six more silent windows. i2c-dev dump after both probes: PDT F01/F12/F34 on page 0, device status 0x00 (no error, not unconfigured), interrupt enable 0x07, **device control 0x00** although `rmi_f01` writes 0x84 (CONFIGURED plus NOSLEEP) at probe. |
| 08-04 | 08, `hwe.touch=monitor`, plus a userspace ctrl0 write-back test | Same ordering (rmi4 after the panel). `ts_1p8_supply` use count 1 after probe. Writing 0x84 to F01 ctrl0 from userspace reads back 0x04: the CONFIGURED bit is not readable on this firmware and the DT's `syna,nosleep-mode = <1>` means "allow sleep" (enum: 0 default, 1 off, 2 on), so ctrl0 = 0x00 is the driver's intended state, not a lost write. 12 silent windows, IRQ 0 then 3 after the reset pulse. |
| 11-01, 11-02 | fixture's own PocketFed `.11` kernel (`7.1.2-0.pocketfed.sdm670.11`), msm in the initrd, `hwe.touch=monitor` | Reference on the known-good kernel. Both runs soft-locked (`watchdog: BUG: soft lockup`, RCU stalls, a kworker in `bpf_prog_free_deferred`/`__text_poke`) right after the service read the PMIC GPIO through the character device and `/sys/kernel/debug/gpio`; the stock kernel handled the same reads fine. Rebooted over SysRq. |
| 11-05 | `.11` kernel, PMIC GPIO/debugfs reads skipped | msm at 6.7 s, rmi4 at 8.4 s. IC registers identical to the stock kernel (PDT F01/F12/F34, status 0x00, ctrl0 0x00, interrupt enable 0x07, write-back 0x04). tlmm 99/125/135 read 1/1/0 like the stock kernel. IRQ 136 already at 30 when the service started at 71 s, then no further IRQs, ATTN never low, F12 saw no finger in the windows; 11-01 and 11-03 had 0 at the same point, so those 30 look like taps during boot rather than IC self-activity. Full `regulator_summary` saved as `out/hwe/A9/regsum-11.txt`. |

No tap was confirmed by Sam during 05-07, 05-08 or 08-03, so the zero counts
in those runs bound the IC's idle behaviour but do not yet prove that touch
is dead in the late-probe or panel-ordered configurations.

## Reading

- **The probe-order theory is not confirmed.** Loading `rmi4_i2c` after the
  panel (05-07, 05-08) or making fw_devlink defer it until the panel bound
  (08-03 to 08-06) produced the same silence as the baseline: IRQ 0, no event
  bytes, ATTN never asserted. Whether that silence means "dead" or "nobody
  tapped" depends on taps that were not confirmed during these runs.
- **The 05-06 "rebind makes the IRQ appear" observation was the reset
  attention, not touch.** A fresh probe of an unconfigured IC never produces
  an edge (0 in every first probe), while a hardware reset pulse plus rebind
  produces two or three edges on both kernels (05-08, 08-03, 08-04, 11-05).
  The counter moving to 1 in 05-06 therefore said nothing about ordering.
- **Nothing measurable differs between the kernels at the IC.** Same PDT,
  same F01 status/control, same GPIO levels on tlmm 99/125/135, same
  `ts_1p8_supply` state, and the regulator summaries differ only in wifi,
  Bluetooth, audio, camera and Type-C consumers that the stock profile does
  not enable (`out/hwe/A9/regsum-11.txt` vs `regsum-stock-08-06.txt`).
- What remains untested without a finger on the glass: whether ATTN goes low
  at all on the stock kernel (the 100 Hz sampler answers that in one tap),
  and whether the `.11` liveboot itself takes touch (11-05 counted 30 IRQs
  before the service started, which is what a few taps during boot would
  leave behind; 11-01 and 11-03 counted 0).
- The `panel` phandle is a working ordering lever regardless: with
  `panel = <&panel>` on the touchscreen node the i2c client gained a device
  link to `ae94000.dsi.0` and probed 0.1 s after `msm` initialised, with
  `CONFIG_DRIVER_DEFERRED_PROBE_TIMEOUT=-1` guaranteeing the wait is never
  relaxed. Downstream needs no such link because its driver re-initialises
  the IC from a display blank notifier on every unblank.

## Proposed fix

If taps show that ordering matters after all, the upstreamable change is
small and already has a binding: add `panel = <&panel>;` to the
`synaptics-rmi4-i2c@20` node in `sdm670-google-common.dtsi`
(`hwe/dt/overlays/sdm670-google-sargo-touch-panel.dtso` is that change as a
test overlay, composed into candidate 08). `touchscreen.yaml` documents the
property as "power sequenced together with the panel"; `syna,rmi4.yaml`
would need to reference `touchscreen.yaml` at the root (today only the F11/F12
children do), and `rmi_i2c` could optionally register as a
`drm_panel_follower` so a later panel unprepare/prepare re-initialises the
IC (sketch in `out/hwe/R2/REPORT.md`, question 5).

If taps show ATTN never asserts on the stock kernel even after the panel,
ordering is a red herring and the next candidates are the power-on sequence
(mainline releases reset before enabling `vio`, downstream pulses reset after
power) and the level-low versus edge-falling IRQ type. Both are one-line DT
or driver experiments on the same harness.

Either way, `msm` should still be in the installed image's initrd for the
display, so the panel is up before rmi4 in production; the `panel` link only
matters for kernels and images that load `msm` late, which is exactly the
distro-kernel case this branch is about.

## Aside: msm in the initrd

The TZ `SECURE_WDOG_EXPIRE` reset when `msm` is inserted from the kboop initrd
(run 05-01) is a different family: it happens inside `msm`/`ubwc_config`
insertion before any userspace, independent of the touch IC. Not chased here.
