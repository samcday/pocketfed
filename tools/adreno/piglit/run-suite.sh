#!/bin/bash
# Runs inside the Mesa CI arm64 test-gl chroot on the DB410c.
# Mirrors .gitlab-ci/common/init-stage2.sh + weston.sh + deqp-runner.sh for
# the a306 piglit jobs (HWCI_START_WESTON=1).
#
# usage: run-suite.sh ARM SUITE JOBS SKIPS LABEL [extra deqp-runner args...]
#   ARM    main | mr            (/install-$ARM becomes /install)
#   SUITE  a306-piglit | a306-piglit-quick-gl | a306-piglit-quick-shader
#   JOBS   --jobs value (CI: 8 / 3 / 6)
#   SKIPS  ci (MR-branch skips) | nohang (Hangchecks block removed) |
#          candidate (proposed expectation change)
#   optional first extra arg frac=K/N splits the suite like CI_NODE_INDEX/TOTAL
#   LABEL  results go to /tmp/results/LABEL
set -u
ARM=$1 SUITE=$2 JOBS=$3 SKIPS=$4 LABEL=$5
shift 5
C=/a306/ci
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

echo "== $LABEL arm=$ARM suite=$SUITE jobs=$JOBS skips=$SKIPS uptime=$(cut -d' ' -f1 /proc/uptime)"
# CI starts every job with an empty tmpfs shader cache; keep runs independent.
rm -rf /tmp/mesa_shader_cache /tmp/mesa_shader_cache_db
echo "== mem $(free -m | awk '/^Mem:/{print "used="$3" avail="$7} /^Swap:/{print "swap_used="$3}' | tr '\n' ' ')"
echo "== num_hw_submissions=$(cat /sys/module/msm/parameters/num_hw_submissions 2>/dev/null)"
sha256sum /install/lib/libgallium*.so | sed 's/^/== /'

# weston.sh (weston is started before deqp-runner.sh exports EGL_PLATFORM)
mkdir -p /tmp/.X11-unix
export DISPLAY=:0
export WAYLAND_DISPLAY=wayland-0
weston --config="$C/weston.ini" --socket="$WAYLAND_DISPLAY" \
  --log "$RESULTS_DIR/weston.log" --logger-scopes=log,xwm-wm-x11 \
  --width 1920 --height 1080 --renderer=gl &
WESTON=$!
for _ in $(seq 60); do [ -S /tmp/.X11-unix/X0 ] && break; sleep 1; done
[ -S /tmp/.X11-unix/X0 ] || { echo "== weston/Xwayland not ready"; kill $WESTON; exit 90; }
echo "== weston pid $WESTON ready uptime=$(cut -d' ' -f1 /proc/uptime)"
grep -iE "GL renderer|GL version" "$RESULTS_DIR/weston.log" | head -2 | sed "s/^/== weston: /"
wflinfo --platform glx --api gl 2>&1 | grep -E "renderer|version string" | sed "s/^/== glx: /"

# deqp-runner.sh
export EGL_PLATFORM=surfaceless
rm -f /tmp/fails.txt; touch /tmp/fails.txt
cat "$C/freedreno-a306-fails.txt" >> /tmp/fails.txt
case $SKIPS in
  ci) SK="$C/freedreno-a306-skips.txt" ;;
  nohang) SK="$C/freedreno-a306-skips-nohang.txt" ;;
  candidate) SK="$C/freedreno-a306-skips-candidate.txt" ;;
  *) echo "bad SKIPS"; exit 91 ;;
esac
FRAC=(--fraction-start 1 --fraction 1)
if [[ "${1:-}" =~ ^frac=([0-9]+)/([0-9]+)$ ]]; then
  FRAC=(--fraction-start "${BASH_REMATCH[1]}" --fraction "${BASH_REMATCH[2]}"); shift
fi
echo "== fraction ${FRAC[*]} skips-file $(sha256sum "$SK")"
set -x
deqp-runner suite \
  --suite "$C/deqp-freedreno-$SUITE.toml" \
  --output "$RESULTS_DIR" \
  --baseline /tmp/fails.txt \
  --flakes "$C/all-flakes.txt" --flakes "$C/freedreno-a306-flakes.txt" \
  --skips "$C/all-skips.txt" --skips "$SK" --skips "$C/all-slow-skips.txt" \
  --single-thread "$C/all-single-thread.txt" \
  --testlog-to-xml /deqp-tools/testlog-to-xml \
  "${FRAC[@]}" \
  --jobs "$JOBS" --timestamp ms "$@"
RC=$?
set +x
echo "== deqp-runner rc=$RC uptime=$(cut -d' ' -f1 /proc/uptime)"
kill $WESTON 2>/dev/null; sleep 2; kill -9 $WESTON 2>/dev/null
cd /tmp/results && tar --exclude='*.xml' --exclude='c*.r*.log' --exclude='c*.r*.caselist.txt' -c "$LABEL" | zstd -q -19 -o "/tmp/results/$LABEL.tar.zst"
sha256sum "/tmp/results/$LABEL.tar.zst"
exit $RC
