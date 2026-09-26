#!/bin/sh
# trace-enomem.sh start|collect OUTDIR|stop   (root, on the DB410c HOST shell, not in the chroot)
#
# Planning artefact (2026-09-26), not yet run. Confirms where DRM_IOCTL_MSM_GEM_SUBMIT's
# -ENOMEM comes from on the stock Fedora 7.3.0-0.rc3.260918g5dd1818b15d9.36.fc46 kernel,
# without rebuilding anything.
#
# Facts this relies on (verified offline against the initrd's msm.ko.xz, sha256 5c465d99...):
#   * submit_create is NOT inlined: msm.ko symtab has "t submit_create" (.text+0x7fd0);
#     only submit_lookup_cmds survives among the other static helpers (as .isra.0).
#   * submit_create+0x50 is "bl __kmalloc_noprof" (size in x0, token x1, gfp w2=0x2dc0 =
#     GFP_KERNEL|__GFP_ZERO|__GFP_NOWARN); submit_create+0x54 is "cbz x0" on its result.
#     sizeof(struct msm_gem_submit)=0x160, bos[] entry 32 B, cmd entry 40 B.
#   * 7.3 slub: a >8 KiB kmalloc goes __do_kmalloc_node -> __kmalloc_large_node_noprof,
#     which emits kmem:kmalloc even when ptr==NULL; __do_kmalloc_node then emits a second
#     kmem:kmalloc with call_site = the real caller (submit_create+0x54).
#   * kmem:mm_page_alloc is emitted after the slowpath with pfn=-1 (printed page=NULL
#     pfn=0x0) when the allocation fails.
#   * drm_msm_gpu:msm_gpu_submit fires only AFTER submit_create succeeded
#     (msm_gem_submit.c:618 at 5dd1818b15d9), so a failed big submit leaves no such event.
set -eu
T=/sys/kernel/tracing
[ -e $T/kprobe_events ] || { mountpoint -q $T || mount -t tracefs nodev $T 2>/dev/null || true; }
[ -e $T/kprobe_events ] || T=/sys/kernel/debug/tracing
[ -e $T/kprobe_events ] || { echo "no tracefs"; exit 1; }
I=$T/instances/a306ev

case ${1:-} in
start)
  # --- sanity: lockdown must be none, msm symbols must be visible ---
  cat /sys/kernel/security/lockdown 2>/dev/null || true
  grep -wE 'submit_create|msm_ioctl_gem_submit' /proc/kallsyms
  grep -wE '^(submit_create|msm_ioctl_gem_submit)' $T/available_filter_functions || true

  echo 0 > $T/tracing_on
  echo nop > $T/current_tracer
  echo > $T/trace
  echo > $T/kprobe_events

  # --- probes (group a306) ---
  # kretprobe with entry args (supported since 6.9; documented at 5dd1818b15d9)
  # arm64 ABI, confirmed in the disassembly: nr_bos arrives in w4 ($arg5), nr_cmds in w5 ($arg6)
  if ! echo 'r:a306/subcr msm:submit_create nr_bos=$arg5:u32 nr_cmds=$arg6:u32 ret=$retval:x64' >> $T/kprobe_events; then
    cat $T/error_log | tail -3
    echo 'p:a306/subcr_in msm:submit_create nr_bos=$arg5:u32 nr_cmds=$arg6:u32' >> $T/kprobe_events
    echo 'r:a306/subcr msm:submit_create ret=$retval:x64' >> $T/kprobe_events
  fi
  echo 'r:a306/gemsub msm:msm_ioctl_gem_submit ret=$retval:s32' >> $T/kprobe_events
  # optional, exact-binary only: the kzalloc result itself (x20 = nr_bos*32 + 0x160 at this point)
  echo 'p:a306/subcr_kz msm:submit_create+0x54 ptr=%x0:x64 hdr_bos=%x20:u64' >> $T/kprobe_events || echo "subcr_kz not placed (ok)"

  # --- instance a306ev: event evidence that must not be overwritten by function_graph ---
  mkdir -p $I
  echo boot > $I/trace_clock
  echo 2048 > $I/buffer_size_kb
  echo > $I/trace
  e() {
    [ -d "$I/events/$1" ] || { echo "missing event $1"; return 0; }
    if [ -n "${2:-}" ]; then echo "$2" > "$I/events/$1/filter" || echo "filter rejected for $1: $2"; fi
    echo 1 > "$I/events/$1/enable"
  }
  e a306/subcr    'nr_bos >= 16384'
  [ -d $I/events/a306/subcr_in ] && e a306/subcr_in 'nr_bos >= 16384'
  e a306/gemsub   'ret != 0'
  [ -d $I/events/a306/subcr_kz ] && e a306/subcr_kz 'hdr_bos >= 524288'
  e kmem/kmalloc  'bytes_req > 1000000'
  e kmem/mm_page_alloc 'order >= 8'
  e kmem/mm_page_alloc_extfrag 'alloc_order >= 8'
  e drm_msm_gpu/msm_gpu_submit 'nr_bos >= 16384'
  e compaction/mm_compaction_try_to_compact_pages 'order >= 8'
  e compaction/mm_compaction_suitable 'order >= 8'
  e compaction/mm_compaction_end
  e compaction/mm_compaction_defer_compaction 'order >= 8'
  e compaction/mm_compaction_deferred 'order >= 8'
  e vmscan/mm_vmscan_direct_reclaim_begin 'order >= 8'
  # call stack of every >1 MB kmalloc (success and failure; failure has ptr=0000000000000000)
  echo 'stacktrace if bytes_req > 1000000' > $I/events/kmem/kmalloc/trigger
  echo 1 > $I/tracing_on

  # --- top level: function_graph of the ioctl, direct callees only, with return values;
  #     freeze the buffer right after the first -ENOMEM return ---
  echo boot > $T/trace_clock
  echo 8192 > $T/buffer_size_kb
  # hook only msm, drm_exec, gpu-sched and the two kmalloc entry points: keeps the
  # system-wide function_graph overhead off the rest of the kernel on the A53s
  echo '*:mod:msm' > $T/set_ftrace_filter
  echo '*:mod:drm_exec' >> $T/set_ftrace_filter
  echo '*:mod:gpu_sched' >> $T/set_ftrace_filter
  echo '__kmalloc_noprof __kvmalloc_node_noprof' >> $T/set_ftrace_filter
  echo msm_ioctl_gem_submit > $T/set_graph_function
  echo 2 > $T/max_graph_depth
  echo 1 > $T/options/funcgraph-retval
  echo 1 > $T/options/funcgraph-proc
  echo 1 > $T/options/funcgraph-abstime
  echo function_graph > $T/current_tracer
  echo 'traceoff:1 if ret == -12' > $T/events/a306/gemsub/trigger
  echo 1 > $T/tracing_on
  echo "trace-enomem: armed ($T, instance a306ev)"
  ;;
