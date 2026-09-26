#!/bin/bash
# Repack the 2026-09-21 reprov liveboot image (stock Fedora 7.3.0-0.rc3 kernel,
# same initrd) for the a306 soak root.
# usage: mkboot.sh EXPORT_ID TOKEN [hw1]
#   hw1: append a cpio with /etc/modprobe.d/a306-ci.conf setting
#        msm num_hw_submissions=1 (CI's .a306-piglit-gl BM_KERNEL_EXTRA_ARGS);
#        msm loads from the initrd, so the option applies at probe.
set -euo pipefail
W=/var/home/sam/tmp/a306-piglit-20260924
B=$W/boot/base
ID=$1 TOKEN=$2 MODE=${3:-}
OUT=$W/boot/liveboot-$TOKEN.img
old=$(sed -n "s/^.*--cmdline '\(.*\)'.*$/\1/p" $B/mkbootimg-args.txt)
[ -n "$old" ]
new=$(printf '%s' "$old" | sed -e "s/rd\.smoo\.root=[0-9]*/rd.smoo.root=$ID/" -e "s/pocketfed\.liveboot=[^ ]*/pocketfed.liveboot=$TOKEN/")
[ ${#new} -le 511 ] || { echo "cmdline too long: ${#new}"; exit 1; }
RD=$B/ramdisk
if [ "$MODE" = hw1 ]; then
  T=$(mktemp -d)
  mkdir -p $T/etc/modprobe.d
  echo 'options msm num_hw_submissions=1' > $T/etc/modprobe.d/a306-ci.conf
  (cd $T && find etc | cpio -o -H newc -R +0:+0 --quiet | zstd -q -19) > $W/boot/hw1.cpio.zst
  cat $B/ramdisk $W/boot/hw1.cpio.zst > $W/boot/ramdisk-hw1
  RD=$W/boot/ramdisk-hw1
  rm -rf $T
fi
mkbootimg --header_version 2 --kernel $B/kernel --ramdisk $RD --dtb $B/dtb \
  --pagesize 0x00001000 --base 0x00000000 --kernel_offset 0x00000000 \
  --ramdisk_offset 0x00000000 --second_offset 0x00000000 --tags_offset 0x00000100 \
  --dtb_offset 0x0000000000000000 --board '' --cmdline "$new" -o $OUT
echo "cmdline (${#new}): $new"
sha256sum $OUT
