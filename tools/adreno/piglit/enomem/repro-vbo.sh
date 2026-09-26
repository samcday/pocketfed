#!/bin/bash
# repro-vbo.sh ARM LABEL N [VARIANT] [HOG HOGS HOG_MIB]
# Runs inside the Mesa CI test-gl chroot (a306_run lab/repro-vbo.sh ...), like run-probe.sh.
# Planning artefact (2026-09-26), not yet run.
#
# Runs ONLY spec@arb_vertex_buffer_object@vbo-subdata-many <VARIANT> N times, sequentially,
# with exactly the command line deqp-runner 0.23.3 used for it on this board (from
# evidence/b29/b29-p2-main-gpu-f2of4/*drawarrays.c3935.r1.log):
#   cd /piglit && DEQP_RUNNER_THREAD=0 MESA_DEBUG=silent PIGLIT_NO_WINDOW=1 PIGLIT_SOURCE_DIR=/piglit \
#     /piglit/bin/arb_vertex_buffer_object-vbo-subdata-many drawarrays -auto -fbo
# (piglit tests/opengl.xml.gz: command ['arb_vertex_buffer_object-vbo-subdata-many','drawarrays'],
#  type gl, run_concurrent True -> deqp-runner appends -auto -fbo; gpu toml adds PIGLIT_NO_WINDOW=1.)
#
# stderr goes to a file, never to the serial console: one failing submit makes Mesa print
# ~32 914 msm_dump_submit lines, which at 115200 baud is what stretched the r1 runtimes to
# 366-627 s in B29-B33.
#
#   VARIANT  drawarrays (default) | drawelements | drawrangeelements
#   HOG      none (default) | anon | gem   -- started before run 1, stopped after run N
#   HOGS     number of hog processes (default 7), HOG_MIB MiB each (default: auto)
set -u
ARM=$1 LABEL=$2 N=$3 VARIANT=${4:-drawarrays} HOG=${5:-none} HOGS=${6:-7} HOG_MIB=${7:-auto}
R=/tmp/results/$LABEL; mkdir -p "$R"
exec > >(tee -a "$R/runner.log") 2>&1
TR=/sys/kernel/tracing; [ -w $TR/trace_marker ] || TR=/sys/kernel/debug/tracing
mark() { for f in $TR/trace_marker $TR/instances/a306ev/trace_marker; do [ -w $f ] && echo "a306 $*" > $f; done; true; }

ln -sfn "/install-$ARM" /install
export LD_LIBRARY_PATH=/install/lib:/usr/local/lib LIBGL_DRIVERS_PATH=/install/lib/dri
export PATH=/usr/local/bin:$PATH XDG_CACHE_HOME=/tmp HOME=/root
export XDG_RUNTIME_DIR=$(mktemp --tmpdir -d xdg-runtime-XXXXXX)
rm -rf /tmp/mesa_shader_cache /tmp/mesa_shader_cache_db
echo "== $LABEL arm=$ARM variant=$VARIANT N=$N hog=$HOG x$HOGS uptime=$(cut -d' ' -f1 /proc/uptime) boot_id=$(cat /proc/sys/kernel/random/boot_id)"
echo "== msm taint=$(cat /sys/module/msm/taint 2>/dev/null) version=$(cat /sys/module/msm/version 2>/dev/null) num_hw_submissions=$(cat /sys/module/msm/parameters/num_hw_submissions)"
sha256sum /install/lib/libgallium*.so | sed 's/^/== /'
# knobs that change whether an order-9 block can be produced; record them every time
for k in min_free_kbytes watermark_scale_factor watermark_boost_factor extfrag_threshold compaction_proactiveness compact_unevictable_allowed swappiness; do
  printf '%s=%s ' $k "$(cat /proc/sys/vm/$k 2>/dev/null)"; done | sed 's/^/== vm: /'; echo
echo "== swap: $(tail -n +2 /proc/swaps | awk '{print $1":"$3":"$4}' | tr '\n' ' ') msm.enable_eviction=$(cat /sys/module/msm/parameters/enable_eviction 2>/dev/null)"

