#!/bin/bash
# build-initrd.sh - build a liveboot v2 boot image from a PocketFed OSTree root image.
#
# Liveboot v2 boots a board through Pocketboot's fastboot kexec loader: no
# ABL/ABLX shim and a plain Android v2 boot image. The image's root filesystem
# is served over USB by smoo-host, pinned to a product id, and the kernel is the
# board's own kernel (a bundle outside this repository). This script builds a
# dracut initrd *inside* that served root image, so the initrd gets the served
# root's userspace (dracut, podman, ostree) plus the board kernel's modules, and
# then wraps it into an Android v2 boot image.
#
# The recipe is deliberately mechanical. It was validated on the DB410c in the
# liveboot trials; the mechanics (read-only loop mount, podman --rootfs :O,
# module-tree overlay + depmod, DRACUT_NO_XATTR=1, strict hostonly confdir,
# stripped display closure) are required and should not be "simplified".
#
# This script never modifies the served root image, but it does use sudo (loop
# mount, overlay mount, podman) and needs a Linux host with mkbootimg. Run it as
# your normal user; sudo -n must succeed without a password prompt.
#
# See README.md for the operator procedure and the known liveboot limits.

set -euo pipefail

PROG=${0##*/}
SELF_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

# ---- defaults ---------------------------------------------------------------

ROOT_IMAGE=""
DEPLOYMENT=""
KERNEL_BUNDLE=""
SMOO_DRACUT=""
SMOO_GADGET=""
OUT_DIR=""

COW_SIZE="512M"
EXPORT_ID=""
PRODUCT_ID="0xBEE1"
RUN_TOKEN="lb-db410c"
AUTOLOGIN_ROOT=1
ZRAM=1
EDID_OVERRIDE="edid/1280x720.bin"
INITRD_ROOT_PASSWORD_FILE=""
DROP_DM_UDEV_RULES=0
DRY_RUN=0

PFROOT_MNT=${PFROOT_MNT:-/mnt/pfroot-ro}
CPIO=${CPIO:-/usr/bin/cpio}
STRIP=${STRIP:-aarch64-linux-gnu-strip}

# Modules the board needs before switch-root. This list came out of the DB410c
# trial and is kept verbatim; dracut normalises the dash/underscore spellings.
ADD_DRIVERS='qcom_hwspinlock qcom_apcs_ipc_mailbox qcom_smd rpm_proc smd_rpm clk_smd_rpm qnoc_msm8916 icc_smd_rpm qcom_spmi_regulator qcom_smd_regulator rtc_pm8xxx ulpi phy_qcom_usb_hs ci_hdrc ci_hdrc_msm extcon_usb_gpio gpio_keys ublk_drv brd libcomposite usb_f_fs msm adv7511 display_connector i2c_qup'
# Display roots whose modprobe closure is stripped into the module overlay.
DISPLAY_ROOTS='msm adv7511 display_connector i2c_qup'
# Firmware needed by the freedreno/msm display path; optional for probe but
# present in the served root and small.
FIRMWARE='/usr/lib/firmware/qcom/a300_pm4.fw.xz /usr/lib/firmware/qcom/a300_pfp.fw.xz'
# Subsystems the boot does not need; keeps the initrd small enough for the
# 54 MiB fastboot window.
OMIT_MODULES='plymouth network nfs iscsi fcoe lvm mdraid crypt multipath btrfs xfs resume i18n bluetooth cifs'

# ---- helpers ----------------------------------------------------------------

die() { printf '%s: error: %s\n' "$PROG" "$*" >&2; exit 1; }
log() { printf '%s: %s\n' "$PROG" "$*" >&2; }

usage() {
    cat <<EOF
Usage: $PROG --root-image <pfroot.img> --kernel-bundle <dir> \\
              --smoo-dracut <dir> --smoo-gadget <binary> --out <dir> \\
              --export-id <id> [options]

Required:
  --root-image <img>       PocketFed root image to loop-mount read-only.
  --kernel-bundle <dir>    Directory with Image.gz, qcom/apq8016-sbc.dtb and
                           modules/lib/modules/<kver>/.
  --smoo-dracut <dir>      Directory containing modules.d/90smoo (the smoo
                           dracut module checkout).
  --smoo-gadget <bin>      aarch64 smoo-gadget binary baked into the initrd.
  --out <dir>              Output directory (created if missing).
  --export-id <id>         smoo export id (rd.smoo.root=); smoo-host prints it.

Common options:
  --deployment <hash>      OSTree deployment hash, e.g. 10b8340a...a7a (or the
                           full <hash>.0). Auto-detected when unambiguous.
  --cow-size <size>        RAM copy-on-write size (default $COW_SIZE).
  --product-id <id>        Pinned gadget USB product id (default $PRODUCT_ID).
  --run-token <token>      pocketfed.liveboot= token and output filename stem
                           (default $RUN_TOKEN).
  --edid-override <path>   drm.edid_firmware override (default $EDID_OVERRIDE);
                           pass "none" to omit for sinks that advertise HPD.
  --autologin-root         Install the liveboot dracut module that drops a root
                           autologin on the serial console (default on).
  --no-autologin-root      Do not install that module.
  --zram                   Load zram (+lz4) from the initrd so the served root's
                           zram-generator can make swap (default on).
  --no-zram                Leave zram out; the RAM COW is then the only headroom.
  --initrd-root-password-file <path>
                           Set the initrd's root password from the first line
                           of <path> (never from the command line) so the
                           dracut emergency shell is usable over the console.
                           Only the initrd is affected.
  --drop-dm-udev-rules     Delete the device-mapper udev rules from the initrd.
                           Not needed with current smoo (smoo#59); off by
                           default and only here for older smoo revisions.
  --dry-run                Print the resolved plan and exit without building.
  -h, --help               Show this help.
EOF
}

need_value() {
    [ "$#" -ge 2 ] && [ -n "$2" ] && [ "${2#-}" = "$2" ] \
        || die "option $1 requires a value"
}

# ---- argument parsing -------------------------------------------------------

while [ "$#" -gt 0 ]; do
    case "$1" in
        --root-image)       need_value "$@"; ROOT_IMAGE=$2; shift 2 ;;
        --deployment)       need_value "$@"; DEPLOYMENT=$2; shift 2 ;;
        --kernel-bundle)    need_value "$@"; KERNEL_BUNDLE=$2; shift 2 ;;
        --smoo-dracut)      need_value "$@"; SMOO_DRACUT=$2; shift 2 ;;
        --smoo-gadget)      need_value "$@"; SMOO_GADGET=$2; shift 2 ;;
        --out)              need_value "$@"; OUT_DIR=$2; shift 2 ;;
        --export-id)        need_value "$@"; EXPORT_ID=$2; shift 2 ;;
        --cow-size)         need_value "$@"; COW_SIZE=$2; shift 2 ;;
        --product-id)       need_value "$@"; PRODUCT_ID=$2; shift 2 ;;
        --run-token)        need_value "$@"; RUN_TOKEN=$2; shift 2 ;;
        --edid-override)    need_value "$@"; EDID_OVERRIDE=$2; shift 2 ;;
        --initrd-root-password-file) need_value "$@"; INITRD_ROOT_PASSWORD_FILE=$2; shift 2 ;;
        --autologin-root)   AUTOLOGIN_ROOT=1; shift ;;
        --no-autologin-root) AUTOLOGIN_ROOT=0; shift ;;
        --zram)             ZRAM=1; shift ;;
        --no-zram)          ZRAM=0; shift ;;
        --drop-dm-udev-rules) DROP_DM_UDEV_RULES=1; shift ;;
        --dry-run)          DRY_RUN=1; shift ;;
        -h|--help)          usage; exit 0 ;;
        *)                  die "unknown argument: $1 (try --help)" ;;
    esac
