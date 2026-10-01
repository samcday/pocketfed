#!/bin/sh
# Runs before udev, while the initrd still has this kernel's module tree.
#
# The served root belongs to another board and cannot modprobe this kernel's
# modules, and zram-generator only modprobes when /sys/class/zram-control is
# missing. Loading zram here (with its lz4 back ends) lets the served root's own
# zram-generator configure swap after switch-root; on a 1 GB board that is the
# difference between reaching the greeter and being OOM-killed.

command -v getarg > /dev/null || . /lib/dracut-lib.sh

getargbool 0 rd.smoo || exit 0
getargbool 1 rd.pocketfed.zram || exit 0

if modprobe -q zram; then
    info "pocketfed-liveboot: zram loaded from the initrd"
else
    warn "pocketfed-liveboot: could not load zram; the served root gets no swap"
fi
