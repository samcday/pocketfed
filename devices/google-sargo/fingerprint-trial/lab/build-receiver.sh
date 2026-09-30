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
flags=(-O2 -g -Wall -Wextra -Werror -std=gnu11 -D_GNU_SOURCE
       -I"$qsee_source/include" -I"$trial_source")
if [[ ${RPMB_DIAGNOSTICS:-0} == 1 ]]; then
    flags+=(-DSARGO_RPMB_DIAGNOSTICS)
fi
"$compiler" -O2 -Wall -Wextra -Werror -I"$trial_source" \
    "$trial_source/test-lab-device.c" -o "$trial_output/test-lab-device"
"$trial_output/test-lab-device"
"$compiler" "${flags[@]}" "$trial_source/test-rpmb-protocol.c" \
    -o "$trial_output/test-rpmb-protocol"
"$trial_output/test-rpmb-protocol"
"$compiler" -O2 -Wall -Wextra -Werror -I"$trial_source" \
    "$trial_source/test-rpmb-mmc.c" -o "$trial_output/test-rpmb-mmc"
"$trial_output/test-rpmb-mmc"
"$compiler" "${flags[@]}" "$trial_source/test-rpmb-supplicant.c" \
    "$trial_source/rpmb-protocol.c" "${common[@]}" "${transport[@]}" \
    -pthread -o "$trial_output/test-rpmb-supplicant"
"$trial_output/test-rpmb-supplicant"
"$compiler" "${flags[@]}" "$trial_source/rpmb-supplicant.c" \
    "$trial_source/rpmb-protocol.c" "$trial_source/rpmb-mmc.c" \
    "${common[@]}" "${transport[@]}" -pthread -o "$trial_output/rpmb-supplicant-ro"
sha256sum "$trial_output/rpmb-supplicant-ro"
