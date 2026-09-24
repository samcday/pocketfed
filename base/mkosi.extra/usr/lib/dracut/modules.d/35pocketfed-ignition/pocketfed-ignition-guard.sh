#!/bin/bash
# Refuse Ignition configs PocketFed cannot honour, before anything acts on
# them.
#
# Checks the user config fetch-offline cached, with any ignition.config.merge
# children already resolved (Butane's variant filters only see the top-level
# document), and every base config fragment Ignition will merge into it.
set -euo pipefail

config=/run/ignition.json
state=/run/ignition/state

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

# Without a user config Ignition still runs, with the base configs alone,
# and leaves a core user nobody can log in as. That means the config never
# reached the initrd.
jq -e 'any(.fetchedConfigs[]?; .kind == "user")' "$state" >/dev/null 2>&1 ||
    fail "no user config was supplied; is it appended to this initrd? (see base/ignition.md)"

platform=metal
if [[ -f /run/ignition.env ]]; then
    platform=$(sed -n 's/^PLATFORM_ID=//p' /run/ignition.env)
fi
# The directories Ignition merges base fragments from, honouring the same
# overrides Ignition does.
configs=("$config")
for dir in \
    "${IGNITION_SYSTEM_RUNTIME_CONFIG_DIR:-/run/ignition}" \
    "${IGNITION_SYSTEM_LOCAL_CONFIG_DIR:-/etc/ignition}" \
    "${IGNITION_SYSTEM_CONFIG_DIR:-/usr/lib/ignition}"
do
    for fragment in "$dir/base.d"/* "$dir/base.platform.d/$platform"/*; do
        [[ -f $fragment ]] && configs+=("$fragment")
    done
done

# Phones keep their OEM partition tables and the root is the userdata
# filesystem, so storage layout and kernel arguments are out of scope.
for file in "${configs[@]}"; do
    unsupported=$(jq -r '
        [
            (if ((.kernelArguments.shouldExist // []) + (.kernelArguments.shouldNotExist // [])) | length > 0
                then "kernelArguments" else empty end),
            (.storage // {} | to_entries[]
                | select(.key == "disks" or .key == "filesystems" or .key == "luks" or .key == "raid")
                | select((.value // []) | length > 0)
                | "storage.\(.key)")
        ] | join(", ")
    ' "$file" 2>/dev/null) || fail "$file is not a JSON Ignition config"
    if [[ -n $unsupported ]]; then
        fail "unsupported config sections in $file: $unsupported"
    fi
done

echo "pocketfed-ignition-guard: config accepted"