collect)
  O=${2:?outdir}; mkdir -p "$O"
  cat $I/trace > "$O/events.txt"
  # the top-level buffer is up to 4 x 8 MiB of graph lines; only its tail (the frozen
  # failing ioctl) is worth pulling over the 115200-baud UART
  cat $T/trace | tail -n 4000 > "$O/fgraph-tail.txt"
  grep -n 'submit_create\|= -12\|0xfffffffffffffff4' "$O/fgraph-tail.txt" | tail -20
  for c in $I/per_cpu/cpu*; do echo "$(basename $c): $(grep -E 'overrun|entries' $c/stats | tr '\n' ' ')"; done > "$O/events.stats"
  cat $T/tracing_on > "$O/fgraph.tracing_on"   # 0 => the traceoff trigger fired
  cat $T/kprobe_events > "$O/kprobe_events"
  cat $T/events/a306/gemsub/trigger > "$O/gemsub.trigger"
  echo "== failed big kmallocs";  grep -c 'ptr=0000000000000000 bytes_req=1[0-9]\{6\}' "$O/events.txt" || true
  echo "== subcr -ENOMEM";        grep -c 'ret=0xfffffffffffffff4' "$O/events.txt" || true
  echo "== order>=8 alloc fails"; grep -c 'pfn=0x0 order=' "$O/events.txt" || true
  echo "== gem_submit -12";       grep -c 'ret=-12' "$O/events.txt" || true
  ;;
stop)
  echo 0 > $T/tracing_on
  echo '!traceoff' > $T/events/a306/gemsub/trigger 2>/dev/null || true
  echo nop > $T/current_tracer
  echo > $T/set_graph_function
  echo > $T/set_ftrace_filter
  echo 0 > $T/max_graph_depth
  if [ -d $I ]; then
    echo 0 > $I/tracing_on
    echo '!stacktrace' > $I/events/kmem/kmalloc/trigger 2>/dev/null || true
    for f in $I/events/*/*/enable; do echo 0 > $f 2>/dev/null || true; done
    rmdir $I
  fi
  echo > $T/kprobe_events
  echo 1 > $T/tracing_on
  ;;
*) echo "usage: $0 start | collect OUTDIR | stop"; exit 2 ;;
esac
