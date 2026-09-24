#!/bin/bash
# shellcheck disable=SC2154 # dracut provides moddir, initdir and the unit dirs
# PocketFed's Ignition integration. See base/ignition.md.
#
# This module is opt-in: only provisioning initrds request it, with
# `dracut --add pocketfed-ignition`. Never name it from dracut.conf.d, or
# rpm-ostree's on-device regenerations would carry Ignition into every
# normal boot.
#
# It installs the Ignition binary, generator and stage units shipped by
# Fedora's ignition package (the 30ignition module), but does not depend on
# that module. 30ignition depends on qemu, url-lib and network: PocketFed
# device configs omit qemu, and the network stack would add NetworkManager,
# dbus and curl to initrds that already press against Android boot image
# limits. Configs are offline-only until PocketFed has initrd networking.

pocketfed_ignition_moddir() {
    dracut_module_path ignition
}

check() {
    local igndir
    igndir=$(pocketfed_ignition_moddir) || return 1
    [[ -x $igndir/ignition ]] || return 1

    # Never auto-include: dracut silently drops auto-included modules whose
    # dependencies fail, and normal boots must not carry Ignition.
    return 255
}

depends() {
    echo systemd ostree
}

# dracut ignores install()'s status and only logs failed installs, so a
# missing file must abort the build explicitly.
pocketfed_ignition_fail() {
    dfatal "pocketfed-ignition: $*"
    exit 1
}

pocketfed_ignition_unit() {
    local source=$1 unit=$2 target=${3:-ignition-complete.target}

    inst_simple "$source/$unit" "$systemdsystemunitdir/$unit" ||
        pocketfed_ignition_fail "cannot install $source/$unit"
    $SYSTEMCTL -q --root="$initdir" add-requires "$target" "$unit" || exit 1
}

install() {
    local igndir unit target
    igndir=$(pocketfed_ignition_moddir) ||
        pocketfed_ignition_fail "Fedora's 30ignition module is not installed"

    # Tools used by Ignition's passwd and relabel steps and by PocketFed's
    # units. Storage tools are deliberately absent: the guard rejects disks,
    # filesystems, LUKS and RAID before those stages run.
    inst_multiple \
        basename \
        chmod \
        groupadd \
        groupdel \
        groupmod \
        head \
        jq \
        lsblk \
        mountpoint \
        realpath \
        sed \
        setfiles \
        stat \
        sync \
        systemd-tmpfiles \
        useradd \
        userdel \
        usermod ||
        pocketfed_ignition_fail "missing initrd tools"

    # Unlike 30ignition, also install the libraries it links (libblkid,
    # libresolv).
    inst_binary "$igndir/ignition" /usr/bin/ignition ||
        pocketfed_ignition_fail "cannot install $igndir/ignition"
    inst_script "$igndir/ignition-kargs-helper.sh" /usr/sbin/ignition-kargs-helper ||
        pocketfed_ignition_fail "cannot install the kargs helper"
    inst_simple "$igndir/ignition-generator" \
        "$systemdutildir/system-generators/ignition-generator" ||
        pocketfed_ignition_fail "cannot install the generator"

    for target in complete subsequent diskful diskful-subsequent; do
        inst_simple "$igndir/ignition-$target.target" \
            "$systemdsystemunitdir/ignition-$target.target" ||
            pocketfed_ignition_fail "cannot install ignition-$target.target"
    done

    for unit in \
        ignition-fetch-offline.service \
        ignition-fetch.service \
        ignition-kargs.service \
        ignition-disks.service \
        ignition-mount.service \
        ignition-files.service
    do
        pocketfed_ignition_unit "$igndir" "$unit"
    done
    pocketfed_ignition_unit "$igndir" ignition-remount-sysroot.service \
        ignition-diskful.target

    for unit in mount-var populate-var guard; do
        inst_script "$moddir/pocketfed-ignition-$unit.sh" \
            "/usr/libexec/pocketfed-ignition-$unit" ||
            pocketfed_ignition_fail "cannot install pocketfed-ignition-$unit"
        pocketfed_ignition_unit "$moddir" "pocketfed-ignition-$unit.service"
    done
    inst_script "$moddir/pocketfed-ignition-relabel.sh" \
        /usr/libexec/pocketfed-ignition-relabel ||
        pocketfed_ignition_fail "cannot install pocketfed-ignition-relabel"
    pocketfed_ignition_unit "$moddir" pocketfed-ignition-finish.service

    # FCOS-compatible default admin account; see base/ignition.md for how a
    # provisioning boot can override it.
    inst_simple "$moddir/00-core.ign" /usr/lib/ignition/base.d/00-core.ign ||
        pocketfed_ignition_fail "cannot install 00-core.ign"
}
