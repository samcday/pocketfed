#!/bin/bash
# mkboot-msm.sh EXPORT_ID TOKEN MSM_KO [hw1]
# Planning artefact (2026-09-26), NOT run. Same repack as tools/mkboot.sh (stock Fedora
# 7.3.0-0.rc3 kernel + its dracut initrd + dtb, Android boot header v2), plus one appended
# zstd cpio that overwrites usr/lib/modules/$KREL/kernel/drivers/gpu/drm/msm/msm.ko.xz.
#
# Verified: init/initramfs.c do_name() opens an existing regular file with O_TRUNC, so a
# later archive replaces it; the base ramdisk's msm.ko.xz (sha256 5c465d99...) is a single
# xz stream with CRC32, like kbuild's "xz --check=crc32 --lzma2=dict=1MiB"; msm loads from
# the initrd (udev modalias), which is why hw1's modprobe.d append worked. Only the file is
# archived (no directory entries), so no initramfs directory modes change.
set -euo pipefail
W=/var/home/sam/tmp/a306-piglit-20260924
B=$W/boot/base
KREL=7.3.0-0.rc3.260918g5dd1818b15d9.36.fc46.aarch64
ID=$1 TOKEN=$2 KO=$3 MODE=${4:-}
OUT=$W/boot/liveboot-$TOKEN.img
[ "$(modinfo -F vermagic "$KO")" = "$KREL SMP preempt mod_unload aarch64" ]
old=$(sed -n "s/^.*--cmdline '\(.*\)'.*$/\1/p" $B/mkbootimg-args.txt)
new=$(printf '%s' "$old" | sed -e "s/rd\.smoo\.root=[0-9]*/rd.smoo.root=$ID/" -e "s/pocketfed\.liveboot=[^ ]*/pocketfed.liveboot=$TOKEN/")
[ ${#new} -le 511 ] || { echo "cmdline too long: ${#new}"; exit 1; }
T=$(mktemp -d)
D=usr/lib/modules/$KREL/kernel/drivers/gpu/drm/msm
mkdir -p $T/$D
xz --check=crc32 --lzma2=dict=1MiB -T1 -c "$KO" > $T/$D/msm.ko.xz
chmod 0644 $T/$D/msm.ko.xz
if [ "$MODE" = hw1 ]; then
  mkdir -p $T/etc/modprobe.d
  echo 'options msm num_hw_submissions=1' > $T/etc/modprobe.d/a306-ci.conf
fi
(cd $T && find . -type f | sed 's#^\./##' | cpio -o -H newc -R +0:+0 --quiet | zstd -q -19) > $W/boot/msm-$TOKEN.cpio.zst
cat $B/ramdisk $W/boot/msm-$TOKEN.cpio.zst > $W/boot/ramdisk-$TOKEN
rm -rf $T
mkbootimg --header_version 2 --kernel $B/kernel --ramdisk $W/boot/ramdisk-$TOKEN --dtb $B/dtb \
  --pagesize 0x00001000 --base 0x00000000 --kernel_offset 0x00000000 \
  --ramdisk_offset 0x00000000 --second_offset 0x00000000 --tags_offset 0x00000100 \
  --dtb_offset 0x0000000000000000 --board '' --cmdline "$new" -o $OUT
# self-check: the last copy of msm.ko.xz in the concatenated ramdisk is ours
zstd -dc $W/boot/msm-$TOKEN.cpio.zst | cpio -t --quiet
echo "cmdline (${#new}): $new"
ls -l $OUT; sha256sum $OUT "$KO"
