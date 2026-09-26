#!/bin/bash
# Guest-only diagnostic. No workload, PM-policy change or device reset is issued.
set -euo pipefail
umask 077

usage() {
    cat <<'USAGE'
Usage:
  trace-vbif-halt.sh start /run/UNUSED_STATE_DIR
  trace-vbif-halt.sh mark  /run/STATE_DIR label...
  trace-vbif-halt.sh stop  /run/STATE_DIR
  trace-vbif-halt.sh --print-probes a3vbif_0_0

start creates a unique trace instance and one entry probe and one return probe in its own group.
mark adds a label only to that instance. stop saves trace/profile/stats and
removes only those probes and that instance; saved state/evidence remains.
Root and an already mounted, writable tracefs are required. No mount is made.
USAGE
}
fail() { printf 'error: %s\n' "$*" >&2; exit 1; }
valid_group() { [[ "$1" =~ ^a3vbif_[0-9]+_[0-9]+$ ]]; }
functions=(preclear a3xx_pm_suspend)
probe_lines() {
    local fn
    for fn in "${functions[@]}"; do
        if [[ "$fn" == preclear ]]; then
            printf '%s\n' "p:$group/${group}_preclear msm:a3xx_pm_suspend+0xb4 poll_ret=%x19:s32 request=+0xc200(+0xc8(%x22)):x32 ack=+0xc204(+0xc8(%x22)):x32"
            continue
        fi
        # $retval is kernel fetch syntax, intentionally not a shell variable.
        # shellcheck disable=SC2016
        printf 'r64:%s/%s_%s msm:%s ret=$retval:s32\n' "$group" "$group" "$fn" "$fn"
    done
}
profile() {
    # This kernel's kprobe_profile prints the event name, without its group.
    awk -v p="${group}_" 'index($1, p) == 1' "$tracefs/kprobe_profile"
}
teardown() {
    local fn event result=0
    if [[ -d "$instance" ]]; then
        printf '0\n' > "$instance/tracing_on" || result=1
        for fn in "${functions[@]}"; do
            event="${group}_${fn}"
            if [[ -e "$instance/events/$group/$event/enable" ]]; then
                printf '0\n' > "$instance/events/$group/$event/enable" || result=1
            fi
        done
    fi
    for fn in "${functions[@]}"; do
        event="${group}_${fn}"
        if [[ -d "$tracefs/events/$group/$event" ]]; then
            printf -- '-:%s/%s\n' "$group" "$event" >> "$tracefs/kprobe_events" || result=1
        fi
    done
    if [[ -d "$instance" ]]; then
        rmdir -- "$instance" || result=1
    fi
    return "$result"
}
load_state() {
    [[ -d "$state" && ! -L "$state" ]] || fail 'state directory missing or symlinked'
    [[ $(stat -c %u -- "$state") == 0 ]] || fail 'state directory must belong to root'
    [[ $(cat "$state/format") == adreno-vbiftrace-v1 ]] || fail 'wrong state format'
    read -r group < "$state/group"
    read -r tracefs < "$state/tracefs"
    valid_group "$group" || fail 'invalid saved event group'
    case "$tracefs" in /sys/kernel/tracing|/sys/kernel/debug/tracing) ;; *) fail 'invalid tracefs path' ;; esac
    instance="$tracefs/instances/$group"
}

command=${1:---help}
case "$command" in
    --help|-h) usage; exit 0 ;;
    --print-probes)
        [[ $# == 2 ]] || fail 'supply one group name'
        group=$2; valid_group "$group" || fail 'invalid group name'; probe_lines; exit 0 ;;
    start|mark|stop) ;;
    *) usage >&2; exit 2 ;;
