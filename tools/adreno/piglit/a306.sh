# /opt/a306/a306.sh - source from the liveboot serial root shell.
# Sets up the Mesa CI test-gl chroot at /opt/ci-root and helpers.
R=/opt/ci-root
a306_mounts() {
  mountpoint -q /sys/kernel/debug || mount -t debugfs none /sys/kernel/debug
  mountpoint -q $R/proc || mount -t proc proc $R/proc
  mountpoint -q $R/sys || mount --rbind /sys $R/sys
  mountpoint -q $R/dev || mount --rbind /dev $R/dev
  mountpoint -q $R/tmp || mount -t tmpfs tmpfs $R/tmp
  mkdir -p $R/tmp/results
}
# a306_run <script> <args...>: run a chroot script in the foreground so its
# output also reaches the serial console (survives a SoC reset).
a306_run() { a306_mounts; chroot $R /usr/bin/env -i TERM=dumb PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin "/a306/$1" "${@:2}"; }
# snapshot of GPU/kernel state, safe to call between runs
a306_state() {
  echo "uptime $(cut -d' ' -f1 /proc/uptime) boot_id $(cat /proc/sys/kernel/random/boot_id)"
  echo "num_hw_submissions=$(cat /sys/module/msm/parameters/num_hw_submissions)"
  free -m | sed -n 2,3p
  dmesg | grep -ciE 'hangcheck|gpu fault|iommu fault|smmu|recover' | sed 's/^/gpu-error-lines /'
}
a306_gpu_log() { dmesg | grep -iE 'hangcheck|offending|gpu fault|iommu|smmu|recover|msm_gpu|adreno|devcoredump|timeout' | tail -${1:-40}; }
