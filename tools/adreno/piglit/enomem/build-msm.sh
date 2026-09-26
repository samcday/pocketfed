#!/bin/bash
# build-msm.sh fetch | tree | build-container TAG [PATCH] | build-cross TAG [PATCH] | check TAG
#
# Planning artefact (2026-09-26), NOT run. Rebuilds ONLY msm.ko for the stock Fedora kernel
# 7.3.0-0.rc3.260918g5dd1818b15d9.36.fc46.aarch64 (Koji build 3104311, dist-git
# 0c596f6db31dd2ceb5df21b409576c7eaba1ec70), so the DB410c liveboot can A/B the
# submit_create kzalloc -> kvzalloc change against a control build of the same sources.
#
# Verified constraints (see the lens output for evidence):
#   - Fedora's patch-7.3-redhat.patch changes struct task_struct (moves stack_canary) and
#     struct module (adds rhelversion). A module built against vanilla 5dd1818b15d9 headers
#     would be rejected (.gnu.linkonce.this_module size) or, worse, use a wrong
#     -mstack-protector-guard-offset. Headers MUST be Fedora's: kernel-devel, or the tree
#     with patch-7.3-redhat.patch applied.
#   - The Fedora patch touches nothing under drivers/gpu/drm/, so msm sources = git 5dd1818b15d9.
#   - msm includes ../../../drm_crtc_internal.h (disp/msm_disp_snapshot.h): keep the
#     drivers/gpu/drm/ layout around the msm directory.
#   - MODVERSIONS=n: only vermagic must match. MODULE_SIG=y, MODULE_SIG_FORCE=n,
#     LOCK_DOWN_KERNEL_FORCE_NONE=y: an unsigned module loads and taints (E, plus O for an
#     out-of-tree build). RANDSTRUCT_NONE, no CFI, no GCC plugins.
#   - kernel-devel ships aarch64 host tools (fixdep, modpost), so it is used natively inside
#     an arm64 container (qemu-user binfmt is registered here with flags OCF).
set -euo pipefail
V=7.3.0-0.rc3.260918g5dd1818b15d9.36.fc46
KREL=$V.aarch64
L=/var/home/sam/tmp/a306-piglit-20260924/kernel-explore/lab-plan
W=$L/kbuild
KOJI=https://kojipkgs.fedoraproject.org/packages/kernel/7.3.0/0.rc3.260918g5dd1818b15d9.36.fc46
DG=https://src.fedoraproject.org/rpms/kernel/raw/0c596f6db31dd2ceb5df21b409576c7eaba1ec70/f
LINUX=/var/home/sam/src/linux
mkdir -p $W

case ${1:-} in
fetch)   # ~55 MB download: needs Sam's OK at run time
  cd $W
  curl -fLO $KOJI/aarch64/kernel-devel-$KREL.rpm          # 55 316 225 bytes
  rpm -K kernel-devel-$KREL.rpm || true                   # signed with 91211fce
  mkdir -p kdev && rpm2cpio kernel-devel-$KREL.rpm | (cd kdev && cpio -idm --quiet)
  K=$W/kdev/usr/src/kernels/$KREL
  cat $K/include/config/kernel.release                    # must be $KREL
  grep -E '^(# )?CONFIG_(MODULE_SIG_FORCE|MODULE_SIG|MODVERSIONS|DRM_MSM|STACKPROTECTOR_PER_TASK|RANDSTRUCT_NONE|LOCK_DOWN_KERNEL_FORCE_NONE)[= ]' $K/.config
  ls $K/vmlinux 2>/dev/null || echo "no vmlinux in kernel-devel: module BTF will be skipped (harmless)"
  ;;
tree)    # msm sources at the Fedora snapshot, laid out as drivers/gpu/drm/{msm,drm_crtc_internal.h}
  rm -rf $W/src && mkdir -p $W/src
  git -C $LINUX archive 5dd1818b15d9 drivers/gpu/drm/msm drivers/gpu/drm/drm_crtc_internal.h | tar -x -C $W/src
  ;;
build-container)   # TAG = ctl | kvz ; PATCH optional (e.g. $L/lab-kvzalloc.diff)
  TAG=$2; P=${3:-}
  rm -rf $W/b-$TAG && cp -a $W/src $W/b-$TAG
  [ -n "$P" ] && patch -d $W/b-$TAG -p1 < "$P"
  # lab-only marker, readable on the board as /sys/module/msm/version
  echo "MODULE_VERSION(\"lab-$TAG\");" >> $W/b-$TAG/drivers/gpu/drm/msm/msm_drv.c
  podman run --rm --arch arm64 -v $W:/w:z registry.fedoraproject.org/fedora:rawhide bash -euxc "
    dnf -y -q install /w/kernel-devel-$KREL.rpm gcc make python3 xz
    gcc --version | head -1
    # trace headers use TRACE_INCLUDE_PATH ../../drivers/gpu/drm/msm, resolved from
    # <kdir>/include/trace, so the msm dir must appear inside the (container-local) kdir
    mkdir -p /usr/src/kernels/$KREL/drivers/gpu/drm
    rm -rf /usr/src/kernels/$KREL/drivers/gpu/drm/msm   # kernel-devel ships a stub dir (Kconfig/Makefile)
    ln -s /w/b-$TAG/drivers/gpu/drm/msm /usr/src/kernels/$KREL/drivers/gpu/drm/msm
    make -C /usr/src/kernels/$KREL M=/w/b-$TAG/drivers/gpu/drm/msm -j\$(nproc) modules
  "
  cp $W/b-$TAG/drivers/gpu/drm/msm/msm.ko $W/msm-$TAG.ko
  ;;
