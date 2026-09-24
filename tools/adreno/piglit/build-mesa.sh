#!/bin/bash
# Build Mesa for the DB410c inside Mesa CI's debian/arm64_build image
# (qemu-user). Mirrors the debian-arm64 CI job's configuration, restricted
# to freedreno: debugoptimized (MESA_DEBUG=0, assertions on), glvnd off,
# prefix /install like CI. One tree, two sequential arms:
#   main = aa1139b2e13 (MR base), mr = d39138dcdcd (base + the MR commit).
set -euo pipefail
cd /w
S=/w/src/main
B=/w/build
rm -rf "$B" /w/out
meson --version
MESA_GIT_SHA1_OVERRIDE=aa1139b2e13 meson setup "$B" "$S" \
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
meson configure --no-pager "$B" > /w/logs/meson-configure.txt
build_arm() {
  arm=$1 sha=$2
  MESA_GIT_SHA1_OVERRIDE=$sha ninja -C "$B" -j32
  DESTDIR=/w/out/$arm ninja -C "$B" install > /w/logs/install-$arm.log
  grep -h 'MESA_GIT_SHA1' "$B"/src/git_sha1.h
  (cd /w/out/$arm/install/lib && find . -type f -name '*.so*' | sort | xargs sha256sum) > /w/out/$arm.SHA256SUMS
}
build_arm main aa1139b2e13
# The MR changes exactly one file; swap it in and rebuild incrementally.
cp /w/src/mr/src/gallium/drivers/freedreno/a3xx/fd3_emit.c "$S/src/gallium/drivers/freedreno/a3xx/fd3_emit.c"
diff -r --exclude=.rev /w/src/main /w/src/mr && echo "source trees identical after swap"
build_arm mr d39138dcdcd
echo BUILD-DONE
