#!/bin/bash
# Bind the booted deployment's stateroot /var onto /sysroot/var for Ignition.
#
# ostree-prepare-root does not mount /var in a systemd initrd; the real
# root's var.mount does that after switch-root. Anything Ignition writes to
# /sysroot/var before then (home directories, SSH keys, /var files) would land
# in the deployment's own var directory and be hidden underneath var.mount.
#
# The deployment is found by identity rather than from ostree= because
# PocketFed boots it three ways: ostree=true with androidboot.slot_suffix
# (Android boot images), an explicit ostree= path (BLS), and liveboot, where
# Android bootloaders may add androidboot.* keys that prepare-root prefers
# over ostree=.
set -euo pipefail

fatal() {
    echo "pocketfed-ignition-mount-var: $*" >&2
    exit 1
}

do_mount() {
    local root_id candidate deployment='' stateroot var

    [[ -e /run/ostree-booted ]] || fatal "ostree-prepare-root has not prepared /sysroot"

    # /sysroot is a bind mount of the deployment directory, so they share an
    # inode. That no longer holds with composefs, which PocketFed disables.
    root_id=$(stat -Lc %d:%i /sysroot/)
    for candidate in /sysroot/sysroot/ostree/deploy/*/deploy/*/; do
        candidate=${candidate%/}
        [[ -L $candidate ]] && continue
        [[ $(stat -Lc %d:%i "$candidate/") == "$root_id" ]] || continue
        [[ -z $deployment ]] || fatal "more than one deployment matches /sysroot"
        deployment=$candidate
    done
    [[ -n $deployment ]] ||
        fatal "no deployment under /sysroot/sysroot/ostree is /sysroot (composefs is unsupported)"

    stateroot=${deployment%/deploy/*}
    var=$stateroot/var
    [[ -d $var && ! -L $var ]] || fatal "$var is not a directory"
    ! mountpoint -q /sysroot/var || fatal "/sysroot/var is already a mount point"

    echo "pocketfed-ignition-mount-var: deployment ${deployment#/sysroot/sysroot}"
    echo "pocketfed-ignition-mount-var: mounting ${var#/sysroot/sysroot} on /sysroot/var"
    mount --bind "$var" /sysroot/var
    mount -o remount,bind,rw /sysroot/var
}

do_umount() {
    if mountpoint -q /sysroot/var; then
        umount /sysroot/var
    fi
}

case ${1:-} in
    mount) do_mount ;;
    umount) do_umount ;;
    *) fatal "usage: $0 mount|umount" ;;
esac
