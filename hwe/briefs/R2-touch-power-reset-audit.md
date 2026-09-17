# Brief R2: how the sargo touch IC is powered and reset (downstream vs mainline)

Read-only code audit. Context: pocketfed #64. On the unmodified Fedora
7.3.0-0.rc3 kernel the Synaptics S3706B (rmi4_i2c 0-0020 on i2c@a84000,
IRQ tlmm gpio125) probes but never interrupts unless rmi4_i2c is bound after
the msm display driver and the samsung-s6e3fa7 panel came up. We need the
real electrical relationship between the touch IC and the panel, from source.

Work only inside this checkout. Write only `out/hwe/R2/REPORT.md`. Do not
run git commands, do not modify any other file, no network.

## Sources (all already on disk)

- Downstream Google kernel (android-msm-bonito-4.9, commit
  ab4493f31457eea175568b18b8300d4d12aaeea8), copied verbatim:
  - `out/hwe/R2/src/dts/sdm670-b4s4-touch.dtsi`, `sdm670-s4-touch.dtsi`
  - `out/hwe/R2/src/dts/sdm670-b4s4-display.dtsi`, `dsi-panel-s6e3fa7-1080p-cmd.dtsi`
  - `out/hwe/R2/src/synaptics_dsx_v27/` (core, i2c, fw_update, header, Kconfig)
- Mainline (kernel-ark tag kernel-7.3.0-0.rc3.704340f1cd0d.32):
  `/var/home/sam/src/pocketfed-hwe/out/hwe/linux-ark-7.3rc3` — read
  `arch/arm64/boot/dts/qcom/sdm670-google-common.dtsi`,
  `arch/arm64/boot/dts/qcom/sdm670.dtsi` (tlmm, i2c9, mdss, pm660 gpios),
  `drivers/input/rmi4/rmi_i2c.c`, `rmi_driver.c`, `rmi_f01.c`,
  `drivers/gpu/drm/panel/panel-samsung-s6e3fa7.c`,
  `drivers/gpu/drm/msm/dsi/dsi_host.c` (only the panel attach/power path),
  `drivers/gpu/drm/drm_panel.c` (panel follower API),
  `Documentation/devicetree/bindings/input/touchscreen/touchscreen.yaml` and
  `input/syna,rmi4.yaml`.

## Questions (answer each with file:line citations)

1. Downstream power: what do `synaptics,power-gpio`/`touch_power_default`
   (pm660 gpio12), `synaptics,reset-gpio` (tlmm 99), `synaptics,switch-gpio`
   (tlmm 135) and `synaptics,switch-ssc-state` do in synaptics_dsx_core.c:
   exact sequence and delays at probe (`synaptics_rmi4_set_gpio`,
   `synaptics_rmi4_gpio_setup`, reset in probe and in `synaptics_rmi4_reset_device`),
   suspend/resume, and what "SSC" means for the switch gpio. Are any
   regulators requested (`pwr_reg_name`/`bus_reg_name`) for bonito? Which
   IRQ trigger (interrupts = <125 0x2008>) does downstream use?
2. Downstream display: which supplies and gpios does the s6e3fa7 panel use
   (vci pm660l_l6, reset tlmm 75, te tlmm 10, anything else). Is anything
   shared with the touch node? Does the downstream touch driver register a
   DRM/fb notifier so that it re-initialises the IC on display on/off
   (look for `fb_notifier`, `drm_notifier`, `synaptics_rmi4_dsi_panel_notifier`,
   `SYNA_DSX_DRM`/`FB` config, and the `synaptics_rmi4_sensor_wake`/`sleep` paths)?
   If so, describe exactly what it does on `FB_EARLY_EVENT_BLANK`/`DRM_PANEL_EVENT_*`.
3. Mainline: what does the touchscreen node express (supplies, pinctrl,
   IRQ type, no reset-gpios) versus downstream; list every difference. Does
   rmi_i2c/rmi_driver ever toggle a reset gpio or re-init after a panel
   event? What does `syna,nosleep-mode`/F01 device control do at probe and
   could a later external reset of the IC lose it?
4. Mainline panel bring-up: what does samsung-s6e3fa7 prepare/enable do to
   gpio75 and its power-supply, and what does msm dsi_host do around panel
   attach that could affect an IC sharing a rail? Any code path that touches
   tlmm 99/125/135 or pm660 gpio12? (Expect none; confirm.)
5. Panel follower: does `drm_panel_add_follower` plus the touchscreen.yaml
   `panel` phandle fit rmi4_i2c? Sketch (prose plus a short pseudo-diff, not a
   full patch) how rmi_i2c would register as a panel follower and defer IC
   init to `panel_prepared`, and note that `drivers/of/property.c` already
   parses `panel` for fw_devlink (cite the line).

## Report

`out/hwe/R2/REPORT.md`, under 250 lines: one section per question, a
"Differences downstream vs mainline" table, and an "Unknowns" list for
anything the sources do not settle (say so rather than guessing). Stop after
writing it.
