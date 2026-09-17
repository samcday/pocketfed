#!/bin/sh
# SPDX-License-Identifier: MIT
#
# Build an external kmod directory against a Fedora kernel-devel RPM inside an
# arm64 rawhide container (this host runs arm64 containers under emulation).
#
#   hwe/tools/build-kmods-arm64.sh > out/hwe/A1b/build.log 2>&1
#
# The first run installs the toolchain plus the kernel-devel RPM and commits the
# result as a local image tag so reruns skip the slow dnf step:
#
#   localhost/pocketfed-hwe-kbuild:73rc3
#
# Only the checkout is mounted (at /work); nothing outside it is mounted or
# written. SELinux label separation is disabled for the container so the mounted
# checkout stays readable without relabelling host files. Override with
# KMOD_DIR, TAG, IMAGE or RELEASE if needed.

set -eu

repo=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)

image=${IMAGE:-registry.fedoraproject.org/fedora:rawhide}
tag=${TAG:-localhost/pocketfed-hwe-kbuild:73rc3}
kmod_dir=${KMOD_DIR:-hwe/kmods/sdm670-early}
packages="gcc make elfutils-libelf-devel kmod xz flex bison openssl-devel diffutils"

devel_rpm=$(ls "$repo"/out/hwe/rpms/kernel-devel-*.rpm 2>/dev/null | head -n 1)
if [ -z "$devel_rpm" ]; then
    echo "build-kmods: no kernel-devel RPM under out/hwe/rpms" >&2
    exit 2
fi
release=${devel_rpm##*/kernel-devel-}
release=${release%.rpm}
if [ -n "${RELEASE:-}" ]; then
    release=$RELEASE
fi

container=
cleanup() {
    [ -n "$container" ] && podman rm -f "$container" >/dev/null 2>&1 || true
}
trap cleanup EXIT HUP INT TERM

if ! podman image exists "$tag"; then
    echo "build-kmods: preparing cached image $tag (dnf install; slow on first run)"
    container=$(podman create --arch arm64 --security-opt label=disable -v "$repo":/work "$image" \
        /bin/sh -c "dnf install -y $packages /work/out/hwe/rpms/kernel-devel-*.rpm")
    podman start -a "$container"
    podman commit "$container" "$tag"
    podman rm -f "$container"
    container=
fi

echo "build-kmods: release=$release kmod_dir=$kmod_dir image=$tag"
podman run --rm --arch arm64 --userns=keep-id --security-opt label=disable -v "$repo":/work "$tag" \
    make -C "/usr/src/kernels/$release" M="/work/$kmod_dir" modules
