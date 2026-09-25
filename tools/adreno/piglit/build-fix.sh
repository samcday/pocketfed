#!/bin/bash
# Build /w/mesa-fix (worktree of Mesa main, branch claude/a3xx-bfm-regression)
# in CI's debian/arm64_build image, same configuration as build-mesa.sh,
# separate build dir so the earlier arms stay intact.
# usage: build-fix.sh ARM SHA   (install goes to /w/out/ARM)
set -euo pipefail
ARM=$1 SHA=$2
S=/w/mesa-fix B=/w/build-fix
if [ ! -f $B/build.ninja ]; then
MESA_GIT_SHA1_OVERRIDE=$SHA meson setup "$B" "$S" \
  --wrap-mode=nofallback \
  -D prefix=/install -D libdir=lib \
  -D buildtype=debugoptimized \
  -D build-tests=false -D enable-glcpp-tests=false \
  -D libunwind=disabled -D valgrind=disabled \
  -D glvnd=disabled -D glx=dri -D gbm=enabled -D egl=enabled \
  -D platforms=x11,wayland \
  -D legacy-wayland=bind-wayland-display \
  -D gallium-drivers=freedreno -D vulkan-drivers=[] \
  -D freedreno-kmds=msm \
  -D gallium-va=disabled -D gallium-rusticl=false \
  -D llvm=disabled -D teflon=false -D perfetto=false \
  -D tools=[] -D werror=false
meson configure --no-pager "$B" > /w/logs/meson-configure-fix.txt
fi
MESA_GIT_SHA1_OVERRIDE=$SHA ninja -C "$B" -j24
rm -rf /w/out/$ARM
DESTDIR=/w/out/$ARM ninja -C "$B" install > /w/logs/install-$ARM.log
(cd /w/out/$ARM/install/lib && find . -type f -name '*.so*' | sort | xargs sha256sum) > /w/out/$ARM.SHA256SUMS
echo BUILD-DONE
