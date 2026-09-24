#!/bin/bash
# Create the stateroot /var layout before Ignition creates users in it.
#
# A freshly deployed stateroot /var holds only what the image put there, and
# /home and /root are symlinks into it. Adapted from Fedora CoreOS's
# ignition-ostree-populate-var.
set -euo pipefail

for subdir in lib log home roothome opt srv usrlocal mnt; do
    # Existing directories belong to the image or an earlier boot; leave them
    # and their labels alone.
    [[ -d /sysroot/var/$subdir ]] && continue

    if [[ $subdir == lib || $subdir == log ]]; then
        # Their tmpfiles.d entries name users and groups that may not resolve
        # from the initrd.
        mkdir -p "/sysroot/var/$subdir"
    else
        systemd-tmpfiles --create --boot --root=/sysroot --prefix="/var/$subdir"
    fi
    [[ -d /sysroot/var/$subdir ]] || {
        echo "pocketfed-ignition-populate-var: /var/$subdir was not created" >&2
        exit 1
    }

    /usr/libexec/pocketfed-ignition-relabel "/var/$subdir"
done
