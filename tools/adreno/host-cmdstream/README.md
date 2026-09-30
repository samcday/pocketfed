# Host-side Adreno command-stream reproduction

Answer "what packets does the Mesa freedreno driver emit for this draw" on an
ordinary x86_64 workstation, with no board, no UART and no GPU, by running a
small GLES harness against the freedreno **drm-shim** and decoding the dump with
`cffdump`.

This was built for [pocketfed#80](https://github.com/samcday/pocketfed/issues/80)
(Adreno A306 GPU hang on the DB410c), where board time is the scarce resource:
every hypothesis that can be phrased as "does this change the command stream,
and only that" is answered here for free, and only the survivors cost a trial.

## What it can and cannot tell you

drm-shim stubs out `DRM_MSM_GEM_SUBMIT`. The command stream is built in full —
same registers, same `CP_LOAD_STATE` packets, same relocs — and then thrown
away. So:

* **Can** show what fd2/fd3/fd4/... emit for a given GL state, byte for byte,
  and diff two variants down to a single bitfield.
* **Cannot** show what the hardware does with those packets. A host run never
  hangs, never renders, and proves nothing about a GPU.

Keep that distinction in anything you write up.

## One-time setup

```sh
git clone https://gitlab.freedesktop.org/mesa/mesa.git
# a3xx-a5xx use the legacy reloc ringbuffer, which never calls msm_dump_rd(),
# so FD_RD_DUMP produces nothing for them.  This patch adds the call, and also
# writes the iova the kernel would have patched in (drm-shim resolves no
# relocs, so without it cffdump cannot follow IB1/IB2).  Instrumentation only:
# it changes nothing about the state the driver emits.
patch -d mesa -p1 < mesa-a3xx-rd-dump.patch

meson setup build-x86 mesa \
  -Dgallium-drivers=freedreno -Dvulkan-drivers= \
  -Dtools=drm-shim,freedreno -Dplatforms= -Dglx=disabled -Degl=enabled \
  -Dgbm=enabled -Dgles2=enabled -Dllvm=disabled -Dvideo-codecs= \
  -Dbuildtype=debugoptimized
ninja -C build-x86
DESTDIR=$PWD/mesa-install meson install -C build-x86 --no-rebuild
```

`-Dbuildtype=debug` is wrong here: it defines `MESA_DEBUG`, which compiles in
`emit_marker()`, which emits an `OUT_WFI` before and after every draw. That is
a pipeline drain inserted into the very stream you are trying to reason about,
and Fedora's build (`%meson` → `--buildtype=plain`) does not have it.

## Building and running the harness

`repro.c` replays a fixed pair of GL calls (a scissored `glClear` and one
`glDrawArraysInstanced`) with the real shaders of the traced application, the
real UBO/VBO sizes and the real `glBindBufferRange`. Edit it for a different
workload; it is deliberately a single file with the call sequence inline.

```sh
mkdir -p repro/shaders
python3 extract-shaders.py /path/to/apitrace-dump.txt repro/shaders
cc -O2 -o repro/repro repro.c -lEGL -lGLESv2
FD_GPU_ID=307 ./run-variant.sh baseline p7 FD_MESA_DEBUG=sysmem
```

`FD_GPU_ID` picks the part: `src/freedreno/drm-shim/freedreno_noop.c` already
carries a306 (`gpu_id = 307`, `chip_id = CHIPID(3,0,6,0)`), so `307` gives a
real a3xx gallium context.

Each run writes `rd/<name>/`:

| file | what |
|---|---|
| `run.log` | harness stderr, including any driver `mesa_logi()` output |
| `repro_submit*.rd` | the raw dump |
| `*.gpuid.rd` | the same with an `RD_GPU_ID` section prepended for `cffdump` |
| `*.cff.txt` | full `cffdump` decode |
| `*.sum.txt` | one line per register write and per `CP_LOAD_STATE`/event |

Diff two arms with `diff rd/a/*.sum.txt rd/b/*.sum.txt`. The summary collapses
addresses, so an intended one-packet change shows up as a one-line diff.

## Validating a host reproduction against a real board

A host stream is only evidence if it matches what the device actually
submitted. The checks that were used in #80, in order of strength:

1. the set of BO sizes in the submit, against the `bos:` list of a devcoredump
   (`crashdec`);
2. the dword count of the main IB, against `CP_IB1_BUFSZ` / the ring decode;
3. the shape of the state around the failing draw — `CP_LOAD_STATE`
   `STATE_SRC`/`STATE_BLOCK`/`NUM_UNIT` and the `HLSQ_*_CONTROL_REG` values —
   against a `.rd` captured on the device, if one can be had.

A devcoredump usually does **not** contain the command BOs (`crashdec` prints
`could not find: <iova>`), which is exactly why the host substitute is worth
building.

## Files

| file | what |
|---|---|
| `repro.c` | the GLES3 surfaceless harness |
| `extract-shaders.py` | pull `glShaderSource` bodies out of an apitrace text dump |
| `run-variant.sh` | run one arm and decode it |
| `add-rd-gpuid.py` | prepend `RD_GPU_ID` so `cffdump` does not segfault on a3xx |
| `summarize-cff.py` | collapse a `cffdump` decode to a diffable summary |
| `mesa-a3xx-rd-dump.patch` | make `FD_RD_DUMP` work for the legacy reloc path |
