#!/bin/bash
set -euo pipefail
lab_source=$1
auth_source=$2
qsee_source=$3
trial_output=$4
mkdir -p "$trial_output"
compiler=${CC:-/usr/bin/gcc}
flags=(-O2 -g -std=gnu11 -Wall -Wextra -Werror -I"$auth_source" -I"$qsee_source")
"$compiler" "${flags[@]}" "$lab_source/test-authorization.c" \
    "$qsee_source/protocol.c" "$qsee_source/gatekeeper-protocol.c" \
    -Wl,--wrap=fsync -o "$trial_output/test-authorization"
"$trial_output/test-authorization"
"$compiler" "${flags[@]}" "$lab_source/check-authorization.c" \
    "$auth_source/auth-store.c" "$auth_source/auth-backend.c" \
    "$qsee_source/protocol.c" "$qsee_source/gatekeeper-protocol.c" \
    "$qsee_source/sensor.c" "$qsee_source/qsee-transport.c" \
    -o "$trial_output/check-authorization"
sha256sum "$trial_output/check-authorization"
