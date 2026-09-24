#!/bin/bash
# Refuse Ignition configs PocketFed cannot honour, before anything acts on
# them.
#
# Checks the merged config that fetch-offline cached, so directives pulled in
# through ignition.config.merge are caught as well; Butane's variant filters
# only see the top-level document.
set -euo pipefail

config=/run/ignition.json

fail() {
    echo "pocketfed-ignition-guard: $*" >&2
    exit 1
}

# There is no initrd network yet. Without this, ignition-fetch would retry
# remote resources forever.
if [[ -e /run/ignition/neednet ]]; then
    fail "the config references remote resources; embed them instead (see base/ignition.md)"
fi

[[ -f $config ]] || fail "fetch-offline did not cache a config at $config"

# Phones keep their OEM partition tables and the root is the userdata
# filesystem, so storage layout and kernel arguments are out of scope.
unsupported=$(jq -r '
    [
        (if ((.kernelArguments.shouldExist // []) + (.kernelArguments.shouldNotExist // [])) | length > 0
            then "kernelArguments" else empty end),
        (.storage // {} | to_entries[]
            | select(.key == "disks" or .key == "filesystems" or .key == "luks" or .key == "raid")
            | select((.value // []) | length > 0)
            | "storage.\(.key)")
    ] | join(", ")
' "$config")
if [[ -n $unsupported ]]; then
    fail "unsupported config sections: $unsupported"
fi

echo "pocketfed-ignition-guard: config accepted"
