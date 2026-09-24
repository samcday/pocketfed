#!/bin/bash
# Runs inside the CI test-gl chroot. Mirrors .gitlab-ci/piglit/piglit-traces.sh
# for a306-traces (HWCI_START_WESTON=1, no PIGLIT_PLATFORM), one trace at a time.
# usage: run-traces.sh ARM LABEL [piglit test-name regex]
set -u
ARM=$1 LABEL=$2 FILTER=${3:-}
C=/a306/ci
RESULTS_DIR=/tmp/results/$LABEL
mkdir -p "$RESULTS_DIR"
exec > >(tee -a "$RESULTS_DIR/runner.log") 2>&1
ln -sfn "/install-$ARM" /install
export LD_LIBRARY_PATH=/install/lib:/usr/local/lib
export LIBGL_DRIVERS_PATH=/install/lib/dri
export PATH=/apitrace/build:/usr/local/bin:$PATH
export XDG_CACHE_HOME=/tmp
export XDG_RUNTIME_DIR=$(mktemp --tmpdir -d xdg-runtime-XXXXXX)
export HOME=/root PAGER=cat
echo "== $LABEL arm=$ARM filter=$FILTER uptime=$(cut -d' ' -f1 /proc/uptime)"
rm -rf /tmp/mesa_shader_cache /tmp/mesa_shader_cache_db
sha256sum /install/lib/libgallium*.so | sed 's/^/== /'
mkdir -p /tmp/.X11-unix
export DISPLAY=:0 WAYLAND_DISPLAY=wayland-0
weston --config="$C/weston.ini" --socket="$WAYLAND_DISPLAY" \
  --log "$RESULTS_DIR/weston.log" --logger-scopes=log,xwm-wm-x11 \
  --width 1920 --height 1080 --renderer=gl &
WESTON=$!
for _ in $(seq 60); do [ -S /tmp/.X11-unix/X0 ] && break; sleep 1; done
[ -S /tmp/.X11-unix/X0 ] || { echo "== weston/Xwayland not ready"; exit 90; }
export PIGLIT_REPLAY_DESCRIPTION_FILE=$C/traces-a306-soak.yml
export PIGLIT_REPLAY_DEVICE_NAME=freedreno-a306
export PIGLIT_REPLAY_EXTRA_ARGS="--keep-image --db-path /a306/traces-db"
wflinfo --platform glx --api gl | grep -E 'renderer|version string'
cd /piglit
set -x
./piglit run -l verbose --timeout 300 -j1 ${FILTER:+-t "$FILTER"} replay "$RESULTS_DIR"
RC=$?
set +x
./piglit summary console "$RESULTS_DIR" | tail -20
echo "== piglit rc=$RC uptime=$(cut -d' ' -f1 /proc/uptime)"
kill $WESTON 2>/dev/null; sleep 2; kill -9 $WESTON 2>/dev/null
cd /tmp/results && tar -c "$LABEL" | zstd -q -19 -o "/tmp/results/$LABEL.tar.zst"
sha256sum "/tmp/results/$LABEL.tar.zst"
exit $RC
