#!/bin/bash
# Stage the smoo dracut module into a tree for `pocketfed-liveboot --inject-tree`.
#
# A device image's initramfs does not carry the smoo gadget, and the road to it
# doing so — land the dracut module, build it in the COPR, put it in the image,
# rebuild the image — is far longer than a boot trial should need. This lays out
# exactly what dracut's module-setup.sh would have installed, plus the kernel
# modules sargo's hostonly-strict initramfs leaves out, so the files can be
# appended to the image's own initramfs instead.
#
# Usage:
#   stage-inject-tree.sh --smoo DIR --gadget BIN --modules DIR --out DIR
#
#   --smoo     smoo checkout, for dracut/modules.d/90smoo
#   --gadget   aarch64 smoo-gadget binary
#   --modules  the image's /usr/lib/modules/<kver> directory
#   --out      tree to create (removed first)

set -euo pipefail

die() {
    printf 'stage-inject-tree: %s\n' "$*" >&2
    exit 1
}

smoo=
gadget=
modules=
out=

while [ "$#" -gt 0 ]; do
    case "$1" in
        --smoo) smoo=${2:?--smoo needs a value}; shift 2 ;;
        --gadget) gadget=${2:?--gadget needs a value}; shift 2 ;;
        --modules) modules=${2:?--modules needs a value}; shift 2 ;;
        --out) out=${2:?--out needs a value}; shift 2 ;;
        *) die "unexpected argument: $1" ;;
    esac
done

[ -n "$smoo" ] || die "--smoo is required"
[ -n "$gadget" ] || die "--gadget is required"
[ -n "$modules" ] || die "--modules is required"
[ -n "$out" ] || die "--out is required"

moddir=$smoo/dracut/modules.d/90smoo
[ -d "$moddir" ] || die "no 90smoo module in $smoo"
[ -f "$gadget" ] || die "no gadget binary at $gadget"
[ -d "$modules" ] || die "no module directory at $modules"

case "$(file -b "$gadget")" in
    *aarch64*) ;;
    *) die "$gadget is not an aarch64 binary; the phone will not run it" ;;
esac

rm -rf -- "$out"
mkdir -p \
    "$out/usr/bin" \
    "$out/usr/libexec/smoo" \
    "$out/usr/lib/smoo/modules" \
    "$out/usr/lib/dracut/hooks/cmdline" \
    "$out/usr/lib/dracut/hooks/pre-udev" \
    "$out/usr/lib/dracut/hooks/shutdown" \
    "$out/usr/lib/systemd/system/initrd-root-device.target.wants"

install -m0755 "$gadget" "$out/usr/bin/smoo-gadget"

# Everything staged here ends up inside a boot image that `fastboot boot` has to
# download into RAM, so the gadget's debug symbols are worth roughly a third of
# its size. Strip when a cross-capable strip is available, and carry on when it
# is not: a larger image still boots.
for strip in llvm-strip aarch64-linux-gnu-strip strip; do
    if command -v "$strip" > /dev/null 2>&1 \
        && "$strip" "$out/usr/bin/smoo-gadget" 2> /dev/null; then
        printf 'stage-inject-tree: stripped smoo-gadget with %s\n' "$strip" >&2
        break
    fi
done

install -m0755 "$moddir/smoo-lib.sh" "$out/usr/libexec/smoo/smoo-lib"
install -m0755 "$moddir/smoo-gadget-initrd-start.sh" \
    "$out/usr/libexec/smoo/smoo-gadget-initrd-start"
install -m0755 "$moddir/smoo-root-setup.sh" "$out/usr/libexec/smoo/smoo-root-setup"

# Hook file names carry the priority dracut's inst_hook would have applied.
install -m0755 "$moddir/parse-smoo.sh" \
    "$out/usr/lib/dracut/hooks/cmdline/20-parse-smoo.sh"
install -m0755 "$moddir/smoo-gadget-initrd-stop.sh" \
    "$out/usr/lib/dracut/hooks/shutdown/90-smoo-gadget-initrd-stop.sh"

install -m0644 "$moddir/smoo-root-storage.service" \
    "$out/usr/lib/systemd/system/smoo-root-storage.service"
install -m0644 "$moddir/smoo-root-setup.service" \
    "$out/usr/lib/systemd/system/smoo-root-setup.service"

# systemd enablement normally comes from `systemctl add-wants` at initrd build
# time; injected files have to bring their own symlinks.
for unit in smoo-root-storage.service smoo-root-setup.service; do
    ln -sf "../$unit" \
        "$out/usr/lib/systemd/system/initrd-root-device.target.wants/$unit"
done

# sargo's dracut.conf is hostonly_mode=strict and lists none of the datapath
# modules, so the image's initramfs has no ublk, gadget or device-mapper
# drivers. Carry them from the image's own module tree, decompressed, because
# insmod cannot be relied on to decompress.
want=(
    configfs
    libcomposite
    usb_f_fs
    ublk_drv
    dm_mod
    dm_snapshot
    loop
)

found=0
missing=()
for name in "${want[@]}"; do
    src=$(find "$modules" -name "$name.ko*" -print -quit 2> /dev/null || true)
    if [ -z "$src" ]; then
        missing+=("$name")
        continue
    fi
    dest=$out/usr/lib/smoo/modules/$name.ko
    case "$src" in
        *.ko.xz) xz -dc "$src" > "$dest" ;;
        *.ko.zst) zstd -dc "$src" > "$dest" ;;
        *.ko.gz) gzip -dc "$src" > "$dest" ;;
        *.ko) cp "$src" "$dest" ;;
        *) die "unrecognised module compression: $src" ;;
    esac
    chmod 0644 "$dest"
    found=$((found + 1))
done

# A missing module is not always fatal: several are commonly built in, and the
# loader tolerates that. Report it so a failed boot can be explained.
if [ "${#missing[@]}" -gt 0 ]; then
    printf 'stage-inject-tree: not found (may be built in): %s\n' "${missing[*]}" >&2
fi
[ "$found" -gt 0 ] || die "no datapath modules found under $modules"

cat > "$out/usr/lib/dracut/hooks/pre-udev/10-smoo-modules.sh" << 'HOOK'
#!/bin/sh
# Load the datapath modules carried in the injected tree.
#
# They are not in the image's initramfs, and they are staged as plain .ko files
# with no modules.dep, so modprobe cannot find them. Order matters: dm_snapshot
# needs dm_mod, and usb_f_fs needs libcomposite.

command -v getarg > /dev/null || . /lib/dracut-lib.sh

getargbool 0 rd.smoo || return 0

for mod in configfs libcomposite usb_f_fs ublk_drv dm_mod dm_snapshot loop; do
    modprobe -q "$mod" 2> /dev/null && continue
    ko=/usr/lib/smoo/modules/$mod.ko
    [ -f "$ko" ] || continue
    if insmod "$ko" 2> /dev/null; then
        info "smoo: loaded $mod from the injected tree"
    else
        # Already loaded or built in: both are fine, and both look like failure.
        info "smoo: $mod not inserted (already present, or built in)"
    fi
done

return 0
HOOK
chmod 0755 "$out/usr/lib/dracut/hooks/pre-udev/10-smoo-modules.sh"

printf 'stage-inject-tree: staged %s files and %s modules into %s\n' \
    "$(find "$out" -type f | wc -l)" "$found" "$out"
