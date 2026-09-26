#!/bin/sh
# Build a freedreno-only, release libgallium for Alpine aarch64 (musl).
# Usage: build.sh <VARIANT>   (VARIANT = A2 | B2)
set -eu
VARIANT="$1"
SRC="/work/$VARIANT/mesa-26.2.3"
BUILD="$SRC/build"

echo "=== apk add build deps ($(date -u +%H:%M:%S)) ==="
apk update >/dev/null
apk add --no-progress \
    build-base meson ninja-build python3 py3-mako py3-yaml py3-packaging \
    py3-ply py3-cparser bison flex pkgconf \
    libdrm-dev wayland-dev wayland-protocols libdisplay-info-dev \
    libx11-dev libxext-dev libxfixes-dev libxdamage-dev libxshmfence-dev \
    libxrandr-dev libxxf86vm-dev libxcb-dev xorgproto \
    expat-dev zlib-dev zstd-dev elfutils-dev eudev-dev \
    libxml2-dev libarchive-dev \
    xz file binutils

export PATH="/usr/lib/ninja-build/bin:$PATH"

echo "=== versions ==="
gcc --version | head -1
meson --version
ninja --version
uname -m
echo "musl: $(apk info -v musl | head -1)"
echo "nproc: $(nproc)"

echo "=== meson setup ($(date -u +%H:%M:%S)) ==="
rm -rf "$BUILD"
cd "$SRC"
meson setup "$BUILD" \
    --wrap-mode=nofallback \
    -Dbuildtype=release \
    -Db_ndebug=true \
    -Dgallium-drivers=freedreno \
    -Dfreedreno-kmds=msm,virtio \
    -Dvulkan-drivers= \
    -Dgallium-rusticl=false \
    -Dgallium-va=disabled \
    -Dllvm=disabled \
    -Dplatforms=x11,wayland \
    -Dglx=dri \
    -Degl=enabled \
    -Dgles1=enabled \
    -Dgles2=enabled \
    -Dopengl=true \
    -Dgbm=enabled \
    -Dshared-glapi=enabled \
    -Dxlib-lease=enabled \
    -Dxmlconfig=enabled \
    -Dexpat=enabled \
    -Dzstd=enabled \
    -Dshader-cache=enabled \
    -Dallow-kcmp=enabled \
    -Dgallium-extra-hud=true \
    -Dvideo-codecs= \
    -Dtools= \
    -Dvalgrind=disabled \
    -Dlibunwind=disabled \
    -Dlmsensors=disabled
MESON_RC=$?
echo "MESON_SETUP_RC=$MESON_RC"
test "$MESON_RC" -eq 0

echo "=== libgallium ninja targets ==="
TGT=$(ninja -C "$BUILD" -t targets all 2>/dev/null | sed -n 's/^\(.*libgallium-26\.2\.3\.so\):.*/\1/p' | head -1)
echo "target: $TGT"
test -n "$TGT"

echo "=== ninja build ($(date -u +%H:%M:%S)) ==="
START=$(date +%s)
ninja -C "$BUILD" "$TGT"
END=$(date +%s)
echo "BUILD_SECONDS=$((END-START))"

echo "=== artifact ==="
SO="$BUILD/$TGT"
ls -l "$SO"
file "$SO"
echo "--- readelf -d ---"
readelf -d "$SO" | head -30
echo "--- size ---"
stat -c '%s %n' "$SO"

mkdir -p /work/out
cp "$SO" "/work/out/libgallium-26.2.3.so.$VARIANT"
echo "=== done $VARIANT ($(date -u +%H:%M:%S)) ==="
