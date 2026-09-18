#!/bin/bash

# Liveboot-only dracut module for the DB410c image.
#
# liveboot is diagnosed over the UART, but the served Phosh image locks root's
# password, so a getty alone is no way in. This installs a pre-pivot hook that
# drops an autologin drop-in for the console getty onto the copy-on-write root.

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

install() {
    inst_hook pre-pivot 99 "$moddir/pocketfed-liveboot-autologin.sh"
}