done

# ---- validation -------------------------------------------------------------

[ -n "$ROOT_IMAGE" ]    || die "--root-image is required"
[ -n "$KERNEL_BUNDLE" ] || die "--kernel-bundle is required"
[ -n "$SMOO_DRACUT" ]   || die "--smoo-dracut is required"
[ -n "$SMOO_GADGET" ]   || die "--smoo-gadget is required"
[ -n "$OUT_DIR" ]       || die "--out is required"
[ -n "$EXPORT_ID" ]     || die "--export-id is required"

[ -f "$ROOT_IMAGE" ]    || die "root image not found: $ROOT_IMAGE"
[ -d "$KERNEL_BUNDLE" ] || die "kernel bundle not found: $KERNEL_BUNDLE"
[ -f "$KERNEL_BUNDLE/Image.gz" ] || die "missing $KERNEL_BUNDLE/Image.gz"
[ -f "$KERNEL_BUNDLE/qcom/apq8016-sbc.dtb" ] || die "missing $KERNEL_BUNDLE/qcom/apq8016-sbc.dtb"
[ -d "$SMOO_DRACUT/modules.d/90smoo" ] || die "missing $SMOO_DRACUT/modules.d/90smoo"
[ -f "$SMOO_GADGET" ]   || die "smoo-gadget not found: $SMOO_GADGET"

