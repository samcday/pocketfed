#!/bin/sh
# Runs before switch-root. The EDID override lives in this initrd's
# /usr/lib/firmware, which vanishes at switch-root while the served root (built
# for another board) has no copy. /run survives the pivot, and the kernel
# searches firmware_class.path first, so stage the blob there.

command -v getarg > /dev/null || . /lib/dracut-lib.sh

getargbool 0 rd.smoo || exit 0
[ -f /usr/lib/firmware/edid/1280x720.bin ] || exit 0

mkdir -p /run/pocketfed-fw/edid
cp /usr/lib/firmware/edid/1280x720.bin /run/pocketfed-fw/edid/1280x720.bin
info "pocketfed-liveboot: staged the EDID override in /run/pocketfed-fw"
