# Trialling a patched Mesa gallium driver on a serial-only aarch64 board

Written while testing a candidate a3xx fix on the DragonBoard 410c for
[pocketfed#80](https://github.com/samcday/pocketfed/issues/80). The board is RAM-rooted, reachable
only over UART, and must not be rebooted — so the driver has to be swapped inside a live session,
with no package install and nothing written to the streamed root.

`build-freedreno-aarch64.sh <workdir> <patch>` does the build. This file is the part that is easy
to get wrong.

## On Mesa 25.1+, the driver is not in `/usr/lib64/dri`

`/usr/lib64/dri/msm_dri.so` and `kgsl_dri.so` are symlinks to `libdril_dri.so`, a small stub that
exists so an X server can still load "a DRI driver". The real driver is the gallium megadriver
`/usr/lib64/libgallium-<version>.so`, and it is a plain **`DT_NEEDED` of `libEGL_mesa.so.0`**
(and of `gbm/dri_gbm.so`). Nothing dlopens it out of `LIBGL_DRIVERS_PATH`.

Neither library carries `RPATH` or `RUNPATH`, so the override is just `LD_LIBRARY_PATH`, and you
can confirm it for free before spending any board time:

```sh
LD_LIBRARY_PATH=/run/mesa-fix ldd /usr/lib64/libEGL_mesa.so.0 | grep gallium
#   libgallium-26.2.2.so => /run/mesa-fix/libgallium-26.2.2.so
```

For proof from inside the process that actually ran, use `LD_DEBUG=libs` and look for
`calling init: /run/mesa-fix/libgallium-<version>.so`. An `ldd` says the link *would* resolve;
only the loader trace says it *did*.

## Check the symbol set before you ship megabytes down a serial line

A driver-specific build still has to satisfy everything the stock loader imports. Compare against
the stock libraries from the same NVR:

```sh
for f in libEGL_mesa.so.0 gbm/dri_gbm.so dri/libdril_dri.so; do
  nm -D --undefined-only "stock/usr/lib64/$f" | awk '{print $2}' |
    grep '@libgallium' | sed 's/@libgallium.*//'
done | sort -u > required.txt
nm -D --defined-only libgallium-26.2.2.so | awk '$2 ~ /^[TDBRWVi]$/ {print $3}' |
  sed 's/@@.*//' | sort -u > built.txt
comm -23 required.txt built.txt      # must be empty
```

72 symbols in that set for Mesa 26.2.2, including `kopper*` (provided by `kopper_stubs.c` when zink
is off), `loader_dri3_*` (only built with `-Dplatforms=x11,…`, even when the app runs on Wayland
via Xwayland) and `driSWRastQueryBufferAge`. The symbol-version node is named after the library, so
the built `SONAME` must match the stock one exactly.

## Do not build `-Dbuildtype=debug` for a cmdstream experiment

`debug` sets `MESA_DEBUG=1`, which enables `emit_marker()` — and on freedreno `emit_marker()` emits
an `OUT_WFI(ring)` before its scratch-register write, immediately before and after **every** draw
(`freedreno_util.h`, `freedreno_draw.h`). If what you are testing is whether the pipeline being
busy matters, a debug build silently answers the question for you. Fedora's `%meson` builds
`--buildtype=plain`, so `debugoptimized` is the flag that keeps the cmdstream comparable.

## Prove the patched code path ran, not just that the file loaded

`fd_wfi()` and friends are gated on driver state. A patch that is present in the binary can still
be a no-op at runtime, which turns "refuted" into "untested". A few lines of `mesa_logi()` around
the patch site — logging the gate and `ring->cur` either side — cost one extra build and settle it:
an 8-byte advance is one `CP_WAIT_FOR_IDLE` that really reached the cmdstream. `mesa_logi` output
lands on stderr, which is already being captured.

## Shipping it

```sh
xz -9 libgallium-26.2.2.so                      # 22 MB -> 3.7 MB for a freedreno-only build
tools/adreno/uart/uart-push.py --src … --dst /run/mesa-fix/libgallium-26.2.2.so.xz
# on the guest: unxz, chmod 755, sha256sum, then LD_LIBRARY_PATH=/run/mesa-fix
```

~5.3 kB/s, so about 12 minutes. Fedora's all-drivers `libgallium` is 40.9 MB (9.2 MB compressed,
~20 minutes); `-Dgallium-drivers=freedreno -Dllvm=disabled` is what buys the difference. Keep it
under `/run` so a reboot cleans up after you, and check the tmpfs has room first.

## Emulated builds are fine

The whole thing builds in a Fedora aarch64 container under qemu-user-static: 9 minutes wall for
1171 targets on 32 emulated cores (217 minutes of CPU). Cross-compiling would be faster but needs
an aarch64 sysroot for a dozen X11/Wayland libraries; emulation needs one `--arch arm64`.
