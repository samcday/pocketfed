#!/usr/bin/env bash
# Bake a trial payload into a *copy* of a PocketFed OSTree root image.
#
# Liveboot serves a root image read-only over USB and gives the guest a RAM
# copy-on-write layer, so anything the guest needs must either be pushed over
# the serial console at boot (slow: ~5 kB/s) or already be inside the image.
# This script does the latter without touching the original image.
#
# The payload lands in the *stateroot* var, i.e.
#   <image>/ostree/deploy/<osname>/var/opt/<name>
# because the deployment bind-mounts that directory over its own /var and
# /opt is a symlink to /var/opt. The guest therefore sees /opt/<name>.
#
# See ./README.md for the whole fixture recipe, including the export id.
set -euo pipefail

usage() {
    cat <<'EOF'
usage: bake-payload.sh --src <root.img> --dst <copy.img> --payload <dir> [options]

  --src <root.img>     source PocketFed root image; opened read-only, never modified
  --dst <copy.img>     copy to create and modify; must not already exist
  --payload <dir>      directory whose *contents* become /opt/<name> in the guest
  --name <name>        install as /opt/<name> (default: basename of --payload)
  --keep               keep an existing --dst instead of refusing (still never
                       touches --src; use when re-baking into the same copy)
  --no-sums            do not write SHA256SUMS into the installed payload
  --dry-run            print the plan and exit

Requires root (loop mount). Refuses to run if --src is currently open by
another process, e.g. being served by smoo-host.
EOF
}

SRC= DST= PAYLOAD= NAME= KEEP=0 SUMS=1 DRY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --src) SRC=$2; shift 2 ;;
        --dst) DST=$2; shift 2 ;;
        --payload) PAYLOAD=$2; shift 2 ;;
        --name) NAME=$2; shift 2 ;;
        --keep) KEEP=1; shift ;;
        --no-sums) SUMS=0; shift ;;
        --dry-run) DRY=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
    esac
done

[ -n "$SRC" ] && [ -n "$DST" ] && [ -n "$PAYLOAD" ] || { usage >&2; exit 2; }
[ -f "$SRC" ] || { echo "no such image: $SRC" >&2; exit 1; }
[ -d "$PAYLOAD" ] || { echo "no such payload directory: $PAYLOAD" >&2; exit 1; }
[ -n "$NAME" ] || NAME=$(basename "$PAYLOAD")

SRC=$(readlink -f "$SRC")
PAYLOAD=$(readlink -f "$PAYLOAD")
DST_DIR=$(dirname "$DST")
[ -d "$DST_DIR" ] || { echo "no such directory: $DST_DIR" >&2; exit 1; }
DST=$(readlink -f "$DST_DIR")/$(basename "$DST")

[ "$SRC" != "$DST" ] || { echo "--src and --dst are the same file" >&2; exit 1; }

if [ "$DRY" = 0 ] && [ "$(id -u)" != 0 ]; then
    echo "must run as root (loop mount)" >&2
    exit 1
fi

# The source image is usually being served by smoo-host. Copying it while it is
# served is fine (read-only), but modifying it is not, and mixing the two up is
# the one mistake that costs a re-provision.
if command -v fuser >/dev/null 2>&1 && fuser -s "$SRC" 2>/dev/null; then
    echo "note: $SRC is open by another process; it will only be read" >&2
fi

echo "src      $SRC"
echo "dst      $DST"
echo "payload  $PAYLOAD -> guest /opt/$NAME"
[ "$DRY" = 0 ] || { echo "(dry run)"; exit 0; }

if [ -e "$DST" ]; then
    [ "$KEEP" = 1 ] || { echo "$DST exists (pass --keep to reuse it)" >&2; exit 1; }
    echo "reusing existing copy"
else
    # --sparse=always keeps the copy cheap on ext4/xfs; on btrfs prefer
    # `cp --reflink=auto`, which this also gets for free via coreutils.
    cp --reflink=auto --sparse=always "$SRC" "$DST"
    echo "copied $(stat -c %s "$DST") bytes"
fi

MNT=$(mktemp -d /tmp/bake-payload.XXXXXX)
cleanup() {
    if mountpoint -q "$MNT"; then umount "$MNT"; fi
    rmdir "$MNT" 2>/dev/null || true
}
trap cleanup EXIT

mount -o loop,rw "$DST" "$MNT"

shopt -s nullglob
installed=0
for var in "$MNT"/ostree/deploy/*/var; do
    [ -d "$var" ] || continue
    dest=$var/opt/$NAME
    rm -rf "$dest"
    mkdir -p "$dest"
    cp -a "$PAYLOAD"/. "$dest"/
    if [ "$SUMS" = 1 ]; then
        ( cd "$dest" && rm -f SHA256SUMS \
            && find . -type f -print0 | sort -z \
            | xargs -0 sha256sum > SHA256SUMS )
    fi
    # OSTree deployments run with SELinux labels from the commit; the trial
    # payload is unlabeled. The liveboot command line carries enforcing=0, so
    # this is only a note, not a failure mode, but relabel when we can.
    if command -v chcon >/dev/null 2>&1; then
        chcon -R -t usr_t "$dest" 2>/dev/null || true
    fi
    echo "installed into ${var#$MNT} ($(du -sh "$dest" | cut -f1))"
    installed=$((installed + 1))
done
shopt -u nullglob

sync
[ "$installed" -gt 0 ] || { echo "no ostree stateroot var found in the image" >&2; exit 1; }

df -h --output=size,used,avail,pcent "$MNT" | tail -1
echo
echo "Remember: the smoo export id is derived from the backing file's path, so"
echo "re-point smoo-host at $DST *and* rebuild the boot image with the new"
echo "--export-id before booting. See tools/adreno/README.md."
