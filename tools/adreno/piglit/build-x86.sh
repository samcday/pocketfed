#!/bin/bash
# Native x86_64 build of /w/mesa-fix in CI's debian/x86_64_build image, with
# the freedreno noop drm-shim, for host-side ir3 disassembly (FD_GPU_ID=307/630).
# usage: build-x86.sh ARM SHA  -> /w/out/x86-ARM
set -euo pipefail
ARM=$1 SHA=$2
S=/w/mesa-fix B=/w/build-x86
if [ ! -f $B/build.ninja ]; then
MESA_GIT_SHA1_OVERRIDE=$SHA meson setup "$B" "$S" \
  --wrap-mode=nofallback \
  -D prefix=/install -D libdir=lib \
  -D buildtype=debugoptimized \
  -D build-tests=false -D enable-glcpp-tests=false \
  -D libunwind=disabled -D valgrind=disabled \
  -D glvnd=disabled -D glx=disabled -D gbm=enabled -D egl=enabled \
  -D platforms=[] \
  -D gallium-drivers=freedreno -D vulkan-drivers=[] \
  -D freedreno-kmds=msm \
  -D gallium-va=disabled -D gallium-rusticl=false \
  -D llvm=disabled -D teflon=false -D perfetto=false \
  -D tools=drm-shim -D werror=false
fi
MESA_GIT_SHA1_OVERRIDE=$SHA ninja -C "$B" -j8
rm -rf /w/out/x86-$ARM
DESTDIR=/w/out/x86-$ARM ninja -C "$B" install > /w/logs/install-x86-$ARM.log
(cd /w/out/x86-$ARM/install/lib && find . -type f -name '*.so*' | sort | xargs sha256sum) > /w/out/x86-$ARM.SHA256SUMS
[ -x /w/shader-db/run ] || make -C /w/shader-db run
echo BUILD-DONE
