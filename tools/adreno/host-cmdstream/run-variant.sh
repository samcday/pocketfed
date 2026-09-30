#!/bin/bash
# Run the host reproducer under the freedreno drm-shim, dump the command stream
# it would have submitted, and decode it with cffdump.
#
# Nothing is executed on a GPU: drm-shim stubs out DRM_MSM_GEM_SUBMIT, so this
# only ever answers "what packets does fd3 emit", never "what does the hardware
# do with them".
#
# usage: run-variant.sh <name> <p3|p7> [KEY=VALUE ...]
#
# Environment:
#   MESA_BUILD   meson build dir of a Mesa tree built with -Dgallium-drivers=freedreno
#                -Dtools=drm-shim,freedreno (default: $PWD/build-x86)
#   MESA_INSTALL DESTDIR that build was installed into (default: $PWD/mesa-install)
#   REPRO        the compiled harness  (default: $PWD/repro/repro)
#   OUTDIR       where to write dumps  (default: $PWD/rd)
set -euo pipefail

name=${1:?name}
prog=${2:?p3 or p7}
shift 2

HERE=$(cd "$(dirname "$0")" && pwd)
MESA_BUILD=${MESA_BUILD:-$PWD/build-x86}
MESA_INSTALL=${MESA_INSTALL:-$PWD/mesa-install}
REPRO=${REPRO:-$PWD/repro/repro}
OUTDIR=${OUTDIR:-$PWD/rd}

L=$MESA_INSTALL/usr/local/lib64
out=$OUTDIR/$name
rm -rf "$out"; mkdir -p "$out"

# env -i so a stray FD_MESA_DEBUG/IR3_SHADER_DEBUG in the caller's shell cannot
# silently change the arm under test.  MESA_SHADER_CACHE_DISABLE matters for any
# knob that changes *compilation*: without it the disk cache happily serves a
# variant compiled by the previous arm.
env -i HOME="$HOME" PATH=/usr/bin \
  REPRO_DIR="$(dirname "$REPRO")" \
  __EGL_VENDOR_LIBRARY_FILENAMES="$MESA_INSTALL/usr/local/share/glvnd/egl_vendor.d/50_mesa.json" \
  LD_LIBRARY_PATH="$L" LD_PRELOAD="$L/libfreedreno_noop_drm_shim.so" \
  MESA_LOADER_DRIVER_OVERRIDE=msm FD_GPU_ID=307 EGL_PLATFORM=surfaceless \
  MESA_SHADER_CACHE_DISABLE=true \
  FD_RD_DUMP=enable,full FD_RD_DUMP_PATH="$out" \
  "$@" \
  "$REPRO" "$prog" > "$out/run.log" 2>&1

# cffdump segfaults on a Mesa-written a3xx .rd: the file carries only
# RD_CHIP_ID, fd_dev_info_raw() returns NULL for it and rnn stays NULL.
# Prepending a 4-byte RD_GPU_ID section fixes it.
for f in "$out"/*.rd; do
  python3 "$HERE/add-rd-gpuid.py" "$f" "${f%.rd}.gpuid.rd" > /dev/null
  "$MESA_BUILD/src/freedreno/decode/cffdump" --no-color "${f%.rd}.gpuid.rd" \
    > "${f%.rd}.cff.txt" 2>&1
  python3 "$HERE/summarize-cff.py" "${f%.rd}.cff.txt" > "${f%.rd}.sum.txt"
done

echo "$name: $(ls "$out"/*.rd 2>/dev/null | wc -l) rd files in $out"
grep -h 'FD3KNOB' "$out/run.log" | sort -u || true
