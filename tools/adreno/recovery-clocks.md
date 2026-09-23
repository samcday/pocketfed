# A3xx recovery clock-reference leak

Source, binary and hardware evidence, 2026-09-23. This addresses Rob Clark's
[recovery question](https://gitlab.freedesktop.org/mesa/mesa/-/work_items/12634#note_3674373).
Six independently booted DB410c sessions now show the same six-clock reference
increment after recovery. A separate [draft kernel correction](https://github.com/samcday/linux/pull/5)
is available for review. The matching Fedora module now loads and keeps all
six clocks balanced across two real recoveries; rendering works afterward.
Ordinary idle suspend remains unresolved and is being checked against stock.

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
and directly establish reference growth. Scoped B5/B6/B8 kretprobes now directly
confirm the recovery suspend returning `-EBUSY`, followed by successful resume
without a generic suspend call. All three captures have zero missed probes and
zero per-CPU buffer overruns/dropped events.

Recovery holds a runtime-PM reference and invokes the callbacks directly.
It does not request genpd runtime suspension, so callback clock gating and
power-cycling the OXILI GDSC are distinct. `runtime_suspended_time=0` does not
rule out callback-level suspend/resume, and `power/control=on` does not bypass
these explicit recovery calls.

## New hardware measurements

The [hardware trial record](hardware-20260923.md) covers these events using the
unchanged official Fedora kernel:

| Boot / trial | Mesa arm | Hang / recovery / drain timeout uptime | RPTR/WPTR after reset | Compositor result |
| --- | --- | --- | --- | --- |
| B1 / t04 | wait-only, sysmem, minimal trace | 353.776 / 353.798 / 354.870 s | `0/1726` | phoc 1022 crashed with SIGSEGV |
| B2 / t11 | stock, sysmem, minimal trace | 711.728 / 711.750 / 712.822 s | `0/1EBC` | phoc 1109 crashed with SIGSEGV; replacement PID 3213 appeared |
| B3 / t12 | fresh-source indirect, sysmem, minimal trace | 162.738 / 162.760 / 163.826 s | `0/180E` | phoc 1059 crashed with SIGSEGV; absent from final process check |
| B5 / t13 | stock with assertions, sysmem, minimal trace | 223.729 / 223.751 / 224.823 s | `0/1F32` | phoc 1065 crashed with SIGSEGV |
| B6 / t14 | !44620 with assertions, sysmem, minimal trace | 389.743 / 389.766 / 390.837 s | `0/7E0` | phoc 1055 crashed with SIGSEGV |
| B8 / t15 | checked-wait, sysmem, minimal trace | 221.744 / 221.766 / 222.838 s | `0/15EA` | phoc 1029 crashed with SIGSEGV |

Each event started from its own boot's baseline. In all six, these enable **and**
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
Thus the measured increases are localized to recovery intervals, rather
than to every replay or direct upload. Process exit 0 and fence retirement
after these recoveries do not make those hanging trials passes. In particular,
`recover_worker()` advances the guilty fence in software before the generation
recovery callback dumps state; later printed fence equality does not establish
GPU progress beyond the authoritative pre-recovery devcoredump.

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
The affected `adreno_gpu.o`, `a3xx_gpu.o`, and `msm_gpu.o` also cross-compile
for ARM64 against that base with upstream arm64 defconfig. Logs, configuration,
compiler provenance and the build script are archived under
`out/adreno-rob-20260923/recovery-evidence/kernel-cross-compile/`. This bounded
compile used upstream defconfig, separately from the Fedora module build below.

The complete `msm.ko` now also builds against the exact shipped Fedora
`kernel-devel` configuration, generated headers and `Module.symvers`, using
the matching ARM64 GCC/linker in the Fedora container. The configuration and
symbol table match the fixture byte-for-byte; all 292 relevant source files
match the Fedora source RPM before applying the recovery patch. The linked
module has the exact stock vermagic, the same 784 imported symbols and ten
dependencies, and the intended A3xx-specific suspend branch. These establish static
compatibility; the separate B9 load and recovery results are recorded below.

The candidate uses the kernel's XZ CRC32/1-MiB dictionary settings. Its archive
SHA-256 is `f128ed08e25e826e6c714c1a3aa2e718d1450f3e63356d05c4bc8cfe0ab7bfe1`
and ELF build ID is `8781436f3c1601233e20bdb11e67be06244fe222`. Build logs,
configuration, source/package provenance, disassembly and the candidate are
archived under `out/adreno-rob-20260923/recovery-evidence/fedora-module/`.
It is an unsigned external module with module BTF generation skipped because
the development package lacks `vmlinux`; it is not a bit-for-bit Fedora build.
B9 loaded this exact candidate, verified from its live module-note hash, with
the expected unsigned/external taint flags (12288).

B9 stock/sysmem minimal trials t16 and t18 both exercise actual GPU recovery.
Generic suspend and resume each return 0, the stale-ring drain timeout is
absent, and all six clock counts remain balanced after both recoveries. Both
scoped captures have zero missed probes/buffer loss and successful cleanup.
The original Mesa hangs and compositor SIGSEGVs remain. Between recoveries,
t17 completes full R3 with stock+sysmem,flush after the display service's
automatic restart; its captured PNG matches the earlier reference byte-for-byte.
See the [hardware ledger](hardware-20260923.md) for fences, times and dump hashes.

Ordinary runtime-PM coverage is still unresolved. In t19, stopping the display
service leaves no DRM clients, but the normal A3xx callback returns `-EBUSY`;
the GPU stays active and generic suspend/resume is never called. The display
service was restored, and all probes were saved/cleaned up. Because this check
followed two recoveries, a clean stock-kernel comparison is needed to distinguish
a preexisting idle-suspend problem from any candidate regression. The PR remains
a draft while that comparison is in progress.

## Read-only measurement recipe

The optional [return-tracing helper](trace-recovery-returns.sh) creates a
dedicated trace instance and uniquely named kretprobes for `a3xx_pm_suspend`,
`msm_gpu_pm_suspend` and `msm_gpu_pm_resume`. It records signed return values,
hit/miss counts and buffer-loss statistics, then removes only its own probes.
Run it as root in the guest with an already mounted tracefs; it starts no
workload and changes no power policy:

```sh
bash /run/trace-recovery-returns.sh start /run/a3xx-returns-t13
# Capture clocks, run the selected replay, then capture clocks/kernel messages.
bash /run/trace-recovery-returns.sh stop /run/a3xx-returns-t13
```

The script passes `bash -n`, ShellCheck and pure argument/probe-definition
checks. Configuration, symbols and syntax were checked against the exact
Fedora inputs. It was successfully used on B5/t13, B6/t14 and B8/t15, with
zero missed probes and zero buffer loss. The recovery return pairs came from `adreno_recover+0x34`
(suspend `-16`) and `+0x44` (resume 0); other failed suspend returns came from
`adreno_runtime_suspend` and must not be conflated with recovery. Trace
instance cleanup succeeded on all three runs. Preserve its state directory
before reboot. Missing events are inconclusive if probes were missed, buffers
overflowed or a callback never returned. Probes add overhead; use the same
setup for baseline and candidate comparisons. A zero return alone does not
prove a power collapse or successful GPU work.

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
