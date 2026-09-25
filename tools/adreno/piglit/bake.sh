#!/bin/bash
# bake.sh ARM...  : copy /w/out/ARM/install into the fixture root as
# /var/opt/ci-root/install-ARM, refresh the /a306 payload (runner scripts,
# CI lists, probe tests). smoo-host must not be serving the image.
set -euo pipefail
W=/var/home/sam/tmp/a306-piglit-20260924
pgrep -x smoo-host >/dev/null && { echo "smoo-host is running; refusing to bake"; exit 1; }
M=$W/fixture/mnt
sudo mount -o loop $W/fixture/pfroot-a306.img $M
R=$M/ostree/deploy/pocketfed/var/opt/ci-root
sudo install -o 0 -g 0 -m 755 $W/payload/a306/run-suite.sh $W/payload/a306/run-traces.sh $W/payload/a306/run-probe.sh $R/a306/
sudo rm -rf $R/a306/probe && sudo cp -a $W/payload/a306/probe $R/a306/probe && sudo chown -R 0:0 $R/a306/probe
for ARM in "$@"; do
  sudo rm -rf $R/install-$ARM
  sudo cp -a $W/out/$ARM/install $R/install-$ARM
  sudo cp $W/out/$ARM.SHA256SUMS $R/install-$ARM/SHA256SUMS
  sudo chown -R 0:0 $R/install-$ARM
  sudo sha256sum $R/install-$ARM/lib/libgallium-*.so | cut -c1-16,65-
done
sudo ls $R/ | tr '\n' ' '; echo
sync; sudo umount $M
e2fsck -fn $W/fixture/pfroot-a306.img 2>&1 | tail -1
