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
#   --modules  the image's /usr/lib/modules/<kver> directory (needs modules.dep)
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

# `rm -rf` on the output is only safe when the output is ours. Refuse an
# output that is, contains, or lives inside an input, and refuse to clear an
# existing directory that this script did not create.
marker=.stage-inject-tree
overlaps() {
    # $1 and $2 overlap if either is a prefix of the other.
    case "$1/" in "$2"/*) return 0 ;; esac
    case "$2/" in "$1"/*) return 0 ;; esac
    return 1
}
out_abs=$(realpath -m -- "$out")
for input in "$smoo" "$modules" "$gadget"; do
    input_abs=$(realpath -- "$input")
    if overlaps "$out_abs" "$input_abs"; then
        die "--out $out overlaps input $input; refusing to delete it"
    fi
done
if [ -e "$out" ]; then
    [ -f "$out/$marker" ] \
        || die "$out exists and was not created by this script; remove it yourself"
    rm -rf -- "$out"
fi
mkdir -p \
    "$out/usr/bin" \
    "$out/usr/libexec/smoo" \
    "$out/usr/lib/smoo/modules" \
    "$out/usr/lib/dracut/hooks/cmdline" \
    "$out/usr/lib/dracut/hooks/pre-udev" \
    "$out/usr/lib/dracut/hooks/shutdown" \
    "$out/usr/lib/systemd/system/initrd-root-device.target.wants"
: > "$out/$marker"

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
# insmod cannot be relied on to decompress. Dependencies are resolved from the
# tree's modules.dep: the first hardware run shipped libcomposite without
# udc-core and the gadget never came up.
want=(
    configfs
    dwc3-qcom
    libcomposite
    usb_f_fs
    ublk_drv
    dm-mod
    dm-snapshot
    loop
)

depfile=$modules/modules.dep
[ -f "$depfile" ] || die "no modules.dep under $modules; --modules must be the /usr/lib/modules/<kver> directory"
builtin=$modules/modules.builtin

# The relative path of a module in modules.dep, matching either spelling of
# its name: modules.dep uses the file name (dm-mod.ko), the kernel the
# module name (dm_mod).
module_path() {
    _pattern=$(printf '%s' "$1" | sed 's/[-_]/[-_]/g')
    sed -n "s|^\(\([^:]*/\)\?$_pattern\.ko[^:]*\):.*|\1|p" "$depfile" | head -n 1
}

is_builtin() {
    [ -f "$builtin" ] || return 1
    _pattern=$(printf '%s' "$1" | sed 's/[-_]/[-_]/g')
    grep -qE "(^|/)$_pattern\.ko$" "$builtin"
}

# Ordered load list: each module's dependencies first, as modules.dep lists
# them right to left, then the module itself. Duplicates keep their first
# position.
order=()
seen=
add_module() {
    case " $seen " in *" $1 "*) return ;; esac
    seen="$seen $1"
    order+=("$1")
}

missing=()
for name in "${want[@]}"; do
    path=$(module_path "$name")
    if [ -z "$path" ]; then
        if is_builtin "$name"; then
            continue
        fi
        missing+=("$name")
        continue
    fi
    deps=$(sed -n "s|^$path: *||p" "$depfile")
    for dep in $(printf '%s\n' "$deps" | tr ' ' '\n' | tac); do
        add_module "$dep"
    done
    add_module "$path"
done

found=0
load_order=()
for path in "${order[@]}"; do
    src=$modules/$path
    [ -f "$src" ] || die "modules.dep names $path but it is not under $modules"
    base=$(basename "$path")
    name=${base%%.ko*}
    dest=$out/usr/lib/smoo/modules/$name.ko
    case "$src" in
        *.ko.xz) xz -dc "$src" > "$dest" ;;
        *.ko.zst) zstd -dc "$src" > "$dest" ;;
        *.ko.gz) gzip -dc "$src" > "$dest" ;;
        *.ko) cp "$src" "$dest" ;;
        *) die "unrecognised module compression: $src" ;;
    esac
    chmod 0644 "$dest"
    load_order+=("$name")
    found=$((found + 1))
done

if [ "${#missing[@]}" -gt 0 ]; then
    die "not in modules.dep or modules.builtin: ${missing[*]}"
fi
[ "$found" -gt 0 ] || die "no datapath modules resolved under $modules"

{
    cat << 'HOOK'
#!/bin/sh
# Load the datapath modules carried in the injected tree.
#
# They are not in the image's initramfs, and they are staged as plain .ko files
# with no modules.dep, so modprobe cannot find them. The list is already in
# dependency order; it was resolved from the image's modules.dep when the tree
# was staged.

command -v getarg > /dev/null || . /lib/dracut-lib.sh

getargbool 0 rd.smoo || return 0

HOOK
    printf 'for mod in %s; do\n' "${load_order[*]}"
    cat << 'HOOK'
    ko=/usr/lib/smoo/modules/$mod.ko
    [ -f "$ko" ] || continue
    if insmod "$ko" 2> /dev/null; then
        info "smoo: loaded $mod from the injected tree"
    else
        # Already loaded (the image's initramfs may carry some of these) or
        # built in: both are fine, and both look like failure.
        info "smoo: $mod not inserted (already present, or built in)"
    fi
done

return 0
HOOK
} > "$out/usr/lib/dracut/hooks/pre-udev/10-smoo-modules.sh"
chmod 0755 "$out/usr/lib/dracut/hooks/pre-udev/10-smoo-modules.sh"
printf 'stage-inject-tree: module load order: %s\n' "${load_order[*]}" >&2

printf 'stage-inject-tree: staged %s files and %s modules into %s\n' \
    "$(find "$out" -type f | wc -l)" "$found" "$out"
