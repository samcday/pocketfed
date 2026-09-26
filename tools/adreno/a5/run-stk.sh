#!/bin/sh
# Phone side: one SuperTuxKart benchmark with a selected libgallium arm.
# usage: run-stk.sh <label> <arm>     (library in /home/user/a3xx/<arm>/)
set -u
LABEL=$1
ARM=$2
BASE=/home/user/a3xx
LIB=$BASE/$ARM
R=$BASE/runs/$LABEL
CFG=/home/user/.config/supertuxkart/config-0.10
mkdir -p "$R"
exec >>"$R/run.log" 2>&1

BUS=$(tr '\0' '\n' < /proc/$(pgrep -x phosh | head -1)/environ | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p')
SESS=$(loginctl list-sessions --no-legend | awk '$4 == "seat0" {print $1; exit}')
say() { echo "[$(date +%H:%M:%S)] $*"; }
psm() {
	DBUS_SESSION_BUS_ADDRESS=$BUS gdbus call --session --dest org.gnome.Mutter.DisplayConfig \
		--object-path /org/gnome/Mutter/DisplayConfig --method org.freedesktop.DBus.Properties.Get \
		org.gnome.Mutter.DisplayConfig PowerSaveMode 2>/dev/null | tr -dc '0-9'
}
state() {
	b=/sys/class/power_supply/rt5033-battery
	c=/sys/class/power_supply/rt5033-charger
	echo "charger_online=$(cat $c/online) charger=$(cat $c/status) bat=$(cat $b/status)" \
		"cap=$(cat $b/capacity)% bat_mV=$(( $(cat $b/voltage_now) / 1000 ))" \
		"psm=$(psm) locked=$(loginctl show-session "$SESS" -p LockedHint --value)" \
		"gpu_MHz=$(( $(cat /sys/class/devfreq/1c00000.gpu/cur_freq) / 1000000 ))" \
		"load=$(cut -d' ' -f1 /proc/loadavg) avail_MiB=$(( $(awk '/MemAvailable/ {print $2}' /proc/meminfo) / 1024 ))"
}

say "START label=$LABEL arm=$ARM"
logger -t a3xx-run "START $LABEL $ARM"
say "host=$(hostname) model=$(tr -d '\0' < /proc/device-tree/model) kernel=$(uname -r)"
say "boot_id=$(cat /proc/sys/kernel/random/boot_id) uptime_s=$(cut -d' ' -f1 /proc/uptime)"
say "lib: $(sha256sum "$LIB/libgallium-26.2.3.so")"
say "ldd: $(LD_LIBRARY_PATH=$LIB ldd /usr/lib/libEGL.so.1 | grep libgallium)"
say "state: $(state)"
env | sort > "$R/launch-env.txt"
sync

cd /home/user
CMD="env XDG_RUNTIME_DIR=/run/user/10000 WAYLAND_DISPLAY=wayland-0 LD_LIBRARY_PATH=$LIB supertuxkart --benchmark"
$CMD > "$R/stk.out" 2>&1 &
PID=$!
T0=$(date +%s)
say "cmd: $CMD (pid $PID)"
sync

MAPPED=0
while kill -0 $PID 2>/dev/null; do
	sleep 5
	E=$(( $(date +%s) - T0 ))
	if [ $MAPPED = 0 ] && grep -q libgallium /proc/$PID/maps 2>/dev/null; then
		grep libgallium /proc/$PID/maps > "$R/maps-libgallium.txt"
		tr '\0' '\n' < /proc/$PID/environ | sort > "$R/proc-environ.txt"
		say "maps: $(awk '{print $6}' "$R/maps-libgallium.txt" | sort -u | tr '\n' ' ')"
		say "environ: $(grep -E '^(LD_LIBRARY_PATH|WAYLAND_DISPLAY|XDG_RUNTIME_DIR|IR3_|FD_|MESA_|LIBGL_|SDL_|GALLIUM_)' "$R/proc-environ.txt" | tr '\n' ' ')"
		MAPPED=1
	fi
	say "t=${E}s $(state)"
	sync
	if [ $E -gt 900 ]; then
		say "TIMEOUT after ${E}s: killing pid $PID"
		kill $PID
	fi
done
wait $PID
RC=$?
E=$(( $(date +%s) - T0 ))
say "EXIT rc=$RC elapsed=${E}s mapped_checked=$MAPPED"
cp "$CFG/stdout.log" "$CFG"/stdout.log.*.csv "$R/"
say "profiler: $(grep 'Profiler:' "$R/stdout.log")"
logread -n 0 | awk -v m="START $LABEL $ARM" 'index($0, m) {f = 1} f' > "$R/syslog-since-start.txt"
grep ' kern ' "$R/syslog-since-start.txt" > "$R/kern.log"
say "kernel lines since START: $(wc -l < "$R/kern.log")" \
	"hangcheck=$(grep -c -i hangcheck "$R/kern.log")" \
	"fault/oops=$(grep -c -i -E 'fault|oops|unable to handle|panic' "$R/kern.log")"
say "state: $(state)"
logger -t a3xx-run "END $LABEL $ARM rc=$RC"
say "DONE"
sync
