#!/usr/bin/env bash
# Validate payload destinations through dry runs; no root, copies or mounts.
set -euo pipefail

HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
TEST_TMP=$(mktemp -d)
trap 'rm -rf -- "$TEST_TMP"' EXIT
: > "$TEST_TMP/source.img"
mkdir "$TEST_TMP/payload"

run_plan() {
    bash "$HERE/bake-payload.sh" --src "$TEST_TMP/source.img" \
        --dst "$TEST_TMP/destination.img" --dry-run "$@" \
        > "$TEST_TMP/stdout" 2> "$TEST_TMP/stderr"
}

expect_valid() {
    local expected=$1
    shift
    if ! run_plan "$@"; then
        cat "$TEST_TMP/stderr" >&2
        echo "valid payload name was rejected: $expected" >&2
        exit 1
    fi
    grep -Fq -- "guest /opt/$expected" "$TEST_TMP/stdout"
    grep -Fxq -- '(dry run)' "$TEST_TMP/stdout"
    [ ! -e "$TEST_TMP/destination.img" ]
}

expect_invalid() {
    if run_plan "$@"; then
        echo "invalid payload name was accepted: $*" >&2
        exit 1
    fi
    grep -Fq -- 'invalid --name:' "$TEST_TMP/stderr"
    # Validation must finish before a destination is planned or created.
    [ ! -s "$TEST_TMP/stdout" ]
    [ ! -e "$TEST_TMP/destination.img" ]
}

for name in adreno trial-v2 .hidden 'trial with spaces' --trial; do
    expect_valid "$name" --payload "$TEST_TMP/payload" --name "$name"
done
expect_valid payload --payload "$TEST_TMP/payload"
expect_valid payload --payload "$TEST_TMP/payload" --name ''

for name in . .. / ../outside a/b /absolute 'trailing/'; do
    expect_invalid --payload "$TEST_TMP/payload" --name "$name"
done
# Default names receive the same check as explicit names.
expect_invalid --payload "$TEST_TMP/."
expect_invalid --payload "$TEST_TMP/.."
expect_invalid --payload /
# Command substitution strips trailing newlines from basename's output.
mkdir "$TEST_TMP/"$'\n'
expect_invalid --payload "$TEST_TMP/"$'\n'

echo 'bake-payload dry-run name checks passed'
