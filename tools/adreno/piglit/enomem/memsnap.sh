#!/bin/sh
# memsnap.sh TAG OUTDIR  -- one fragmentation snapshot (root; works on the host and in the
# CI chroot, which sees the host /proc and /sys via a306_mounts). Planning artefact, not yet run.
# Prints one summary line: free order-9 and order-10 blocks per zone (/proc/buddyinfo columns
# are orders 0..10 on this kernel: MAX_PAGE_ORDER=10; pageblock_order=9 on arm64 4K).
set -u
O=$2/$1; mkdir -p "$O"
cat /proc/buddyinfo    > "$O/buddyinfo"
cat /proc/pagetypeinfo > "$O/pagetypeinfo" 2>/dev/null   # 0400, root only
cat /proc/meminfo      > "$O/meminfo"
cat /proc/zoneinfo     > "$O/zoneinfo"
grep -E '^(nr_free_pages|compact_|pgalloc_|allocstall|pgscan_direct|pgsteal_direct|pgmigrate_|kswapd_|thp_fault|nr_unevictable|nr_mlock|nr_shmem )' /proc/vmstat > "$O/vmstat"
D=/sys/kernel/debug/extfrag
if [ -r $D/unusable_index ]; then cat $D/unusable_index > "$O/unusable_index"; cat $D/extfrag_index > "$O/extfrag_index"; fi
awk -v t="$1" '{o9=$14; o10=$15; printf "== %s buddy %s o9=%s o10=%s\n", t, $4, o9, o10}' /proc/buddyinfo
grep -E '^(MemFree|MemAvailable|Shmem|Unevictable|Mlocked):' /proc/meminfo | tr -s ' ' | tr '\n' ' ' | sed "s/^/== $1 /"; echo
