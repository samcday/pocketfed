#!/bin/bash
# Relabel paths under /sysroot with the deployment's own SELinux policy.
# Adapted from Fedora CoreOS's coreos-relabel.
set -euo pipefail

if [[ $# -eq 0 ]]; then
    echo "usage: $0 PATTERN..." >&2
    exit 2
fi

[[ -f /sysroot/etc/selinux/config ]] || exit 0

# shellcheck disable=SC1091
. /sysroot/etc/selinux/config
if [[ -z ${SELINUXTYPE:-} ]]; then
    echo "pocketfed-ignition-relabel: no SELINUXTYPE in /sysroot/etc/selinux/config" >&2
    exit 1
fi

file_contexts=/sysroot/etc/selinux/$SELINUXTYPE/contexts/files/file_contexts
if [[ ! -f $file_contexts ]]; then
    echo "pocketfed-ignition-relabel: missing $file_contexts" >&2
    exit 1
fi

patterns=()
for pattern in "$@"; do
    patterns+=("/sysroot/$pattern")
done
setfiles -vFi0 -r /sysroot "$file_contexts" "${patterns[@]}"
