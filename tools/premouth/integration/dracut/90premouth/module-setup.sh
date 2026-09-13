#!/bin/bash
# Opt-in dracut module for the experimental Premouth ABL dissolve helper.
#
# Enable from a trial configuration with:  add_dracutmodules+=" premouth "
# Nothing here is installed or activated by default.
#
# The module expects a `premouth` binary next to module-setup.sh, a packaged
# /usr/libexec/premouth on the build host, or one on the build host PATH. It
# installs the binary as /usr/libexec/premouth and enables the Type=notify
# unit on sysinit.target.

check() {
    if ! [ -x "$moddir/premouth" ] \
        && ! [ -x /usr/libexec/premouth ] \
        && ! type -P premouth >/dev/null 2>&1; then
        return 1
    fi
    # Available, but only include when explicitly requested by the trial.
    return 255
}

depends() {
    echo systemd plymouth
}

install() {
    local bin
    if [ -x "$moddir/premouth" ]; then
        bin="$moddir/premouth"
    elif [ -x /usr/libexec/premouth ]; then
        bin="/usr/libexec/premouth"
    else
        bin="$(type -P premouth)"
    fi
    [ -n "$bin" ] || return 1

    inst_binary "$bin" "/usr/libexec/premouth" || return 1
    inst_simple "$moddir/premouth.service" \
        "$systemdsystemunitdir/premouth.service" || return 1
    inst_simple "$moddir/plymouth-start.service.d/10-premouth-yield.conf" \
        "$systemdsystemunitdir/plymouth-start.service.d/10-premouth-yield.conf" || return 1

    mkdir -p "$initdir$systemdsystemunitdir/sysinit.target.wants" || return 1
    ln -sfn ../premouth.service \
        "$initdir$systemdsystemunitdir/sysinit.target.wants/premouth.service" || return 1
}