mkdir -p /tmp/.X11-unix
export DISPLAY=:0 WAYLAND_DISPLAY=wayland-0
weston --config=/a306/ci/weston.ini --socket="$WAYLAND_DISPLAY" --log "$R/weston.log" \
  --logger-scopes=log,xwm-wm-x11 --width 1920 --height 1080 --renderer=gl &
WESTON=$!
for _ in $(seq 60); do [ -S /tmp/.X11-unix/X0 ] && break; sleep 1; done
[ -S /tmp/.X11-unix/X0 ] || { echo "== weston/Xwayland not ready"; kill $WESTON; exit 90; }
export EGL_PLATFORM=surfaceless

# buddyinfo sampler (1 Hz), boot-clock seconds like trace_clock=boot
( while :; do echo "$(cut -d' ' -f1 /proc/uptime) $(awk '{printf "%s:o9=%s,o10=%s ", $4, $14, $15}' /proc/buddyinfo)"; sleep 1; done ) > "$R/buddy-1hz.log" 2>&1 &
SAMPLER=$!

HOGPIDS=()
if [ "$HOG" != none ]; then
  if [ "$HOG_MIB" = auto ]; then
    avail=$(awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo)
    # leave ~320 MiB for the test (~135 MiB of 4 KiB BO pages + Mesa + Weston headroom)
    HOG_MIB=$(( (avail - 320) / HOGS )); [ $HOG_MIB -lt 8 ] && HOG_MIB=8
  fi
  /a306/lab/memsnap.sh pre-hog "$R/snap"
  for h in $(seq $HOGS); do
    python3 /a306/lab/hog-$HOG.py $HOG_MIB > "$R/hog$h.log" 2>&1 &
    HOGPIDS+=($!); echo 1000 > /proc/$!/oom_score_adj
  done
  echo "== started $HOGS $HOG hogs x $HOG_MIB MiB: ${HOGPIDS[*]}"; sleep 20
fi

fails=0
for i in $(seq $N); do
  /a306/lab/memsnap.sh r$i-pre "$R/snap"
  mark "run $i start variant=$VARIANT hog=$HOG"
  t0=$(cut -d' ' -f1 /proc/uptime)
  ( cd /piglit && DEQP_RUNNER_THREAD=0 MESA_DEBUG=silent PIGLIT_NO_WINDOW=1 PIGLIT_SOURCE_DIR=/piglit \
      timeout -k 5 600 /piglit/bin/arb_vertex_buffer_object-vbo-subdata-many "$VARIANT" -auto -fbo ) \
      > "$R/r$i.out" 2> "$R/r$i.err"
  rc=$?
  t1=$(cut -d' ' -f1 /proc/uptime)
  mark "run $i end rc=$rc"
  enomem=$(grep -c 'submit failed: -12' "$R/r$i.err")
  nbos=$(grep -c 'msm_dump_submit.*bos\[' "$R/r$i.err")
  res=$(grep -ao 'PIGLIT: {"result": "[a-z]*"' "$R/r$i.out" | tail -1 | sed 's/.*"\([a-z]*\)"$/\1/')
  [ "$enomem" -gt 0 ] && fails=$((fails+1))
  echo "== run $i t0=$t0 t1=$t1 rc=$rc result=$res enomem=$enomem dumped_bos=$nbos"
  # keep the evidence small: head of stderr + count; tmpfs is RAM
  { head -3 "$R/r$i.err"; grep -m2 'cmd\[' "$R/r$i.err"; } > "$R/r$i.err.head"; rm -f "$R/r$i.err"
  /a306/lab/memsnap.sh r$i-post "$R/snap"
  sleep 5
done
echo "== SUMMARY $LABEL variant=$VARIANT hog=$HOG enomem_runs=$fails/$N"

for p in "${HOGPIDS[@]}"; do kill $p 2>/dev/null; done
# never a bare `wait`: it would also wait for the sampler and weston
[ ${#HOGPIDS[@]} -gt 0 ] && wait "${HOGPIDS[@]}" 2>/dev/null
kill $SAMPLER $WESTON 2>/dev/null; sleep 2; kill -9 $WESTON 2>/dev/null
cd /tmp/results && tar -c "$LABEL" | zstd -q -19 -o "/tmp/results/$LABEL.tar.zst"
sha256sum "/tmp/results/$LABEL.tar.zst"
