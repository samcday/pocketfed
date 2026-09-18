#!/bin/sh
# SPDX-License-Identifier: MIT
# Fail if any undefined symbol in a built .ko is absent from Module.symvers.
#
# usage: check-exports.sh <module.ko[.xz|.gz|.zst]> <Module.symvers>
#
# The target kernel's Module.symvers lists one symbol per line as
#   <crc> <symbol> <module> <export> ...
# and only exported symbols resolve a loadable module. MODVERSIONS is off for
# these kernels, so symbol names are compared without CRCs.

set -eu

if [ "$#" -ne 2 ]; then
    echo "usage: check-exports.sh <module.ko[.xz|.gz|.zst]> <Module.symvers>" >&2
    exit 2
fi

module=$1
symvers=$2

[ -f "$module" ] || { echo "check-exports: no such module: $module" >&2; exit 2; }
[ -f "$symvers" ] || { echo "check-exports: no such Module.symvers: $symvers" >&2; exit 2; }

work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT HUP INT TERM

raw=$work/module.ko
case "$module" in
    *.ko)    cp "$module" "$raw" ;;
    *.ko.xz) xz -dc "$module" > "$raw" ;;
    *.ko.gz) gzip -dc "$module" > "$raw" ;;
    *.ko.zst) zstd -dc "$module" > "$raw" ;;
    *) echo "check-exports: unsupported module compression: $module" >&2; exit 2 ;;
esac

nm --format=posix -u "$raw" | awk '{ print $1 }' | sort -u > "$work/undefined"
awk -F'\t' 'NF >= 2 { print $2 }' "$symvers" | sort -u > "$work/exported"

missing=0
total=0
while IFS= read -r symbol; do
    [ -n "$symbol" ] || continue
    total=$((total + 1))
    if grep -qxF "$symbol" "$work/exported"; then
        echo "U       $symbol"
    else
        echo "MISSING $symbol"
        missing=$((missing + 1))
    fi
done < "$work/undefined"

echo "check-exports: $(basename "$module") ${total} undefined, ${missing} missing from $(basename "$symvers")"
[ "$missing" -eq 0 ]
