#!/bin/bash

# Liveboot-only dracut module for the DB410c image.
#
# liveboot is diagnosed over the UART, but the served Phosh image locks root's
# password, so a getty alone is no way in. This installs a pre-pivot hook that
# drops an autologin drop-in for the console getty onto the copy-on-write root,
# and a pre-udev hook that loads zram from the initrd so the served root (which
# cannot load this kernel's modules) still gets swap on the 1 GB board.

check() {
    return 0
}

depends() {
    # The pre-pivot hook is run by dracut-pre-pivot.service, which comes from
    # the systemd module. The smoo module already depends on it, but stating it
    # here keeps this module meaningful on its own.
    echo systemd
    return 0
}

installkernel() {
    # zram is never auto-loaded by udev, so --add-drivers alone would not pull
    # it in under hostonly; install it and its lz4 back ends explicitly.
    hostonly='' instmods zram lz4_compress lz4hc_compress
}

install() {
    inst_hook pre-udev 40 "$moddir/pocketfed-liveboot-zram.sh"
    inst_hook pre-pivot 99 "$moddir/pocketfed-liveboot-autologin.sh"
}
