# /opt/adreno-b14/b14-trials.sh (v3) - source from the liveboot root shell.
# pocketfed#80 B14+: boundary knobs, candidate fixes, GTK/Settings and STK.
# Full per-run logs stay in /run/adreno-b14; only summaries go to UART.
# Kernel events are counted by timestamp (the dmesg ring buffer wraps).
. /opt/adreno/env.sh
B14=/opt/adreno-b14
R=/run/adreno-b14
mkdir -p $R
GPU=/sys/bus/platform/devices/1c00000.gpu
MIN=/opt/adreno-rob/a306-minimal-pair.trace
FULL=/opt/adreno/r3.trace

libdir() {
  case $1 in
    b14|b14c|fixL|fixI|fixF) echo $B14/$1 ;;
    patchA) echo /opt/adreno/mesa-patchA ;;
    b2) echo /opt/adreno-rob/direct-wait ;;
    *) echo /opt/adreno-rob/$1 ;;
  esac
}

# kernel log lines newer than uptime $1
newk() {
  dmesg | awk -v t=$1 '{s=$0; sub(/^\[ */,"",s); split(s,a,"]"); if (a[1]+0 > t) print}'
}
kevents() {
  echo "hangchecks=$(newk $1 | grep -c 'hangcheck detected')" \
       "iova_faults=$(newk $1 | grep -c 'fault: iova')" \
       "oom=$(newk $1 | grep -c -i 'out of memory')"
  newk $1 | grep -i -E 'hangcheck detected|completed fence|submitted fence|offending|out of memory' | cut -c1-150 | head -8
}

brief() {
  echo "boot=$(cat /proc/sys/kernel/random/boot_id) up=$(cut -d' ' -f1 /proc/uptime)" \
       "pm=$(cat $GPU/power/control)/$(cat $GPU/power/runtime_status)" \
       "fence=$(awk '/last-fence|retired-fence/{gsub(/ /,"");printf "%s ",$0} /data:/{exit}' /sys/kernel/debug/dri/0/gpu 2>/dev/null)" \
       "phoc=$(pgrep -x phoc | head -1)" \
       "devcd=$(ls -d /sys/class/devcoredump/devcd* 2>/dev/null | wc -l)" \
       "avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)M"
}

ready() {
  pgrep -x phoc >/dev/null || systemctl restart phrog
  for i in $(seq 1 90); do
    [ -S /run/user/991/wayland-0 ] && [ -S /tmp/.X11-unix/X0 ] && pgrep -x phoc >/dev/null && break
    sleep 1
  done
  sleep 4
  greetrun gdbus call --session --dest org.gnome.ScreenSaver --object-path /org/gnome/ScreenSaver \
    --method org.gnome.ScreenSaver.SetActive false >/dev/null 2>&1
  sleep 2
  echo "ready crtc: $(awk '/^crtc\[/{c=1} c&&/enable=|active=/{printf "%s ",$1} /^plane/{c=0}' /sys/kernel/debug/dri/0/state) phoc=$(pgrep -x phoc)"
}

devcd_save() {
  local tag=$1 d n=0
  for d in /sys/class/devcoredump/devcd*; do
    [ -e "$d/data" ] || continue
    n=$((n + 1))
    cat "$d/data" > $R/$tag.devcore$n
    sha256sum $R/$tag.devcore$n
    echo 1 > "$d/data"
  done
  echo "devcd_saved=$n"
}

watch_loaded() {
  local tag=$1 name=$2 launcher=$3 i child
  for i in $(seq 1 600); do
    child=$(pgrep -u greetd -x "$name" | head -n1)
    if [ -n "$child" ] && grep -q libgallium /proc/$child/maps 2>/dev/null; then
      echo "LOADED $tag pid=$child $(grep -m1 -o '/[^ ]*libgallium[^ ]*' /proc/$child/maps)"
      tr '\0' '\n' < /proc/$child/environ | grep -E '^(LD_LIBRARY_PATH|MESA_|FD_|FD3_|IR3_)' | tr '\n' ' '
      echo
      return 0
    fi
    kill -0 "$launcher" 2>/dev/null || break
    sleep 0.1
  done
  echo "LOADED $tag NOT-CAPTURED"
}

