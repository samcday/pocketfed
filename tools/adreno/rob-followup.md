# A3xx investigation: Rob Clark follow-up

Status: **host-side evidence audit, 2026-09-23**. No new hardware results are
recorded here. The older B2 patch is an experimental workaround, not a proven
root-cause fix.

Tracking: [PocketFed #80](https://github.com/samcday/pocketfed/issues/80).
Upstream: [Rob's reply on Mesa #12634](https://gitlab.freedesktop.org/mesa/mesa/-/work_items/12634#note_3674373).

## Questions to resolve

Rob points out that, on a5xx and later, the firmware handles direct and indirect
loads similarly apart from the source address. He asks whether B2's added CPU
wait is what matters, requests the constant-upload size and a devcoredump, and
suggests testing [Mesa !44620](https://gitlab.freedesktop.org/mesa/mesa/-/merge_requests/44620)
with assertions enabled. That firmware observation is a hypothesis for a3xx,
not a demonstrated explanation of this failure.

Keep assertion coverage separate from Mesa's `MESA_DEBUG` build mode: the earlier
trial notes report that `buildtype=debug` adds freedreno draw markers containing
extra `CP_WAIT_FOR_IDLE` packets. Use `debugoptimized` with `b_ndebug=false`,
verify the effective configuration, and disable the shader cache when changing
compiler behavior. A successful build alone is not a hardware test.

## Existing direct upload without a CPU wait

The original V3 experiment already omitted `fd_bo_cpu_prep()` entirely.
[Trials 4 and 8](https://github.com/samcday/pocketfed/issues/80#issuecomment-5757485832)
passed the B8 minimal pair under `FD_MESA_DEBUG=sysmem` on one DB410c boot,
while the no-knob control and split-indirect arm hung on that boot. Its log
identifies the changed FS upload: `regid=32 sizedwords=64 bo_off=576`.

The source in
`outputs/db410c-adreno-20260921/mesa-variants/fd3-a3xx-fs-const-knobs.patch`
does `fd_bo_map()` followed by `fd3_emit_const_user()` for the fragment stage;
there is no CPU prep. The library SHA-256 recorded in the guest was
`a7f7a9fdb7bf7c5ba7181618e0dcf216ab53f9ad217c63ede092a092b1ec2a3b`.

This means the later addition of a CPU wait is **not necessary to explain those
two V3 passes**. It does not establish that every indirect upload is faulty:
V3 also changes command-buffer contents and length, performs a CPU mapping and
copy, and logs during emission. It has no general synchronization guarantee for
a GPU-written source. Both successful trials used the same reduced workload.

## Upload size: hardware dumps and host evidence

For a3xx shader `ST_CONSTANTS`, one `NUM_UNIT` is **two dwords / eight bytes**.
Both `fd3_emit_const_user()` and `fd3_emit_const_bo()` encode
`NUM_UNIT = sizedwords / 2`; `DST_OFF = regid / 2`. Consequently:

| Stage | DST_OFF | NUM_UNIT | Payload | Destination within that stage |
| --- | ---: | ---: | ---: | --- |
| VS | 16 | 16 | 32 dwords / 128 bytes | vec4 8 through 15 |
| FS | 16 | 32 | 64 dwords / 256 bytes | vec4 8 through 23 |

The B10 **hardware** minimal-pair dump was decoded again during this audit:

```text
revision: 307 (03000600)
rbbm-status: 0xe0684003
retired-fence: 19611; last-fence: 19614
command BO: 0x02a80000
+0x488: SS_INDIRECT SB_VERT_SHADER DST_OFF=16 NUM_UNIT=16 src=0x01cd5240
+0x558: SS_INDIRECT SB_FRAG_SHADER DST_OFF=16 NUM_UNIT=32 src=0x01cd5240
```

Source artifact:
`outputs/db410c-adreno-20260921/b10-minimal-pair-sysmem.devcore.xz`.
The decompressed file is 94,309 bytes, SHA-256
`ae7e58f0f454c3b8f2cc6937fa3d3ffe05a36cc37d2987eb6493b16397e348aa`.
This is the dump discussed in the
[register analysis](https://github.com/samcday/pocketfed/issues/80#issuecomment-5757144553).

The later **hardware** full-trace dump independently contains two FS loads of
256 bytes and nine VS loads of 128 bytes:

```text
command BO: 0x0348c000
+0x20a4: SS_INDIRECT SB_FRAG_SHADER DST_OFF=16 NUM_UNIT=32 src=0x03082180
+0x2794: SS_INDIRECT SB_FRAG_SHADER DST_OFF=16 NUM_UNIT=32 src=0x03082240
```

Source: `w6-stock-sysmem.devcore` in the re-provisioning experiment's `outputs/`;
138,812 bytes, SHA-256
`d9d816d85de388651bf7ec791325adf8808ddcba136e99ccaa76cde40efe96a5`.
Its [trial report](https://github.com/samcday/pocketfed/issues/80#issuecomment-5758800870)
records retired/submitted fences 9767/9770 and the same RBBM status.

The scans use the decoder from [PocketFed #89](https://github.com/samcday/pocketfed/pull/89).
The original scanner incorrectly consumed following YAML section labels as
Ascii85 data. The follow-up fix in #89 stops at the end of the indented literal
block. B10 now decodes all nine payloads without warnings; its indirect-constant
packet counts remain one VS and one FS. The earlier overflow was a parser bug,
not evidence that the captured payload itself was corrupt.
These are packets present in a hung submission, not proof of the exact packet
being executed at the instant of the hang. Raw dumps remain outside Git.

The separate **host drm-shim** comparison at
`outputs/a5u-stk-a3xx-20260922/db410c-drm-shim-b2-vs-stock.txt` confirms the same
VS/FS sizes. B2 changes those two loads to direct uploads with identical
payloads, initialized with a nonzero pattern for the comparison. Both source
ranges start at byte 576. The bound UBO range is 160 bytes, so the FS upload
extends 96 bytes beyond the binding, while remaining inside the 16-KiB BO.
This is distinct from overrunning the destination constant window. The
drm-shim does not execute GPU work.

## Corrections needed before presenting B2 upstream

Source audit baseline: Mesa main
`ee9edd46254884ab7fe6c96518e23d421d5f5344`.

- **READ prep also waits for earlier readers.**
  [`fd_bo_cpu_prep()`](https://gitlab.freedesktop.org/mesa/mesa/-/blob/ee9edd46254884ab7fe6c96518e23d421d5f5344/src/freedreno/drm/freedreno_bo.c#L684)
  waits all attached fences, irrespective of `FD_BO_PREP_READ`. An immutable,
  CPU-written UBO or shader BO can still have outstanding GPU readers. The
  claim that those waits necessarily cost nothing is incorrect. Its flush
  operates on existing submission fences, not arbitrary unsubmitted Gallium
  batches. B2 also ignores the prep return value.
- **Shader constant data is not converted.**
  [`upload_shader_variant()`](https://gitlab.freedesktop.org/mesa/mesa/-/blob/ee9edd46254884ab7fe6c96518e23d421d5f5344/src/gallium/drivers/freedreno/ir3/ir3_gallium.c#L87)
  allocates `v->bo` with `FD_BO_NOMAP`; `fd_bo_map()` explicitly returns NULL
  for that flag. Thus `ir3_emit_constant_data()` reaches B2's indirect fallback.
  The same allocation flag is present in the 26.2.2 source used for the DB410c
  artifact. B2 does not eliminate every indirect constant load.
- **The GTK minimal pair contains both stages' indirect loads.** The B2 commit
  message still says only the fragment stage produces one. That is contradicted
  by both the hardware dump and the host stream. The fragment-only workaround
  succeeds for this workload; this does not make the vertex packet universally
  safe or universally faulty.
- **Separate implementations and observations.** The earlier DB410c results
  cover V3 and Patch A, not the widened B2 binary. B2's documented hardware
  result is the A5 SuperTuxKart run. Sam’s upstream report records 762 frames in 71,353 ms for B2 versus
  121,733 ms for `nouboopt` (one run each, not a controlled performance study).
  Device power-offs and recoverable GPU hangs have not been shown to share a mechanism.

The emitter's size conversion is in
[`fd3_emit.c:43–80`](https://gitlab.freedesktop.org/mesa/mesa/-/blob/ee9edd46254884ab7fe6c96518e23d421d5f5344/src/gallium/drivers/freedreno/a3xx/fd3_emit.c#L43).
The `FD_BO_NOMAP` check is in
[`freedreno_bo.c:641`](https://gitlab.freedesktop.org/mesa/mesa/-/blob/ee9edd46254884ab7fe6c96518e23d421d5f5344/src/freedreno/drm/freedreno_bo.c#L641).

## Outstanding controls

1. Stock versus **wait-only**: add exactly B2's `fd_bo_cpu_prep(bo, NULL,
   FD_BO_PREP_READ)` before the unchanged indirect emission. Verify the emitted
   stream remains unchanged. The matched control below ignores the return as
   B2 does; separately instrument errors if the hardware result needs it.
2. Repeat **direct without prep** with matched instrumentation, ideally
   without per-upload logging, using the known CPU-initialized reproducer.
   Include **direct with prep** to complete the transport/wait comparison.
3. Test !44620 independently on stock transport with assertions active and a
   fresh shader cache. The host compiler check below is complete; actual GPU
   replay with this build remains outstanding.
4. Check a fresh-source indirect arm if the results still implicate transport:
   copy the same range into a new BO and leave the upload indirect. This helps
   separate the original source BO's history from the packet mode.
5. Capture fences, hangchecks and output pixels; prove the override library is
   actually loaded. Reserve broad workload/performance claims until measured.

Patch C remains a separate bounds investigation. Its proposed clamp rounds the
remaining binding size **up** to 16 bytes on a3xx or 64 bytes on later gens;
therefore it does not generally prevent reading past a nonaligned binding.
For example, four remaining bytes still request 16/64 bytes. A complete fix
needs to account for real allocation padding or copy a partial final unit into
padded storage. Its claim that later generations can never shrink is also too
broad when the runtime binding is shorter than the compiled range. Do not add
Patch C to the synchronization experiments.

## Wait-only artifact, built 2026-09-23

[`fd3-const-wait-only.patch`](fd3-const-wait-only.patch) is a diagnostic against
Mesa 26.2.2. It adds the same CPU prep call as B2, leaving the indirect packet
and relocation intact. Like B2 it ignores the return value; this is intentional
for the matched control, not a proposed production error-handling policy.
It contains neither B2 nor Patch A/C nor the scheduler MR.

The aarch64 Fedora 46 build completed using the existing
`localhost/mesa-freedreno-build:f46` image and the previous 26.2.2 build tree,
copied into isolated scratch storage. Effective flags remain
`buildtype=release`, `b_ndebug=true`, `MESA_DEBUG=0`. This artifact therefore
**does not** satisfy Rob's separate assertion-enabled scheduler test.

The resulting stripped `libgallium-26.2.2.so` SHA-256 is
`f32ae90f49acabe08f3ba2df6da008f067fb5d51588470a791a6fc8d4ad5279b`.
Its exported symbols match the earlier hardware-tested Patch A library;
all symbols expected from Gallium by Fedora's `libEGL_mesa`, `libGLX_mesa`
and `gbm/dri_gbm.so` are present, including all 18 `loader_dri3_*` symbols.
This static ABI check does not establish runtime loading or GPU behavior.

Apply to an otherwise stock 26.2.2 tree, then use the full Fedora-compatible
build configuration from [PR #86](https://github.com/samcday/pocketfed/pull/86)
(`platforms=x11,wayland`, `glx=dri`, `glvnd=enabled` matter for the loader ABI):

```sh
patch -p1 --dry-run < /path/to/fd3-const-wait-only.patch
patch -p1 < /path/to/fd3-const-wait-only.patch
ninja -C build src/gallium/targets/dri/libgallium-26.2.2.so
```

Before a trial, prove that `/usr/lib64/libEGL_mesa.so.0` resolves Gallium from
the override directory with `LD_LIBRARY_PATH=... ldd`, and check `ldd -r`.
Do not inspect only libglvnd's `/usr/lib64/libEGL.so.1`, which loads the vendor
library dynamically. Do not use a 26.2.2 override against a 26.2.3 soname.

## Matched upload controls

Four aarch64 26.2.2 libraries were built with the same release configuration.
Each has the same exported-symbol set and passes the Fedora front-end static
ABI gate. These are experiments restricted to the known CPU-initialized trace,
not general replacements for Mesa. In particular, a CPU read without prep is
not safe for an arbitrary GPU-written source.

| Arm | Patch against stock | CPU prep | BO-backed upload |
| --- | --- | --- | --- |
| stock | none | none | indirect |
| wait | [wait-only](fd3-const-wait-only.patch) | READ | indirect |
| direct-no-wait | [direct-no-wait](fd3-const-direct-no-wait.patch) | none | direct if mapping succeeds |
| direct-wait | [direct-with-wait](fd3-const-direct-with-wait.patch) | READ | direct if mapping succeeds |

Apply exactly one patch per otherwise identical source tree. The direct arms
retain B2's indirect fallback when the BO cannot be mapped; this includes
`FD_BO_NOMAP` shader buffers. No per-upload logging is added. The direct-wait
arm implements B2's relevant operations, but is a newly built matched control,
not the previously tested B2 artifact. Verify actual packet modes on the trace
before attributing a result to transport.

Review raised the direct-wait arm's ignored prep error. This is a real defect
for a general-purpose upload path, retained here solely to match B2 in the
restricted CPU-initialized reproducer. A production change must handle that
error before reading the BO. Changing to indirect on failure would also change
this experiment's transport, so an error cannot be interpreted as a successful
direct-with-wait trial. These controls do not establish that CPU preparation
completed successfully; investigate prep/fence errors separately if observed.

Stripped-library SHA-256 values:

```text
ff153c4a2d69a00f5837ba6363bdf0b111603c072724a91484aa4cd72eaf4b50  stock
f32ae90f49acabe08f3ba2df6da008f067fb5d51588470a791a6fc8d4ad5279b  wait
dcbd8c923a9b4550da77f40485d897ff765f7a10512757b00482347165a2dc62  direct-no-wait
5c15029f0dcfa3802caa943e15d54fffe6eac392dd68aa79a23a005dff6b3242  direct-wait
```

## Assertion-enabled host compiler checks

Mesa 26.2.2 release commit `3281a69a8bfd9f997e91c15ed0e6290cae12dd32`,
GCC 16.2.1, `debugoptimized`, `b_ndebug=false`, `MESA_DEBUG=0`;
freedreno drm-shim `FD_GPU_ID=307`, `FD_MESA_DEBUG=sysmem`, cache disabled.
The compared MR comprises commits `96a8da8d8de07b2a58e10b8d206401436c6ececc`
and `3bab7e568ef5c3863f9cda9b600f9e67448d25bf`. Its new assertion expression
is present in the built library.

- Baseline and MR both compile/run p3 and rounded-clip p7 in the host harness,
  with no assertion or GL error. Their decoded shader instruction lines are
  identical between arms, with no kill/discard/demote instructions.
- All ten GLSL sources from R3 (five VS/FS pairs) contain no `discard`. The
  remaining three pairs also compile with the MR without assertion failures. Their
  generic harness draw state is not a replay of their original trace state.
- Mesa's `ir3_delay_test` and `ir3_disasm` pass on both baseline and MR (2/2
  each). The complete R3 apitrace was not replayed successfully on the host;
  headless eglretrace could not open a display.
- With the MR removed and wait-only applied, p7's normalized packet/register
  summary and shader instructions remain identical to baseline. Both indirect
  loads remain, and their 32/64-dword payloads match the nonzero source pattern.

Normalized p7 packet/register summary SHA-256 (all three arms):
`ddfbbf0b44fb4209a679258434815b9efd9ee7121c5edc85e95451873ffb3f7c`.
Decoded p7 instruction-lines SHA-256 (all three arms):
`4ad8eadcd2456ef80214e2a3f2cf9dd837644920d56c5f4e66bb2712275fa333`.
Raw dumps contain differing BO addresses and are not byte-identical.

The existing B10 **hardware** dump also preserves the fragment shader object
named by `SP_FS_OBJ_START_REG`: BO `0x02969000`, 13,792 captured bytes. Its
1,724 instruction slots contain no kill/discard/demote and end with `end`.
The command buffer programs `SP_FS_LENGTH_REG=431`, or 13,792 bytes. Every
captured byte matches the host baseline-p7 fragment shader in the raw RD file;
the remaining 2,592 bytes of that 16-KiB host BO are zero. The disassembler
includes four zero padding slots; the kernel dump writer trims trailing zero
dwords. The shader-object SHA-256 after converting the dump
words to little-endian is
`6b277e86d377c9497a3d6c9c8fc55fa9300627c937d42b8ef68907f12f19d788`.
This links the host-tested variant to the captured hardware shader; a saved
object pointer does not prove which instruction was executing at the hang.

The tested p7 variant does not exercise the specific cross-block kill/bary.f
condition checked by !44620. It does not exclude other compiler bugs or say
anything about shaders in SuperTuxKart. The shim submits no GPU work, so these
checks do not establish a hardware fix or a real GPU wait.

## Assertion-enabled board pair and prepared fixture

The aarch64 `sched` and `stock-asserts` libraries are also built. Both use
`debugoptimized`, `b_ndebug=false`, `MESA_DEBUG=0`, `-O2`, and no `-DNDEBUG`;
they differ only by the two !44620 commits. The MR's new assertion expression
is present only in `sched`. Both pass the same Fedora EGL/GLX/GBM static ABI
gate as the four transport arms.

```text
d05d68f997ddbef7646fa8bf070db5a343e0134b50abe2f094a55f2fd948a804  sched
48101a6bb28facb30c5295d0902c202be25c2e65b322e65079b747cba4984ceb  stock-asserts
```

Compare these two to each other, not to the release/O3 transport controls,
when attributing a change to the scheduler MR.

A new local root-image copy contains all six libraries and the minimal trace.
Its boot image preserves the previous kernel, initramfs and device tree; only
the root export ID and trial identifier change in the command line. Original
image hashes remain unchanged. The baked payload checksums and a read-only
filesystem check pass. The images, raw evidence, build logs and upstream reply
draft remain in ignored local artifacts. Runtime loader checks, physical GPU
replays and recovery-clock measurements are still pending.

See [recovery-clocks.md](recovery-clocks.md) for the separate, still unmeasured
recovery-clock hypothesis and the read-only snapshots needed to test it.
