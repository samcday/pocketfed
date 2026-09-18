#!/bin/bash
# Build a liveboot image for a device from an image builder's output directory.
#
# Everything the phone needs comes from the image itself: the boot image is
# repacked with a liveboot command line, and the smoo dracut module, the
# datapath kernel modules and dmsetup are taken from the served root filesystem
# and appended to the image's own initramfs. Nothing is flashed; the result is
# handed to `fastboot boot`.
#
# Usage:
#   tools/liveboot/build.sh --out out/google-sargo --smoo ../smoo [options]
#
#   --out DIR       image builder output holding boot.img and pfroot.img
#   --smoo DIR      smoo checkout with dracut/modules.d/90smoo
#   --gadget BIN    aarch64 smoo-gadget; default: the smoo checkout's
#                   target/aarch64-unknown-linux-musl/release/smoo-gadget
#                   (`cargo gadget-musl-aarch64` in that checkout builds it)
#   --cow-size SIZE RAM overlay ceiling, default 2G
#   --enforcing     keep SELinux enforcing (the boot stalls until the image
#                   carries smoo's policy module; see README)
#   --append ARG    extra kernel argument, repeatable
#
# Needs: debugfs (e2fsprogs), xz, file, cargo.

set -euo pipefail

die() {
    printf 'liveboot/build: %s\n' "$*" >&2
    exit 1
}

here=$(cd "$(dirname "$0")" && pwd)
out=
smoo=
gadget=
cow_size=2G
permissive=1
append=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --out) out=${2:?--out needs a value}; shift 2 ;;
        --smoo) smoo=${2:?--smoo needs a value}; shift 2 ;;
        --gadget) gadget=${2:?--gadget needs a value}; shift 2 ;;
        --cow-size) cow_size=${2:?--cow-size needs a value}; shift 2 ;;
        --enforcing) permissive=0; shift ;;
        --append) append+=(--append "${2:?--append needs a value}"); shift 2 ;;
        *) die "unexpected argument: $1" ;;
    esac
done

[ -n "$out" ] || die "--out is required"
[ -n "$smoo" ] || die "--smoo is required"
gadget=${gadget:-$smoo/target/aarch64-unknown-linux-musl/release/smoo-gadget}
[ -f "$out/boot.img" ] || die "no boot.img in $out (run the image builder's fastboot-from-image first)"
[ -f "$out/pfroot.img" ] || die "no pfroot.img in $out"
[ -f "$gadget" ] || die "no smoo-gadget at $gadget (cargo gadget-musl-aarch64 in $smoo)"
command -v debugfs > /dev/null || die "debugfs (e2fsprogs) is required to read pfroot.img"

root=$out/pfroot.img
work=$out/liveboot-work
rm -rf "$work"
mkdir -p "$work/modules" "$work/extra/usr/sbin" "$work/extra/usr/lib64"

# debugfs reads the ext4 image without mounting it, so no root is needed.
fs_ls() {
    debugfs -R "ls -p $1" "$root" 2> /dev/null | awk -F/ '{print $6}' | grep -vE '^\.{1,2}$' || true
}

os=$(fs_ls /ostree/deploy | head -n 1)
[ -n "$os" ] || die "$root has no ostree deployment"
deploy=$(fs_ls "/ostree/deploy/$os/deploy" | grep -E '\.[0-9]+$' | head -n 1)
[ -n "$deploy" ] || die "$root has no checked-out deployment under /ostree/deploy/$os/deploy"
deploy=/ostree/deploy/$os/deploy/$deploy
kver=$(fs_ls "$deploy/usr/lib/modules" | grep -E '^[0-9]' | head -n 1)
[ -n "$kver" ] || die "no kernel modules under $deploy/usr/lib/modules"
printf 'liveboot/build: deployment %s, kernel %s\n' "$deploy" "$kver" >&2

# The datapath drivers live in a handful of subtrees; modules.dep resolves
# their dependencies. rdump creates the last path component itself.
modtree=$deploy/usr/lib/modules/$kver
mkdir -p "$work/modules/kernel/drivers/usb" "$work/modules/kernel/fs"
for sub in drivers/block drivers/md drivers/usb/gadget drivers/usb/dwc3 drivers/usb/common fs/configfs; do
    debugfs -R "rdump $modtree/kernel/$sub $work/modules/kernel/$(dirname "$sub")" "$root" 2>&1 \
        | grep -vE '^debugfs|Operation not permitted|File not found|^$' >&2 || true
done
for f in modules.dep modules.builtin; do
    debugfs -R "cat $modtree/$f" "$root" 2> /dev/null > "$work/modules/$f"
    [ -s "$work/modules/$f" ] || die "could not read $modtree/$f"
done

# The image's initramfs has no dmsetup; take it and its library from the
# deployment (the initramfs already carries everything else they link).
debugfs -R "dump $deploy/usr/sbin/dmsetup $work/extra/usr/sbin/dmsetup" "$root" 2>&1 | grep -v '^debugfs' >&2 || true
[ -s "$work/extra/usr/sbin/dmsetup" ] || die "could not read dmsetup from $deploy"
chmod 0755 "$work/extra/usr/sbin/dmsetup"
for lib in $(fs_ls "$deploy/usr/lib64" | grep -E '^libdevmapper\.so'); do
    debugfs -R "dump $deploy/usr/lib64/$lib $work/extra/usr/lib64/$lib" "$root" 2>&1 | grep -v '^debugfs' >&2 || true
done
[ -n "$(ls "$work/extra/usr/lib64")" ] || die "could not read libdevmapper from $deploy"

"$here/stage-inject-tree.sh" \
    --smoo "$smoo" \
    --gadget "$gadget" \
    --modules "$work/modules" \
    --extra "$work/extra" \
    --out "$work/inject-tree"

# rd.timeout/rd.emergency: a failed initrd reboots by itself instead of
# waiting on a console nobody can log in to (sulogin, root locked).
extra_args=(--append rd.timeout=120 --append rd.emergency=reboot)
if [ "$permissive" = 1 ]; then
    extra_args+=(--append enforcing=0)
fi

cargo build --release --quiet --manifest-path "$here/Cargo.toml"
"$here/target/release/pocketfed-liveboot" boot \
    --aboot "$out/boot.img" \
    --root-image "$root" \
    --cow-size "$cow_size" \
    --inject-tree "$work/inject-tree" \
    "${extra_args[@]}" \
    "${append[@]}" \
    --output "$out/liveboot.img"
