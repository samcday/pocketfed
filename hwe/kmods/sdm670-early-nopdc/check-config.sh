#!/bin/sh
# SPDX-License-Identifier: MIT
# Verify every required Kconfig symbol is =y or =m in a kernel .config.
#
# usage: check-config.sh <kernel.config> [required-configs]
#
# With no symbol list it reads the required-configs file next to this script.

set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "usage: check-config.sh <kernel.config> [required-configs]" >&2
    exit 2
fi

config=$1
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
symbols=${2:-"$script_dir/required-configs"}

[ -f "$config" ] || { echo "check-config: no such config: $config" >&2; exit 2; }
[ -f "$symbols" ] || { echo "check-config: no such symbol list: $symbols" >&2; exit 2; }

missing=0
checked=0
while IFS= read -r line || [ -n "$line" ]; do
    symbol=$(printf '%s\n' "$line" | sed -e 's/#.*//' -e 's/[[:space:]]//g')
    [ -n "$symbol" ] || continue
    checked=$((checked + 1))
    if grep -qx "CONFIG_${symbol}=y" "$config" || grep -qx "CONFIG_${symbol}=m" "$config"; then
        echo "ok      ${symbol}"
    else
        echo "MISSING ${symbol}"
        missing=$((missing + 1))
    fi
done < "$symbols"

echo "check-config: ${checked} required, ${missing} missing"
[ "$missing" -eq 0 ]
