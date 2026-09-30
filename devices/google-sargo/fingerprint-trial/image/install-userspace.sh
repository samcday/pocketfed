#!/bin/bash
# Only run in the disposable image build. All inputs are reviewed signed RPMs.
set -euo pipefail
test -e /run/.containerenv || test -e /.dockerenv
inputs=/run/fingerprint-userspace
test -d /usr/lib/modules/7.1.2-0.pocketfed.sdm670.11.fc46.aarch64
python3 /tmp/validate-fingerprint-inputs.py "$inputs"
save=$(mktemp -d /tmp/fingerprint-userspace.XXXXXX)
trap 'rm -rf -- "$save"' EXIT
rpm -qa --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' > "$save/before.tsv"
# The working policy routes through Fedora system-auth, including homed.
# Retain the proven base policy even if an incoming package changes defaults.
test -f /etc/pam.d/phosh && test ! -L /etc/pam.d/phosh
cp -a /etc/pam.d/phosh "$save/phosh.pam"

# Install-time scriptlets cannot activate the fingerprint path. The masks also
# survive into the first boot and gate systemd's fprintd D-Bus activation.
install -d -m0755 /etc/systemd/system
masks=(fprintd.service phosh-fingerprint-auth.socket qsee-supplicant.service
       pocketfed-fpc-auth.socket pocketfed-fpc-provision@.service)
for unit in "${masks[@]}"; do
    test ! -e "/etc/systemd/system/$unit" && test ! -L "/etc/systemd/system/$unit"
    ln -s /dev/null "/etc/systemd/system/$unit"
done

rpms=("$inputs"/*.rpm)
test -f "${rpms[0]}"
rpm -qp --qf '%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n' "${rpms[@]}" > "$save/inputs.tsv"
python3 - "$save/inputs.tsv" <<'PY'
import pathlib,sys
rows=[line.split('\t') for line in pathlib.Path(sys.argv[1]).read_text().splitlines()]
names=[r[0] for r in rows]
assert len(names)==len(set(names)), 'duplicate input package name'
required={'libfprint','libfprint-fpc-qsee','fprintd','fprintd-pam','fpc-qsee-probe',
          'qsee-supplicant','phosh','libphosh','phosh-fingerprint-auth',
          'gnome-control-center','gnome-control-center-filesystem','tailscale',
          'feedbackd-device-themes','lpa-gtk','python3-cairo','python3-gobject',
          'python3-gobject-base','pocketfed-fpc-auth','pocketfed-fpc-selinux'}
assert required == set(names), 'runtime package set differs: '+str(required ^ set(names))
assert all(v.endswith(('.aarch64','.noarch')) for _,v in rows), 'non-runtime architecture'
assert not any('debug' in n or n.endswith(('-devel','-tests')) for n in names), 'non-runtime RPM'
PY

# Offline transaction: fail on missing dependencies instead of upgrading the
# working base through a repository. No removals or forced dependency changes.
rpm -Uvh --test "${rpms[@]}"
rpm -Uvh "${rpms[@]}"
cp -a "$save/phosh.pam" /etc/pam.d/phosh
cmp "$save/phosh.pam" /etc/pam.d/phosh
python3 - "$save/before.tsv" "$save/inputs.tsv" <<'PY'
import pathlib,subprocess,sys
def parse(text):
    rows=[line.split('\t',1) for line in text.splitlines()]
    result={}
    for name,version in rows:
        result.setdefault(name,[]).append(version)
    return {name:sorted(versions) for name,versions in result.items()}
before=parse(pathlib.Path(sys.argv[1]).read_text())
inputs=parse(pathlib.Path(sys.argv[2]).read_text())
after=parse(subprocess.check_output(['rpm','-qa','--qf','%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n'],text=True))
assert all(after.get(n)==v for n,v in inputs.items()), 'input version not installed exactly'
unexpected={n:(v,after.get(n)) for n,v in before.items() if n not in inputs and after.get(n)!=v}
assert not unexpected, unexpected
assert set(after)-set(before) <= set(inputs), 'unreviewed package added'
PY

test "$(readlink /etc/systemd/system/fprintd.service)" = /dev/null
test "$(readlink /etc/systemd/system/phosh-fingerprint-auth.socket)" = /dev/null
test "$(readlink /etc/systemd/system/qsee-supplicant.service)" = /dev/null
test ! -e /etc/systemd/system/sockets.target.wants/phosh-fingerprint-auth.socket
test ! -e /etc/systemd/system/sockets.target.wants/pocketfed-fpc-auth.socket
for unit in "${masks[@]}"; do
    test "$(readlink "/etc/systemd/system/$unit")" = /dev/null
done
test -f /usr/lib/systemd/system/pocketfed-fpc-auth.service
test -f /usr/lib/systemd/system/pocketfed-fpc-provision@.service
test -x /usr/bin/pocketfed-fpc-auth
test ! -e /run/pocketfed-fpc-auth
test ! -e /var/lib/pocketfed-fpc-auth
test ! -e /var/lib/firmware-updates/.sargo-fingerprint
test -x /usr/bin/debugfs
test -x /usr/bin/fpc-qsee-probe
python3 /tmp/install-fingerprint-policy.py /run/fingerprint-policy
/usr/libexec/pocketfed-verify-oci
bootc container lint
