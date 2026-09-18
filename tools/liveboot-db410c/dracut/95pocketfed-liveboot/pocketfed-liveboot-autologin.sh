#!/bin/sh
# Runs before switch-root with the served (copy-on-write) root at $NEWROOT.
#
# root's password in the served image is locked, so agetty's --autologin (which
# runs login -f and never prompts) is the only way to get a shell on the UART.
# systemd-getty-generator instantiates serial-getty@ttyMSM0 for the active
# console=, so a drop-in is enough; no enable symlink is needed. The write lands
# in the RAM COW layer and is gone on the next boot.

command -v getarg > /dev/null || . /lib/dracut-lib.sh

getargbool 0 rd.smoo || exit 0
getargbool 1 rd.pocketfed.autologin || exit 0
[ -n "$NEWROOT" ] || exit 0

dropin="$NEWROOT/etc/systemd/system/serial-getty@ttyMSM0.service.d"
mkdir -p "$dropin"

cat > "$dropin/10-autologin.conf" <<'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin root --noclear --keep-baud 115200,57600,38400,9600 %I $TERM
EOF

info "pocketfed-liveboot: enabled root autologin on ttyMSM0"
