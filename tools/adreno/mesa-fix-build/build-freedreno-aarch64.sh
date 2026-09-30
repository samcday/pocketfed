#!/bin/bash
# Build a patched Fedora Mesa gallium megadriver for an aarch64 Adreno board.
#
# Produces ONE artifact: libgallium-<ver>.so with only the freedreno driver in it.
# On Mesa 25.1+ that single library *is* the driver: /usr/lib64/dri/*_dri.so are
# symlinks to a stub, and libgallium is a DT_NEEDED of libEGL_mesa.so.0, so the
# shipped copy is selected with LD_LIBRARY_PATH (see README.md).
#
# Runs the whole build inside a Fedora aarch64 container. On an x86_64 host that
# needs qemu-user-static; check it first:
#   podman run --rm --arch arm64 registry.fedoraproject.org/fedora:46 uname -m
#
# usage: build-freedreno-aarch64.sh <workdir> <patch> [<mesa-nvr>] [<fedora-release>]
set -euo pipefail

WORK=$(realpath "${1:?workdir}")
PATCH=$(realpath "${2:?patch file}")
NVR=${3:-mesa-26.2.2-6.fc46}
REL=${4:-46}
VER=${NVR#mesa-}; VER=${VER%%-*}
IMG=mesa-freedreno-build:f$REL

mkdir -p "$WORK"
cd "$WORK"

if [ ! -f "$NVR.src.rpm" ]; then
  curl -sSL -o "$NVR.src.rpm" \
    "https://kojipkgs.fedoraproject.org/packages/mesa/${VER}/${NVR#mesa-$VER-}/src/$NVR.src.rpm"
fi
sha256sum "$NVR.src.rpm"
rpm2cpio "$NVR.src.rpm" | cpio -idm --quiet
# Fedora carries no patches for mesa; if that ever changes, apply them here too.
grep -q '^Patch' mesa.spec && { echo "spec now has patches, handle them"; exit 1; }
rm -rf "mesa-$VER"; tar xf "mesa-$VER.tar.xz"

# libarchive-devel and libxml2-devel are load-bearing: without them meson falls
# back to wrap subprojects and downloads+builds them from source.
if ! podman image exists "$IMG"; then
  podman rm -f mesa-fd-deps 2>/dev/null || true
  podman run --name mesa-fd-deps --arch arm64 "registry.fedoraproject.org/fedora:$REL" \
    dnf -y install --setopt=install_weak_deps=False \
      meson ninja-build gcc gcc-c++ flex bison patch binutils file \
      python3-mako python3-pyyaml python3-packaging python3-devel python3-pycparser \
      pkgconf-pkg-config gettext kernel-headers \
      libdrm-devel libX11-devel libXext-devel libXdamage-devel libXfixes-devel \
      libXxf86vm-devel libxcb-devel xcb-util-keysyms-devel libxshmfence-devel \
      libXrandr-devel libXrender-devel libXpresent-devel xorg-x11-proto-devel \
      expat-devel zlib-devel libzstd-devel libarchive-devel libxml2-devel libxslt-devel \
      wayland-devel wayland-protocols-devel libglvnd-devel libglvnd-core-devel \
      libselinux-devel libdisplay-info-devel systemd-devel elfutils-libelf-devel \
      libunwind-devel valgrind-devel
  podman commit mesa-fd-deps "$IMG"
  podman rm -f mesa-fd-deps
fi

cp "$PATCH" "$WORK/build.patch"
cat > "$WORK/inner.sh" <<INNER
set -euxo pipefail
cd /w/mesa-$VER
patch -p1 --dry-run < /w/build.patch
patch -p1 < /w/build.patch
rm -rf /w/build
# buildtype=debugoptimized, NOT debug: debug sets MESA_DEBUG=1, which makes
# emit_marker() emit an OUT_WFI before and after every draw. That is a pipeline
# drain in the middle of the cmdstream you are trying to reason about, and it
# does not exist in Fedora's build (%meson uses --buildtype=plain).
meson setup /w/build --prefix=/usr --libdir=lib64 \\
  -Dbuildtype=debugoptimized -Dplatforms=x11,wayland \\
  -Dgallium-drivers=freedreno -Dfreedreno-kmds=msm -Dvulkan-drivers= \\
  -Dgles1=enabled -Dgles2=enabled -Dopengl=true -Dgbm=enabled \\
  -Dglx=dri -Degl=enabled -Dglvnd=enabled -Dllvm=disabled \\
  -Dgallium-va=disabled -Dgallium-rusticl=false -Dgallium-mediafoundation=disabled \\
  -Dteflon=false -Dbuild-tests=false -Dlibunwind=disabled -Dvalgrind=disabled \\
  -Dlmsensors=disabled -Dandroid-libbacktrace=disabled -Dglx-read-only-text=true \\
  -Dspirv-tools=disabled -Dmicrosoft-clc=disabled -Dintel-rt=disabled -Dvideo-codecs=
time ninja -C /w/build -j\$(nproc) src/gallium/targets/dri/libgallium-$VER.so
strip --strip-unneeded -o /w/libgallium-$VER.so \\
  /w/build/src/gallium/targets/dri/libgallium-$VER.so
ls -l /w/libgallium-$VER.so
sha256sum /w/libgallium-$VER.so
INNER

podman run --rm --arch arm64 -v "$WORK:/w:z" "$IMG" bash /w/inner.sh
xz -9 -T0 -kf "$WORK/libgallium-$VER.so"
ls -l "$WORK/libgallium-$VER.so.xz"
sha256sum "$WORK/libgallium-$VER.so" "$WORK/libgallium-$VER.so.xz"