[[ "$EXPORT_ID" =~ ^[0-9]+$ ]]              || die "--export-id must be an unsigned decimal integer"
[[ "$PRODUCT_ID" =~ ^(0x[0-9A-Fa-f]{1,4}|[0-9]+)$ ]] || die "--product-id must be hex (0xBEE1) or decimal"
[[ "$COW_SIZE" =~ ^[0-9]+[KMGkmg]$ ]]       || die "--cow-size must look like 512M, 2G, ..."
[[ "$RUN_TOKEN" =~ ^[A-Za-z0-9._-]+$ ]]     || die "--run-token may only contain [A-Za-z0-9._-]"

if [ "$EDID_OVERRIDE" = none ]; then
    EDID_OVERRIDE=""
fi

# ---- kernel version ---------------------------------------------------------

mapfile -t _kvers < <(find "$KERNEL_BUNDLE/modules/lib/modules" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort)
[ "${#_kvers[@]}" -eq 1 ] || die "expected exactly one kernel version under $KERNEL_BUNDLE/modules/lib/modules, found ${#_kvers[@]}"
KVER=${_kvers[0]}

# ---- derived paths ----------------------------------------------------------

INITRD="$OUT_DIR/initrd-$RUN_TOKEN.img"
INITRD_PRE="$OUT_DIR/initrd-$RUN_TOKEN-pre.img"
BOOT_IMAGE="$OUT_DIR/liveboot-$RUN_TOKEN.img"
CMD_LINE_FILE="$OUT_DIR/cmdline.txt"

STAGING="$OUT_DIR/staging"
MODTREE_UPPER="$OUT_DIR/modtree-upper"
MODTREE_WORK="$OUT_DIR/modtree-work"
MODTREE_MERGED="$OUT_DIR/modtree-merged"
DRACUT_TMP="$OUT_DIR/dracut-tmp"
CONFDIR="$OUT_DIR/dracut-confdir"
LOGS="$OUT_DIR/logs"

if [ "$AUTOLOGIN_ROOT" = 1 ] || [ "$ZRAM" = 1 ]; then
    ADD_MODULES="smoo pocketfed-liveboot ostree"
else
    ADD_MODULES="smoo ostree"
fi

# ---- plan -------------------------------------------------------------------

if [ "$DRY_RUN" = 1 ]; then
    cat <<EOF
$PROG plan (dry run, nothing mounted or built)

  root image       $ROOT_IMAGE
  deployment       ${DEPLOYMENT:-<auto-detect>}
  kernel bundle    $KERNEL_BUNDLE
  kernel version   $KVER
  smoo dracut      $SMOO_DRACUT
  smoo gadget      $SMOO_GADGET
  output dir       $OUT_DIR

  loop mount       mount -o ro,loop $ROOT_IMAGE $PFROOT_MNT
  rootfs overlay   podman run --rootfs <deployment>:O
  module overlay   lowerdir=$KERNEL_BUNDLE/modules/lib/modules/$KVER upperdir=$MODTREE_UPPER workdir=$MODTREE_WORK
  dracut modules   --add "$ADD_MODULES"
  dracut drivers   --add-drivers "$ADD_DRIVERS"
  dracut firmware  --install "$FIRMWARE"
  dracut omit      --omit "$OMIT_MODULES"
  display closure  modprobe --show-depends $DISPLAY_ROOTS, stripped with $STRIP --strip-debug
  confdir          hostonly_mode=strict, add_dracutmodules+=" ostree "
  drop dm rules    $DROP_DM_UDEV_RULES
  shadow password  $([ -n "$INITRD_ROOT_PASSWORD_FILE" ] && echo 'set' || echo 'unchanged')
  run token        $RUN_TOKEN
  product id       $PRODUCT_ID
  cow size         $COW_SIZE
  export id        $EXPORT_ID
  edid override    ${EDID_OVERRIDE:-<none>}
  zram from initrd $ZRAM
  cmdline          (ostree= auto-derived from $PFROOT_MNT/ostree/boot.1/*/*/0)
  outputs          $INITRD
                   $BOOT_IMAGE
                   $CMD_LINE_FILE

  packages needed: sudo, podman, mount, realpath, openssl, zstd, cpio,
                   mkbootimg, lsinitrd, unpack_bootimg, $STRIP
