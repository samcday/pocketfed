# A3xx recovery clock-reference leak

Source, binary and hardware evidence, 2026-09-23. This addresses Rob Clark's
[recovery question](https://gitlab.freedesktop.org/mesa/mesa/-/work_items/12634#note_3674373).
Two independently booted DB410c sessions now show the same six-clock reference
increment after recovery. A separate [draft kernel correction](https://github.com/samcday/linux/pull/5)
is available for review; it has not been built or tested on hardware.

There is an ignored-error path in the actual Fedora 7.3-rc3 module that matches
the measured accumulation of clock references during recovery. This is separate
from the Mesa trigger; it does not explain the original hang or establish the
cause of the hard resets.

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
RPTR/WPTR `0/198A`. The new clock measurements below repeat this timeout pattern
and directly establish reference growth. The callback return itself has not
been traced, so its exact mechanism remains strongly supported rather than
directly observed at every step.

Recovery holds a runtime-PM reference and invokes the callbacks directly.
It does not request genpd runtime suspension, so callback clock gating and
power-cycling the OXILI GDSC are distinct. `runtime_suspended_time=0` does not
rule out callback-level suspend/resume, and `power/control=on` does not bypass
these explicit recovery calls.

## New hardware measurements

The [hardware trial record](hardware-20260923.md) covers both events using the
unchanged official Fedora kernel:

| Boot / trial | Mesa arm | Hang / recovery / drain timeout uptime | RPTR/WPTR after reset | Compositor result |
| --- | --- | --- | --- | --- |
| B1 / t04 | wait-only, sysmem, minimal trace | 353.776 / 353.798 / 354.870 s | `0/1726` | phoc 1022 crashed with SIGSEGV |
| B2 / t11 | stock, sysmem, minimal trace | 711.728 / 711.750 / 712.822 s | `0/1EBC` | phoc 1109 crashed with SIGSEGV; replacement PID 3213 appeared |

Each event started from its own boot's baseline. In both, these enable **and**
prepare counts changed together:

| GPU bulk clock | Before | After |
| --- | ---: | ---: |
| gcc_oxili_gfx3d_clk | 1 | 2 |
| gcc_oxili_gmem_clk | 1 | 2 |
| gcc_oxili_ahb_clk | 1 | 2 |
| gcc_bimc_gfx_clk | 1 | 2 |
| gcc_bimc_gpu_clk | 1 | 2 |
| gfx3d_clk_src | 3 | 4 |

The neighboring `bimc_gpu_clk_src`, `gcc_gfx_tcu_clk`, and `gcc_smmu_cfg_clk`
counts did not change. Rates were unchanged, and hardware-enable readback was
Y before and after. GPU power policy remained `auto`, runtime status remained
active, and runtime suspended time remained zero. B2's AFTER t11 suspended-time
value is on the following UART line because an audit message interrupted its
label; the recorded value is still zero.

Non-hanging controls t01–t03 and t05–t10 preserved their baseline references.
The B2 controls include full-trace direct-no-wait and direct-wait replays,
followed by separate PNG captures matching the stock+flush reference exactly.
Thus the two measured increases are localized to recovery intervals, rather
than to every replay or direct upload. Process exit 0 and fence retirement
after t04/t11 do not make those hanging trials passes.

## Candidate correction and remaining validation

[samcday/linux #5](https://github.com/samcday/linux/pull/5) targets a dedicated
base at `5dd1818b15d98d4a20806cd00b1b40320b06004f`, matching the measured Fedora
source. It selects generic `msm_gpu_pm_suspend()` specifically during A3xx
recovery, after the existing software reset. Normal runtime suspension keeps
the idle/VBIF drain callback, and other GPU generations retain their callbacks.

The candidate preserves resume and `msm_gpu_hw_init()`: successful resume sets
`needs_hw_init`, without which hardware init could be skipped after reset.
It restores balanced callback-level clock disable/enable; it does not add a
genpd/OXILI power-collapse operation or repair references leaked earlier in a
boot. The broader handling of PM-resume errors remains unchanged.

The patch applies to the exact base and passes whitespace/checkpatch checks.
It is still a draft with no build or patched-kernel boot result. Validation
requires a fresh boot, an actual hang/recovery, stable clock references across
repeated recoveries, successful reinitialization/replay, and ordinary runtime
suspend/resume coverage. The Mesa trigger may remain after recovery accounting
is fixed. Fresh-source indirect and assertion-enabled scheduler controls are
separate pending Mesa experiments.

## Read-only measurement recipe

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

A repeatable increment in GPU leaf-clock enable/prepare counts after recovery,
as observed above, supports the ignored-suspend explanation. Nonzero counts
during normal operation or a shared parent remaining enabled do not. Registered
consumer names are not per-handle vote counts. Compare the hardware-enable
column if available; a nonzero rate alone does not prove a running clock.

These are read-only snapshots, but `clk_summary` may briefly resume clock
providers to read hardware state. Do not describe them as having zero observer
effect. The snapshots themselves require no clock toggles, forced suspends or
new kernel.
