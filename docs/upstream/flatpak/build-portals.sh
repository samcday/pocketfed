#!/bin/bash
# Build Fedora's baseline and the patched portal from its exact source RPM.
set -euo pipefail

recipe_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
source_dir=
output_dir=
jobs=${FLATPAK_BUILD_JOBS:-8}
while (($#)); do
    case "$1" in
        --source-dir) source_dir=$2; shift 2 ;;
        --output-dir) output_dir=$2; shift 2 ;;
        --jobs) jobs=$2; shift 2 ;;
        -h|--help)
            echo "Usage: $0 --source-dir DIR --output-dir EMPTY_DIR [--jobs N]"
            echo "DIR must contain flatpak-1.19.0-3.fc46.src.rpm. No downloads or installation are performed."
            exit 0 ;;
        *) echo "Unknown argument: $1" >&2; exit 2 ;;
    esac
done
if [[ -z $source_dir || -z $output_dir || ! $jobs =~ ^[1-9][0-9]*$ ]]; then
    echo "Specify --source-dir, --output-dir, and a positive job count." >&2
    exit 2
fi
source_dir=$(realpath -- "$source_dir")
mkdir -p -- "$output_dir"
output_dir=$(realpath -- "$output_dir")
if [[ -n $(find "$output_dir" -mindepth 1 -maxdepth 1 -print -quit) ]]; then
    echo "Output directory must be empty: $output_dir" >&2
    exit 2
fi
srpm=flatpak-1.19.0-3.fc46.src.rpm
patch_file="$recipe_dir/flatpak-1.19.0-retry-instance-pid.patch"
(
    cd "$source_dir"
    awk -v name="$srpm" '$2 == name' "$recipe_dir/sources.sha256" | sha256sum --check -
)
mkdir "$output_dir/sources" "$output_dir/source" "$output_dir/artifacts"
(
    cd "$output_dir/sources"
    rpm2cpio "$source_dir/$srpm" | cpio -idm --quiet
    awk -v name="$srpm" '$2 != name' "$recipe_dir/sources.sha256" | sha256sum --check -
)
tar -xf "$output_dir/sources/flatpak-1.19.0.tar.xz" -C "$output_dir/source"
tree="$output_dir/source/flatpak-1.19.0"
patch -d "$tree" -p1 < "$output_dir/sources/fd-conflation.patch"
patch -d "$tree" -p1 < "$output_dir/sources/eagain.patch"

meson setup "$output_dir/build" "$tree" \
    --prefix=/usr --libdir=lib64 --libexecdir=libexec \
    --sysconfdir=/etc --localstatedir=/var \
    --buildtype=debugoptimized -Db_lto=false \
    -Dsystem_bubblewrap=/usr/bin/bwrap \
    -Dsystem_dbus_proxy=/usr/bin/xdg-dbus-proxy \
    -Dmalcontent=enabled -Dwayland_security_context=enabled \
    -Ddocbook_docs=disabled -Dman=disabled -Dgtkdoc=disabled \
    -Dgir=disabled -Dselinux_module=disabled \
    -Dtests=false -Dinstalled_tests=false
ninja -C "$output_dir/build" -j "$jobs" portal/flatpak-portal
cp "$output_dir/build/portal/flatpak-portal" "$output_dir/artifacts/flatpak-portal-unpatched"
patch -d "$tree" -p1 < "$patch_file"
ninja -C "$output_dir/build" -j "$jobs" portal/flatpak-portal
cp "$output_dir/build/portal/flatpak-portal" "$output_dir/artifacts/flatpak-portal-patched"
(
    cd "$output_dir/artifacts"
    sha256sum flatpak-portal-* > binaries.sha256
    ldd flatpak-portal-patched > dependencies.txt
    file flatpak-portal-* > file.txt
    rpm -qa | sort > build-packages.txt
    ./flatpak-portal-unpatched --version
    ./flatpak-portal-patched --version
)
sha256sum "$source_dir/$srpm" "$patch_file" > "$output_dir/artifacts/inputs.sha256"
