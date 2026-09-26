#!/bin/bash
# Run individual piglit shader_tests inside the CI chroot with the ir3
# disassembly enabled, recording GPU errors per test.
# usage: run-probe.sh ARM LABEL [--override DIR] [--repeat N] file.shader_test...
#   (paths inside the chroot; DIR holds <blake3>.asm files for IR3_SHADER_OVERRIDE_PATH)
set -u
ARM=$1 LABEL=$2; shift 2
OVR= REPEAT=1
while [ $# -gt 0 ]; do
  case $1 in
    --override) OVR=$2; shift 2 ;;
    --repeat) REPEAT=$2; shift 2 ;;
    *) break ;;
  esac
done
RESULTS_DIR=/tmp/results/$LABEL
mkdir -p "$RESULTS_DIR"
exec > >(tee -a "$RESULTS_DIR/runner.log") 2>&1
ln -sfn "/install-$ARM" /install
export LD_LIBRARY_PATH=/install/lib:/usr/local/lib
export LIBGL_DRIVERS_PATH=/install/lib/dri
export PATH=/usr/local/bin:$PATH
export XDG_CACHE_HOME=/tmp
export XDG_RUNTIME_DIR=$(mktemp --tmpdir -d xdg-runtime-XXXXXX)
export HOME=/root
echo "== $LABEL arm=$ARM probe uptime=$(cut -d' ' -f1 /proc/uptime)"
rm -rf /tmp/mesa_shader_cache /tmp/mesa_shader_cache_db
sha256sum /install/lib/libgallium*.so | sed 's/^/== /'
mkdir -p /tmp/.X11-unix
export DISPLAY=:0 WAYLAND_DISPLAY=wayland-0
weston --config=/a306/ci/weston.ini --socket="$WAYLAND_DISPLAY" --log "$RESULTS_DIR/weston.log" \
  --logger-scopes=log,xwm-wm-x11 --width 1920 --height 1080 --renderer=gl &
WESTON=$!
for _ in $(seq 60); do [ -S /tmp/.X11-unix/X0 ] && break; sleep 1; done
[ -S /tmp/.X11-unix/X0 ] || { echo "== weston/Xwayland not ready"; kill $WESTON; exit 90; }
export PIGLIT_PLATFORM=mixed_glx_egl MESA_SHADER_CACHE_DISABLE=true IR3_SHADER_DEBUG=disasm
if [ -n "$OVR" ]; then export IR3_SHADER_OVERRIDE_PATH=$OVR; echo "== override $OVR: $(ls $OVR | tr '\n' ' ')"; fi
for t in "$@"; do
  for i in $(seq $REPEAT); do
  n=$(basename "$t" .shader_test).$i
  h0=$(dmesg | grep -c 'hangcheck detected')
  echo "== test $n start uptime=$(cut -d' ' -f1 /proc/uptime) hangchecks_before=$h0"
  timeout -k 5 120 /piglit/bin/shader_runner "$t" -auto -fbo > "$RESULTS_DIR/$n.log" 2>&1
  rc=$?
  h1=$(dmesg | grep -c 'hangcheck detected')
  echo "== test $n rc=$rc hangchecks_after=$h1 result=$(grep -ao 'PIGLIT: {"result": "[a-z]*"' "$RESULTS_DIR/$n.log" | tail -1) probes_failed=$(grep -c '^Probe color' "$RESULTS_DIR/$n.log")"
  [ "$h1" != "$h0" ] && dmesg | grep -E 'hangcheck|offending|fault' | tail -6 | sed 's/^/== dmesg: /'
  done
done
echo "== probe done uptime=$(cut -d' ' -f1 /proc/uptime)"
kill $WESTON 2>/dev/null; sleep 2; kill -9 $WESTON 2>/dev/null
cd /tmp/results && tar -c "$LABEL" | zstd -q -19 -o "/tmp/results/$LABEL.tar.zst"
sha256sum "/tmp/results/$LABEL.tar.zst"