SESSION_ENV="HOME=/var/lib/greetd XDG_RUNTIME_DIR=/run/user/991 WAYLAND_DISPLAY=wayland-0 DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/991/bus XDG_CURRENT_DESKTOP=GNOME"
CLEAN="-u LD_PRELOAD -u IR3_SHADER_DEBUG -u LIBGL_ALWAYS_SOFTWARE -u FD3_FS_NO_PUSH_UBO -u FD3_FS_CONST_DIRECT -u FD3_B14 -u FD_MESA_DEBUG"

# trial <tag> <arm> <mode|-> <trace> [pixels|-] [KEY=VAL ...] [-- retrace args]
trial() {
  local tag=$1 arm=$2 mode=$3 trace=$4 px=${5:--} lib rc=0 launcher t0 t1
  shift 5 2>/dev/null || shift $#
  local -a envs=() args=()
  while [ $# -gt 0 ]; do
    [ "$1" = -- ] && { shift; args=("$@"); break; }
    envs+=("$1"); shift
  done
  lib=$(libdir $arm)
  [ "$mode" = - ] && mode=
  if [ "$px" = pixels ]; then
    greetrun mkdir -p /run/user/991/b14
    args+=(--call-nos -s /run/user/991/b14/$tag-)
  fi
  echo "=== TRIAL $tag arm=$arm mode=${mode:-default} trace=$(basename $trace) env=${envs[*]} args=${args[*]}"
  echo "lib $(sha256sum $lib/libgallium-26.2.2.so | cut -c1-16)"
  echo "before $(brief)"
  t0=$(cut -d' ' -f1 /proc/uptime)
  timeout -k 5s ${TRIAL_TIMEOUT:-45}s runuser -u greetd -- env $CLEAN $SESSION_ENV \
    DISPLAY=:0 LD_LIBRARY_PATH=$lib MESA_SHADER_CACHE_DISABLE=true FD_MESA_DEBUG=$mode "${envs[@]}" \
    /opt/adreno/at/usr/bin/eglretrace "${args[@]}" "$trace" > $R/$tag.retrace 2>&1 &
  launcher=$!
  watch_loaded $tag eglretrace $launcher
  wait $launcher || rc=$?
  t1=$(cut -d' ' -f1 /proc/uptime)
  sleep 3
  echo "RESULT $tag exit=$rc launch=$t0 end=$t1"
  grep -h -E 'FD3B14|Rendered|error|Error|cannot|Cannot' $R/$tag.retrace | head -6
  kevents $t0
  [ "$px" = pixels ] && sha256sum /run/user/991/b14/$tag-*.png 2>/dev/null
  echo "after $(brief)"
  echo "=== END $tag"
}

# stk <tag> <arm> <mode|-> [KEY=VAL ...]: supertuxkart benchmark, fresh HOME,
# A5-derived seed config (internet and sound off), A5 texture cache.
stk() {
  local tag=$1 arm=$2 mode=$3 lib rc=0 launcher t0 t1 home
  shift 3
  lib=$(libdir $arm)
  [ "$mode" = - ] && mode=
  home=/run/stk-home-$tag
  rm -rf $home
  mkdir -p $home/.config/supertuxkart/config-0.10
  cp $B14/stk-seed/*.xml $home/.config/supertuxkart/config-0.10/
  chown -R greetd: $home
  echo "=== STK $tag arm=$arm mode=${mode:-default} env=$* args=${STK_ARGS:-}"
  echo "lib $(sha256sum $lib/libgallium-26.2.2.so | cut -c1-16)"
  echo "before $(brief)"
  t0=$(cut -d' ' -f1 /proc/uptime)
  timeout -k 10s ${STK_TIMEOUT:-900}s runuser -u greetd -- env $CLEAN $SESSION_ENV \
    HOME=$home XDG_CACHE_HOME=$B14/stk-cache-root \
    SDL_VIDEODRIVER=x11 SDL_VIDEO_DRIVER=x11 DISPLAY=:0 \
    LD_LIBRARY_PATH=$lib:$B14/stk/root/usr/lib64 \
    SUPERTUXKART_DATADIR=$B14/stk/root/usr/share/supertuxkart \
    MESA_SHADER_CACHE_DISABLE=true FD_MESA_DEBUG=$mode "$@" \
    $B14/stk/root/usr/bin/supertuxkart --no-start-screen --benchmark --no-sound ${STK_ARGS:-} \
    > $R/$tag.stk 2>&1 &
  launcher=$!
  watch_loaded $tag supertuxkart $launcher
  wait $launcher || rc=$?
  t1=$(cut -d' ' -f1 /proc/uptime)
  sleep 3
  echo "RESULT $tag exit=$rc launch=$t0 end=$t1"
  grep -h -E 'Profiler|Frame count|renderer:|Fatal|fatal' $R/$tag.stk | head -6
  grep -h -E 'Profiler|Frame count' $home/.config/supertuxkart/config-0.10/stdout.log 2>/dev/null | head -3
  kevents $t0
  echo "after $(brief)"
  echo "=== END $tag"
}

# gtkprobe <tag> <arm>: #82 probe, animated, 12 tiles, 450 updates, GMEM
gtkprobe() {
  local tag=$1 arm=$2 lib rc=0 l t0 t1
  lib=$(libdir $arm)
  echo "=== GTKPROBE $tag arm=$arm"
  echo "lib $(sha256sum $lib/libgallium-26.2.2.so | cut -c1-16)"
  echo "before $(brief)"
  t0=$(cut -d' ' -f1 /proc/uptime)
  timeout -k 5s 400s runuser -u greetd -- env $CLEAN $SESSION_ENV GDK_BACKEND=wayland \
    GSK_RENDERER=gl GDK_DEBUG=opengl LD_LIBRARY_PATH=$lib MESA_SHADER_CACHE_DISABLE=true \
    gjs /opt/adreno/gtk-probe.js > $R/$tag.gtk 2>&1 &
  l=$!
  watch_loaded $tag gjs $l
  wait $l || rc=$?
  t1=$(cut -d' ' -f1 /proc/uptime)
  sleep 3
  echo "RESULT $tag exit=$rc launch=$t0 end=$t1"
  grep -h -E 'updates|complete' $R/$tag.gtk | tail -2
  kevents $t0
  echo "after $(brief)"
  echo "=== END $tag"
}

# settingsrun <tag> <arm>: Settings background 85 s + six panel switches, GMEM
settingsrun() {
  local tag=$1 arm=$2 lib p pid rcs="" t0
  lib=$(libdir $arm)
  echo "=== SETTINGS $tag arm=$arm"
  echo "lib $(sha256sum $lib/libgallium-26.2.2.so | cut -c1-16)"
  echo "before $(brief)"
  t0=$(cut -d' ' -f1 /proc/uptime)
  runuser -u greetd -- env $CLEAN $SESSION_ENV GDK_BACKEND=wayland GDK_DEBUG=opengl \
    LD_LIBRARY_PATH=$lib MESA_SHADER_CACHE_DISABLE=true gnome-control-center background > $R/$tag.gcc 2>&1 &
  sleep 30
  pid=$(pgrep -u greetd -x gnome-control-c | head -1)
  echo "LOADED $tag pid=$pid $(grep -m1 -o '/[^ ]*libgallium[^ ]*' /proc/$pid/maps)"
  sleep 55
  for p in display sound power network mouse about; do
    runuser -u greetd -- env $CLEAN $SESSION_ENV GDK_BACKEND=wayland LD_LIBRARY_PATH=$lib \
      gnome-control-center $p >> $R/$tag.gcc 2>&1
    rcs="$rcs $p=$?"
    sleep 6
  done
  sleep 10
  echo "panels:$rcs still=$(pgrep -u greetd -x gnome-control-c | head -1) (was $pid)"
  kill $pid 2>/dev/null
  sleep 3
  echo "RESULT $tag launch=$t0 end=$(cut -d' ' -f1 /proc/uptime)"
  grep -m2 -E 'Using OpenGL backend|Vendor' $R/$tag.gcc
  kevents $t0
  echo "after $(brief)"
  echo "=== END $tag"
}

# lighten: stop session clients the benchmarks do not need (memory)
lighten() {
  for p in phosh-first-boot phosh-osk-stevia gnome-calls evolution-addressbook-factory \
           evolution-source-registry evolution-calendar-factory gvfs-udisks2-volume-monitor gvfsd; do
    pkill -u greetd -f "$p" && echo "stopped $p"
  done
  systemctl stop ModemManager 81voltd 2>/dev/null
  echo "avail=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)M"
}
echo "b14-trials v3 loaded: $(sha256sum $B14/b14-trials.sh | cut -c1-16)"
