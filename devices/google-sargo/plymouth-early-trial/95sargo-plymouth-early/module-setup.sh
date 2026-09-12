#!/bin/bash

check() { return 0; }
depends() { echo plymouth; }

install() {
    inst_multiple /usr/bin/timeout /usr/bin/udevadm /bin/sh
    inst_simple "$moddir/prepare-display" /usr/libexec/pocketfed-plymouth-prepare-display
    inst_simple "$moddir/pocketfed-plymouth-display.service" \
        "$systemdsystemunitdir/pocketfed-plymouth-display.service"

    # Modify only the initrd's copy. Preserve the packaged service's other
    # dependencies and let the real-root service remain unchanged.
    local unit="$initdir$systemdsystemunitdir/plymouth-start.service"
    grep -Eq '^After=.*systemd-udev-trigger[.]service' "$unit" || return 1
    sed -i '/^After=/s/systemd-udev-trigger[.]service//g' "$unit"
    cat >> "$unit" <<'EOF'

[Unit]
Wants=pocketfed-plymouth-display.service
After=pocketfed-plymouth-display.service
EOF
}
