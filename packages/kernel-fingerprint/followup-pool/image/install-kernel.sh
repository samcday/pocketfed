#!/bin/bash
# Run only inside the disposable candidate-image build, never on the phone.
set -euo pipefail
test -e /run/.containerenv || test -e /.dockerenv
inputs=/run/fingerprint-kernel
kver=7.1.2-0.pocketfed.sdm670.12.fc46.aarch64
new=/usr/lib/modules/$kver
set -- /usr/lib/modules/*
test "$#" -eq 1 && test -d "$1"
old=$1
case "${old##*/}" in
    7.1.2-0.pocketfed.sdm670.11.fc46.aarch64) ;;
    *) echo 'Unexpected base kernel; reconcile the trial baseline first' >&2; exit 1 ;;
esac
test -z "$(find /boot -mindepth 1 -maxdepth 1 -print -quit)"
(cd "$inputs" && sha256sum -c SHA256SUMS)
save=$(mktemp -d /tmp/pocketfed-fingerprint-base.XXXXXX)
cp "$old/aboot.img" "$save/aboot.img"
cp "$old/dtb/qcom/sdm670-google-sargo.dtb" "$save/old.dtb"
rpm -qa --qf '%{NAME}\t%{VERSION}-%{RELEASE}.%{ARCH}\n' > "$save/packages.tsv"
mapfile -t names < <(rpm -qa --qf '%{NAME}\n' |
    grep -E '^kernel(-core|-modules|-modules-core|-modules-extra|-modules-internal|-modules-extra-matched)?$')
test "${#names[@]}" -ge 4
rpms=()
for name in "${names[@]}"; do
    file="$inputs/$name-$kver.rpm"
    test -f "$file"
    rpms+=("$file")
done
# Verify signatures with the inherited COPR key before the transaction.
rpm -K "${rpms[@]}"
rpm -Uvh --test "${rpms[@]}"
rpm -Uvh "${rpms[@]}"
test -d "$new"
rm -rf -- "$old"
find /boot -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +

# Keep all the inherited verifier's checks and update its one release token.
python3 - <<'PY'
from pathlib import Path
import re
p=Path('/usr/libexec/pocketfed-verify-kernel');s=p.read_text()
s,n=re.subn(r'7\.1\.2-0\.pocketfed\.sdm670\.11\.',
            '7.1.2-0.pocketfed.sdm670.12.',s)
assert n == 1, n
p.write_text(s)
PY
/usr/libexec/pocketfed-verify-kernel
for module in fpc1020 qseecomtee; do
    test "$(modinfo -k "$kver" -F vermagic "$module" | cut -d' ' -f1)" = "$kver"
done
# dtc supplies fdtget. It may be placed in a temporary build-only stage.
# This release changes only QSEECOM allocation; preserve the exact device tree.
cmp -s "$save/old.dtb" "$new/dtb/qcom/sdm670-google-sargo.dtb"
python3 /tmp/replace-template-dtb.py "$save/aboot.img" \
    "$new/dtb/qcom/sdm670-google-sargo.dtb" "$new/aboot.img"
dracut --force --hostonly --hostonly-mode=strict --no-hostonly-cmdline \
    --no-hostonly-default-device "$new/initramfs.img" "$kver"
/usr/libexec/pocketfed-aboot-finalize \
    --options 'root=LABEL=pfroot rw rootwait rootfstype=ext4 ostree=true' \
    --append-options-file /usr/lib/ostree-boot/aboot-kargs \
    "$new/aboot.img" "$save/final.img"
install -m0644 "$save/final.img" "$new/aboot.img"

python3 - "$save/packages.tsv" <<'PY'
import pathlib,subprocess,sys
def parse(t): return dict(line.split('\t',1) for line in t.splitlines())
before=parse(pathlib.Path(sys.argv[1]).read_text())
after=parse(subprocess.check_output(['rpm','-qa','--qf',
      '%{NAME}\t%{VERSION}-%{RELEASE}.%{ARCH}\n'],text=True))
allowed={'kernel','kernel-core','kernel-modules','kernel-modules-core',
         'kernel-modules-extra','kernel-modules-internal','kernel-modules-extra-matched'}
assert {n:v for n,v in before.items() if n not in allowed} == {n:v for n,v in after.items() if n not in allowed}, "Unrelated package set changed"
PY
rm -rf -- "$save"
