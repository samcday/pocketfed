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
Each dump has one other 32-KiB payload that this decoder rejects with an
Ascii85 overflow; the results are not an exhaustive decode of the dump.
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
   FD_BO_PREP_READ)` before the unchanged indirect emission, with the return
   value recorded. Verify the emitted stream remains unchanged.
2. Repeat **direct without prep** with matched instrumentation, ideally
   without per-upload logging, using the known CPU-initialized reproducer.
   Include **direct with prep** to complete the transport/wait comparison.
3. Test !44620 independently on stock transport with assertions active and a
   fresh shader cache, rather than mixing it with B2 in the first comparison.
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