build-cross)       # faster fallback: x86 cross gcc 16.2.1 on a full Fedora-patched tree
  TAG=$2; P=${3:-}
  T=$W/full-$TAG; rm -rf $T && mkdir -p $T
  git -C $LINUX archive 5dd1818b15d9 | tar -x -C $T
  curl -fL -o $W/Makefile.rhelver $DG/Makefile.rhelver     # the patched Makefile includes it
  cp $W/Makefile.rhelver $T/
  patch -d $T -p1 < $L/patch-7.3-redhat.patch.txt           # sha256 7a955816...
  [ -n "$P" ] && patch -d $T -p1 < "$P"
  echo "MODULE_VERSION(\"lab-$TAG\");" >> $T/drivers/gpu/drm/msm/msm_drv.c
  cp $W/kdev/usr/src/kernels/$KREL/.config $T/.config
  M="make -C $T ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- KERNELRELEASE=$KREL PYTHON3=/usr/bin/python3 -j32"
  $M olddefconfig
  diff <(grep '^CONFIG_' $W/kdev/usr/src/kernels/$KREL/.config | grep -vE 'CC_VERSION_TEXT|GCC_VERSION|AS_VERSION|LD_VERSION|PAHOLE_VERSION|CC_IS_|LD_IS_|AS_IS_' | sort) \
       <(grep '^CONFIG_' $T/.config | grep -vE 'CC_VERSION_TEXT|GCC_VERSION|AS_VERSION|LD_VERSION|PAHOLE_VERSION|CC_IS_|LD_IS_|AS_IS_' | sort) \
    && echo "config matches kernel-devel"
  $M modules_prepare
  diff $T/include/generated/asm-offsets.h $W/kdev/usr/src/kernels/$KREL/include/generated/asm-offsets.h \
    && echo "asm-offsets identical (task_struct/stack canary layout matches Fedora)"
  $M KBUILD_EXTRA_SYMBOLS=$W/kdev/usr/src/kernels/$KREL/Module.symvers M=drivers/gpu/drm/msm modules
  cp $T/drivers/gpu/drm/msm/msm.ko $W/msm-$TAG.ko
  ;;
check)   # gates, run on the host before anything goes near the board
  TAG=$2; K=$W/msm-$TAG.ko; F=$L/msm.ko                     # F = Fedora's, from the initrd
  modinfo -F vermagic $K                                       # == "$KREL SMP preempt mod_unload aarch64"
  modinfo -F version $K                                        # == lab-$TAG
  for m in $F $K; do readelf -SW $m | awk '/gnu.linkonce.this_module/{print "this_module size", $6}'; done   # must be equal
  d() { aarch64-linux-gnu-objdump -d --no-show-raw-insn --disassemble="$2" "$1" | sed -n '/>:$/,$p' | sed -E 's/^ *[0-9a-f]+:\t//; s/[0-9a-f]+ <[^>]*>//'; }
  diff <(d $F submit_create) <(d $K submit_create) && echo "submit_create identical to Fedora's" || true
  diff <(d $F msm_ioctl_gem_submit) <(d $K msm_ioctl_gem_submit) >/dev/null && echo "msm_ioctl_gem_submit identical" || echo "msm_ioctl_gem_submit differs (inspect)"
  # stack-canary offset used by the module must equal Fedora's: Fedora's msm.ko loads the
  # canary as [sp_el0 + #88] (81 sites, e.g. msm_mm_show); the Fedora patch moves
  # task_struct.stack_canary up next to wake_entry, so a vanilla-header build shows a far
  # larger offset. Also: grep TSK_STACK_CANARY kdev/.../include/generated/asm-offsets.h -> 88
  for m in $F $K; do aarch64-linux-gnu-objdump -d $m | grep -A1 'mrs.*sp_el0' | grep -oE 'ldr\s+x[0-9]+, \[x[0-9]+, #[0-9]+\]' | awk '{print $NF}' | sort | uniq -c | sort -rn | head -3; echo --; done
  ;;
*) echo "usage: $0 fetch | tree | build-container TAG [PATCH] | build-cross TAG [PATCH] | check TAG"; exit 2 ;;
esac
