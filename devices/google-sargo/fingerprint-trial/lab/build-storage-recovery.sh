#!/bin/bash
set -euo pipefail
lab_source=$1
auth_source=$2
qsee_source=$3
trial_output=$4
mkdir -p "$trial_output"
compiler=${CC:-/usr/bin/gcc}
flags=(-O2 -g -std=gnu11 -Wall -Wextra -Werror -I"$auth_source" -I"$qsee_source")
"$compiler" "${flags[@]}" "$lab_source/test-recover-storage-once.c" \
    "$qsee_source/gatekeeper-protocol.c" -Wl,--wrap=fsync \
    -o "$trial_output/test-recover-storage-once"
"$trial_output/test-recover-storage-once"
"$compiler" "${flags[@]}" "$lab_source/recover-storage-once.c" \
    "$auth_source/auth-backend.c" "$qsee_source/gatekeeper-protocol.c" \
    "$qsee_source/qsee-transport.c" -o "$trial_output/recover-storage-once"
sha256sum "$trial_output/recover-storage-once"