esac
[[ $EUID == 0 ]] || fail 'run as root in the guest'
[[ $# -ge 2 ]] || fail 'state directory required'
state=$2
[[ "$state" == /* ]] || fail 'state directory must be an absolute path'

if [[ "$command" == start ]]; then
    [[ $# == 2 ]] || fail 'start accepts only its new state directory'
    tracefs=
    for candidate in /sys/kernel/tracing /sys/kernel/debug/tracing; do
        if [[ -w "$candidate/kprobe_events" && -d "$candidate/instances" ]]; then
            tracefs=$candidate; break
        fi
    done
    [[ -n "$tracefs" ]] || fail 'writable mounted tracefs with kprobe_events not found'
    [[ -d /sys/module/msm ]] || fail 'msm must already be loaded'
    # These register/field/instruction offsets are valid only for this binary.
    loaded_note=$(sha256sum /sys/module/msm/notes/.note.gnu.build-id | cut -d' ' -f1)
    [[ "$loaded_note" == d0c1a71c7555e24ea32914c70cd8fd654bb35bf4141b63eae9a657d98cf19091 ]] || fail 'requires the exact audited Fedora stock MSM module'
    group="a3vbif_$(date +%s)_$$"
    valid_group "$group" || fail 'could not form unique group'
    instance="$tracefs/instances/$group"
    [[ ! -e "$instance" && ! -e "$tracefs/events/$group" ]] || fail 'name collision; nothing changed'
    mkdir -- "$state"  # Refuse an existing directory, even if it looks like ours.
    printf '%s\n' adreno-vbiftrace-v1 > "$state/format"
    printf '%s\n' "$group" > "$state/group"
    printf '%s\n' "$tracefs" > "$state/tracefs"
    printf '%s\n' starting > "$state/status"
    # Called indirectly by the EXIT trap below.
    # shellcheck disable=SC2329
    startup_cleanup() {
        local result=$?
        if (( result != 0 )); then
            teardown || true
            printf '%s\n' startup-failed > "$state/status"
            printf 'Startup failed; scoped cleanup attempted; evidence: %s\n' "$state" >&2
        fi
        return "$result"
    }
    trap startup_cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    mkdir -- "$instance"
    printf '0\n' > "$instance/tracing_on"
    # Change only instance-local controls. In particular, never write trace_options.
    printf '256\n' > "$instance/buffer_size_kb"
    printf 'mono\n' > "$instance/trace_clock"
    probe_lines > "$state/probe-definitions.txt"
    while IFS= read -r definition; do
        printf '%s\n' "$definition" >> "$tracefs/kprobe_events"
    done < "$state/probe-definitions.txt"
    for fn in "${functions[@]}"; do
        event="${group}_${fn}"
        cat "$instance/events/$group/$event/format" > "$state/$fn.format"
        printf '1\n' > "$instance/events/$group/$event/enable"
    done
    {
        date --utc --iso-8601=seconds
        uname -a
        printf 'group=%s\ntracefs=%s\n' "$group" "$tracefs"
        printf 'clock: '; cat "$instance/trace_clock"
        printf 'buffer KiB per CPU: '; cat "$instance/buffer_size_kb"
        if [[ -r /sys/module/msm/notes/.note.gnu.build-id ]]; then
            sha256sum /sys/module/msm/notes/.note.gnu.build-id
            od -An -tx1 -v /sys/module/msm/notes/.note.gnu.build-id
        fi
    } > "$state/metadata.txt"
    profile > "$state/profile.before.txt"
    printf '1\n' > "$instance/tracing_on"
    printf 'adreno-vbiftrace START\n' > "$instance/trace_marker"
    printf '%s\n' active > "$state/status"
    trap - EXIT INT TERM
    printf 'Tracing active in %s; state: %s\n' "$instance" "$state"
    exit 0
fi

load_state
if [[ "$command" == mark ]]; then
    [[ $# -ge 3 ]] || fail 'mark requires a label'
    [[ -d "$instance" ]] || fail 'trace instance is absent'
    shift 2
    printf '%s\n' "$*" > "$instance/trace_marker"
    exit 0
fi

[[ $# == 2 ]] || fail 'stop accepts only its state directory'
if [[ ! -d "$instance" ]]; then
    [[ $(cat "$state/status") == stopped ]] && { printf 'Already stopped: %s\n' "$state"; exit 0; }
    fail 'trace instance missing; retained state may require manual scoped cleanup'
fi
result=0
# Preserve the interrupt/error status while removing our own tracing resources.
# Called indirectly by the EXIT trap below.
# shellcheck disable=SC2329
stop_cleanup() {
    local status=$?
    trap - EXIT INT TERM
    if teardown; then
        printf '%s\n' stopped-incomplete > "$state/status" || true
    else
        printf '%s\n' cleanup-incomplete > "$state/status" || true
    fi
    return "$status"
}
trap stop_cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
printf 'adreno-vbiftrace STOP\n' > "$instance/trace_marker" || result=1
printf '0\n' > "$instance/tracing_on" || result=1
cat "$instance/trace" > "$state/trace.txt" || result=1
profile > "$state/profile.after.txt" || result=1
{
    for stats in "$instance"/per_cpu/cpu*/stats; do
        [[ -r "$stats" ]] || continue
        printf '\n%s\n' "$stats"
        cat "$stats"
    done
} > "$state/buffer-stats.txt" || result=1
if teardown; then
    printf '%s\n' stopped > "$state/status"
else
    result=1
    printf '%s\n' cleanup-incomplete > "$state/status"
    printf 'Scoped cleanup incomplete; do not clear global tracing. Inspect %s\n' "$state" >&2
fi
trap - EXIT INT TERM
printf 'Trace and diagnostics saved in %s\n' "$state"
exit "$result"