EOF
    exit 0
fi

# ---- tool checks ------------------------------------------------------------

command -v sudo >/dev/null            || die "sudo not found"
command -v podman >/dev/null          || die "podman not found"
command -v realpath >/dev/null        || die "realpath not found"
command -v openssl >/dev/null         || die "openssl not found"
command -v mkbootimg >/dev/null       || die "mkbootimg not found"
command -v "$STRIP" >/dev/null        || die "$STRIP not found"
command -v "$CPIO" >/dev/null         || die "$CPIO not found"
command -v zstd >/dev/null            || die "zstd not found"

# ---- build ------------------------------------------------------------------

mkdir -p "$OUT_DIR"/{logs,staging/90smoo,staging/95pocketfed-liveboot,modtree-upper,modtree-work,modtree-merged,dracut-tmp,dracut-confdir}

cleanup() {
    sudo -n umount "$MODTREE_MERGED" 2>/dev/null || :
    sudo -n umount "$PFROOT_MNT" 2>/dev/null || :
}
trap cleanup EXIT

# 1. Mount the served root read-only and resolve the OSTree deployment.
sudo -n mkdir -p "$PFROOT_MNT"
mountpoint -q "$PFROOT_MNT" || sudo -n mount -o ro,loop "$ROOT_IMAGE" "$PFROOT_MNT"

mapfile -t _deps < <(find "$PFROOT_MNT/ostree/deploy" -mindepth 3 -maxdepth 3 -type d -name '*.0' 2>/dev/null | sort)
[ "${#_deps[@]}" -gt 0 ] || die "no OSTree deployments found in $ROOT_IMAGE"

