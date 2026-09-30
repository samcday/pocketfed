#!/bin/bash
set -euo pipefail
trial_source=$1
qsee_source=$2
trial_output=$3
mkdir -p "$trial_output"
compiler=${CC:-/usr/bin/gcc}
common=("$qsee_source/src/path.c" "$qsee_source/src/services.c"
        "$qsee_source/src/handle_db.c" "$qsee_source/src/fs.c" "$qsee_source/src/gpfs.c")
transport=("$qsee_source/src/transport_qseecom.c" "$qsee_source/src/notify.c")
flags=(-O2 -g -Wall -Wextra -Werror -std=gnu11 -D_GNU_SOURCE -DSARGO_RPMB_DIAGNOSTICS
       -I"$qsee_source/include" -I"$trial_source")
for test in test-rpmb-protocol test-rpmb-mmc test-lab-writer; do
    "$compiler" "${flags[@]}" "$trial_source/$test.c" -o "$trial_output/$test"
    "$trial_output/$test"
done
"$compiler" "${flags[@]}" "$trial_source/test-writer-supplicant.c" \
    "$trial_source/rpmb-protocol.c" "${common[@]}" "${transport[@]}" -pthread \
    -o "$trial_output/test-writer-supplicant"
"$trial_output/test-writer-supplicant"
"$compiler" "${flags[@]}" "$trial_source/rpmb-supplicant.c" \
    "$trial_source/rpmb-protocol.c" "$trial_source/rpmb-mmc.c" \
    "${common[@]}" "${transport[@]}" -pthread -o "$trial_output/rpmb-supplicant-trial"
sha256sum "$trial_output/rpmb-supplicant-trial"
