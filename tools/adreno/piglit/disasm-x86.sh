#!/bin/bash
# Host-side ir3 disassembly via the freedreno noop drm-shim (runs inside the
# x86_64_build container). usage: disasm-x86.sh ARM GPU_ID file.shader_test...
set -u
ARM=$1 GPU=$2; shift 2
I=/w/out/x86-$ARM/install
export LD_LIBRARY_PATH=$I/lib LIBGL_DRIVERS_PATH=$I/lib/dri GBM_BACKENDS_PATH=$I/lib/gbm EGL_PLATFORM=surfaceless
export LD_PRELOAD=$I/lib/libfreedreno_noop_drm_shim.so FD_GPU_ID=$GPU
export MESA_SHADER_CACHE_DISABLE=true IR3_SHADER_DEBUG=disasm MESA_GLSL_CACHE_DISABLE=true
exec /w/shader-db/run -j1 "$@"