DEP=""
if [ -n "$DEPLOYMENT" ]; then
    for d in "${_deps[@]}"; do
        b=${d##*/}
        if [ "$b" = "$DEPLOYMENT" ] || [ "$b" = "$DEPLOYMENT.0" ]; then
            DEP=$d
            break
        fi
    done
    [ -n "$DEP" ] || die "deployment '$DEPLOYMENT' not found in $ROOT_IMAGE"
else
    [ "${#_deps[@]}" -eq 1 ] || die "multiple deployments found; pass --deployment"
    DEP=${_deps[0]}
fi
log "deployment: $DEP"

# Derive the real ostree= path from the boot symlink rather than hardcoding it.
DEP_REAL=$(realpath "$DEP")
OSTREE_PATH=""
for _pattern in "$PFROOT_MNT/ostree/boot.1/*/*/0" "$PFROOT_MNT"/ostree/boot.1.*/*/*/0; do
    mapfile -t _links < <(compgen -G "$_pattern" || true)
    for _link in "${_links[@]}"; do
        [ -L "$_link" ] || continue
        if [ "$(realpath "$_link")" = "$DEP_REAL" ]; then
            OSTREE_PATH=${_link#"$PFROOT_MNT"}
            break 2
        fi
    done
done
[ -n "$OSTREE_PATH" ] || die "could not derive ostree= boot path for $DEP"
log "ostree path:  $OSTREE_PATH"

# Module tree overlay: depmod and strip write here, never into the bundle.
sudo -n mount -t overlay overlay \
    -o "lowerdir=$KERNEL_BUNDLE/modules/lib/modules/$KVER,upperdir=$MODTREE_UPPER,workdir=$MODTREE_WORK" \
    "$MODTREE_MERGED"

# 2. Stage the dracut modules with execute bits (90smoo ships 0644 in git).
rm -rf "$STAGING/90smoo" "$STAGING/95pocketfed-liveboot"
mkdir -p "$STAGING/90smoo" "$STAGING/95pocketfed-liveboot"
cp -a "$SMOO_DRACUT/modules.d/90smoo/." "$STAGING/90smoo/"
cp -a "$SELF_DIR/dracut/95pocketfed-liveboot/." "$STAGING/95pocketfed-liveboot/"
chmod 0755 "$STAGING"/90smoo/*.sh "$STAGING"/95pocketfed-liveboot/*.sh

printf '%s\n' \
    'hostonly="yes"' \
    'hostonly_mode="strict"' \
    'hostonly_cmdline="no"' \
    'add_dracutmodules+=" ostree "' > "$CONFDIR/10-db410c.conf"

# 3. Strip the display module closure in the writable overlay.
# The redirect is host-side into a user-owned log; only podman runs under sudo.
# shellcheck disable=SC2024
sudo -n podman run --rm --security-opt label=disable -e DRACUT_NO_XATTR=1 \
    -v "$MODTREE_MERGED:/usr/lib/modules/$KVER" \
    --rootfs "$DEP:O" /bin/bash -lc "
        depmod $KVER >/dev/null
        for m in $DISPLAY_ROOTS; do
            modprobe -S $KVER --show-depends \"\$m\"
        done | sed -n 's|^insmod /lib/modules/$KVER/\([^ ]*\).*|\1|p' | sort -u
    " > "$LOGS/display-closure.txt"

: > "$LOGS/display-strip.txt"
while IFS= read -r rel; do
    [ -n "$rel" ] || continue
    target="$MODTREE_MERGED/$rel"
    before=$(stat -c%s "$target")
    "$STRIP" --strip-debug "$target"
    after=$(stat -c%s "$target")
    printf '%-22s %10s -> %10s  %s\n' "$(basename "$rel" .ko)" "$before" "$after" "$rel" \
        >> "$LOGS/display-strip.txt"
done < "$LOGS/display-closure.txt"

# 4. dracut inside the served root.
# shellcheck disable=SC2024
sudo -n podman run --rm --security-opt label=disable -e DRACUT_NO_XATTR=1 \
    -v "$MODTREE_MERGED:/usr/lib/modules/$KVER" \
    -v "$STAGING/90smoo:/usr/lib/dracut/modules.d/90smoo:ro" \
    -v "$STAGING/95pocketfed-liveboot:/usr/lib/dracut/modules.d/95pocketfed-liveboot:ro" \
    -v "$SMOO_GADGET:/usr/bin/smoo-gadget:ro" \
    -v "$CONFDIR:/confdir-db410c:ro" \
    -v "$OUT_DIR:/out" \
    --rootfs "$DEP:O" \
    /bin/bash -lc "depmod $KVER && dracut --force --no-hostonly-cmdline --confdir /confdir-db410c \
        --tmpdir /out/dracut-tmp --kver $KVER \
        --add '$ADD_MODULES' \
        --add-drivers '$ADD_DRIVERS' \
        --install '$FIRMWARE' \
        --omit '$OMIT_MODULES' \
        /out/initrd-$RUN_TOKEN-pre.img" \
    > "$LOGS/dracut-build.log" 2>&1
sudo -n chmod 644 "$INITRD_PRE"

# 5. Post-process the initrd: optional dm udev-rule removal and optional
#    initrd root password. With neither requested, adopt dracut's output as is.
if [ "$DROP_DM_UDEV_RULES" = 1 ] || [ -n "$INITRD_ROOT_PASSWORD_FILE" ]; then
    sudo -n sh -c '"$1" -dc "$2" > "$3"' _ "$ZSTD" "$INITRD_PRE" "$DRACUT_TMP/tree.cpio"
    sudo -n sh -c 'rm -rf "$1" && mkdir -p "$1" && cd "$1" && "$2" -idmu < "$3" >/dev/null 2>&1' \
        _ "$DRACUT_TMP/tree" "$CPIO" "$DRACUT_TMP/tree.cpio"
    if [ "$DROP_DM_UDEV_RULES" = 1 ]; then
        # Only needed for smoo revisions before smoo#59: the dm udev rules
        # interfered with the /dev/smoo-root trigger.
        sudo -n sh -c 'cd "$1" && rm -f \
            usr/lib/udev/rules.d/10-dm.rules usr/lib/udev/rules.d/13-dm-disk.rules \
            usr/lib/udev/rules.d/95-dm-notify.rules etc/udev/rules.d/11-dm.rules' \
            _ "$DRACUT_TMP/tree"
    fi
    if [ -n "$INITRD_ROOT_PASSWORD_FILE" ]; then
        [ -r "$INITRD_ROOT_PASSWORD_FILE" ] || die "cannot read $INITRD_ROOT_PASSWORD_FILE"
        # The hash never appears in a process argument list: it travels to the
        # privileged shell over its standard input.
        head -n 1 -- "$INITRD_ROOT_PASSWORD_FILE" | openssl passwd -6 -stdin \
            | sudo -n sh -c 'IFS= read -r hash && sed -i "s|^root:[^:]*:|root:$hash:|" "$1"' \
                _ "$DRACUT_TMP/tree/etc/shadow"
    fi
    sudo -n sh -c 'cd "$1" && find . | "$2" -o -H newc 2>/dev/null | "$3" -T0 -19 > "$4"' \
        _ "$DRACUT_TMP/tree" "$CPIO" "$ZSTD" "$INITRD"
    sudo -n chmod 644 "$INITRD"
else
    sudo -n cp "$INITRD_PRE" "$INITRD"
    sudo -n chmod 644 "$INITRD"
fi

# 6. Kernel command line and Android v2 boot image (page size 4096).
# The comma in console=ttyMSM0,115200n8 is a baud list, not an array separator.
# shellcheck disable=SC2054
_parts=(
    rw rootwait "ostree=$OSTREE_PATH" init_on_alloc=0
    root=/dev/smoo-root rootfstype=ext4 rd.smoo=1
    "rd.smoo.root=$EXPORT_ID" "rd.smoo.cow.size=$COW_SIZE"
    "pocketfed.liveboot=$RUN_TOKEN"
    console=ttyMSM0,115200n8 earlycon sysrq_always_enabled=1
    rd.timeout=180 rd.emergency=reboot enforcing=0
    video=HDMI-A-1:1280x720@60e panic=10
    "rd.smoo.product=$PRODUCT_ID" rd.smoo.root_timeout=120
)
[ -n "$EDID_OVERRIDE" ] && _parts+=("drm.edid_firmware=HDMI-A-1:$EDID_OVERRIDE")
[ "$ZRAM" = 1 ] || _parts+=(rd.pocketfed.zram=0)
_parts+=(systemd.mask=systemd-coredump.socket)
CMD_LINE="${_parts[*]}"
printf '%s\n' "$CMD_LINE" > "$CMD_LINE_FILE"

mkbootimg --header_version 2 --pagesize 4096 --base 0 \
    --kernel_offset 0 --ramdisk_offset 0 --dtb_offset 0 \
    --kernel "$KERNEL_BUNDLE/Image.gz" \
    --ramdisk "$INITRD" \
    --dtb "$KERNEL_BUNDLE/qcom/apq8016-sbc.dtb" \
    --cmdline "$CMD_LINE" \
    --output "$BOOT_IMAGE"

# 7. Structural verification.
lsinitrd "$INITRD" > "$LOGS/lsinitrd.txt" 2>&1
rm -rf "$OUT_DIR/unpacked"; mkdir -p "$OUT_DIR/unpacked"
unpack_bootimg --boot_img "$BOOT_IMAGE" --out "$OUT_DIR/unpacked" \
    > "$LOGS/unpack_bootimg.txt" 2>&1
cmp "$OUT_DIR/unpacked/kernel" "$KERNEL_BUNDLE/Image.gz"
cmp "$OUT_DIR/unpacked/dtb" "$KERNEL_BUNDLE/qcom/apq8016-sbc.dtb"
cmp "$OUT_DIR/unpacked/ramdisk" "$INITRD"

cat > "$OUT_DIR/build-info.txt" <<EOF
kernel bundle      $KERNEL_BUNDLE
kernel version     $KVER
deployment         $DEP
ostree path        $OSTREE_PATH
run token          $RUN_TOKEN
export id          $EXPORT_ID
product id         $PRODUCT_ID
cow size           $COW_SIZE
autologin root     $AUTOLOGIN_ROOT
edid override      ${EDID_OVERRIDE:-<none>}
zram from initrd   $ZRAM
drop dm udev rules $DROP_DM_UDEV_RULES
cmdline            $CMD_LINE
EOF

log "initrd:     $INITRD ($(stat -c%s "$INITRD") bytes)"
log "boot image: $BOOT_IMAGE ($(stat -c%s "$BOOT_IMAGE") bytes)"
