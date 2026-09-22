# A3xx recovery clock hypothesis

Read-only source and binary audit, 2026-09-23. This addresses Rob Clark's
[recovery question](https://gitlab.freedesktop.org/mesa/mesa/-/work_items/12634#note_3674373).
No new hardware measurement or kernel change has been made.

There is an ignored-error path in the actual Fedora 7.3-rc3 module that could
accumulate clock references during recovery. This is separate from the Mesa
trigger; it does not explain the original hang or establish the cause of the
hard resets.

## Verified code path

The fixture runs `7.3.0-0.rc3.260918g5dd1818b15d9.36.fc46.aarch64`.
Its upstream base is `5dd1818b15d98d4a20806cd00b1b40320b06004f`.
Disassembly of the shipped, decompressed `msm.ko` confirms the relevant control
flow; module SHA-256:
`832fff363ccb21890c8c3bdf6e63062530090f5cb38cf9b7b53f840eeb61ed93`.

1. [`a3xx_recover()`](https://github.com/torvalds/linux/blob/5dd1818b15d98d4a20806cd00b1b40320b06004f/drivers/gpu/drm/msm/adreno/a3xx_gpu.c#L362)
   toggles `RBBM_SW_RESET_CMD`, then calls `adreno_recover()`.
2. [`adreno_recover()`](https://github.com/torvalds/linux/blob/5dd1818b15d98d4a20806cd00b1b40320b06004f/drivers/gpu/drm/msm/adreno/adreno_gpu.c#L716)
   calls the suspend and resume callbacks consecutively, ignoring both returns.
   The Fedora module's two indirect calls have no return-value test between them.
3. [`a3xx_pm_suspend()`](https://github.com/torvalds/linux/blob/5dd1818b15d98d4a20806cd00b1b40320b06004f/drivers/gpu/drm/msm/adreno/a3xx_gpu.c#L519),
   added by `be0e82b8e0c96649b8bc77a99ab0d185243b7659`, first drains the ring
   and halts VBIF. Failure returns before generic suspend disables the clocks.
4. Generic [`msm_gpu_pm_resume()`](https://github.com/torvalds/linux/blob/5dd1818b15d98d4a20806cd00b1b40320b06004f/drivers/gpu/drm/msm/msm_gpu.c#L100)
   enables those clocks again. If suspend failed before the balancing disable,
   a successful resume increments their reference counts.

A software reset may zero hardware RPTR while the software WPTR still describes
the old submission. The existing [W6 report](https://github.com/samcday/pocketfed/issues/80#issuecomment-5758800870)
records recovery followed one second later by a ring-drain timeout with
RPTR/WPTR `0/198A`. This is consistent with the path above; clock counts have
not yet been measured to complete the causal chain.

Recovery holds a runtime-PM reference and invokes the callbacks directly.
It does not request genpd runtime suspension, so callback clock gating and
power-cycling the OXILI GDSC are distinct. `runtime_suspended_time=0` does not
rule out callback-level suspend/resume, and `power/control=on` does not bypass
these explicit recovery calls.

## Discriminating measurement

On one boot, capture the following before and after a naturally occurring
recovery, keeping the existing power policy and workload conditions fixed:

```sh
cat /proc/uptime
for p in /sys/bus/platform/devices/1c00000.gpu/power/control \
         /sys/bus/platform/devices/1c00000.gpu/power/runtime_status \
         /sys/bus/platform/devices/1c00000.gpu/power/runtime_active_time \
         /sys/bus/platform/devices/1c00000.gpu/power/runtime_suspended_time; do
    [ ! -r "$p" ] || { printf '%s: ' "$p"; cat "$p"; }
done
cat /sys/kernel/debug/clk/clk_summary
cat /sys/kernel/debug/pm_genpd/pm_genpd_summary
dmesg | grep -E 'hangcheck|recover|timeout waiting|VBIF|hw init failed'
```

Keep the complete clock table, including its header and consumer continuation
lines. The actual DB410c DTB supplies GPU clocks `gcc_oxili_gfx3d_clk`,
`gcc_oxili_ahb_clk`, `gcc_oxili_gmem_clk`, `gcc_bimc_gfx_clk`,
`gcc_bimc_gpu_clk`, and `gfx3d_clk_src`. The IOMMU has separate clocks.

A repeatable increment in GPU leaf-clock enable/prepare counts after each failed
recovery would support the ignored-suspend explanation. Nonzero counts during
normal operation or a shared parent remaining enabled do not. Registered
consumer names are not per-handle vote counts. Compare the hardware-enable
column if available; a nonzero rate alone does not prove a running clock.

These are read-only snapshots, but `clk_summary` may briefly resume clock
providers to read hardware state. Do not describe them as having zero observer
effect. No clock toggles, forced suspends or new kernel are needed for this
first discrimination.
