#!/usr/bin/python3
"""Install a hash-bound local package update only inside a disposable image."""
from pathlib import Path
import hashlib,json,os,subprocess

INPUT=Path('/run/fingerprint-upgrade')
REQUIRED={'libfprint','libfprint-fpc-qsee','qsee-supplicant','qsee-supplicant-sargo-rpmb','pocketfed-fpc-auth','pocketfed-fpc-selinux','fprintd','fprintd-pam','fpc-qsee-probe','phosh','libphosh','phosh-fingerprint-auth','gnome-control-center','gnome-control-center-filesystem'}
POLICY=Path('/etc/selinux/targeted')
assert Path('/run/.containerenv').exists() or Path('/.dockerenv').exists()
m=json.loads((INPUT/'manifest.json').read_text())
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for name,h in m['input_files'].items():
 p=INPUT/name
 assert not p.is_symlink() and p.is_file() and sha(p)==h, name
assert {str(p.relative_to(INPUT)) for p in INPUT.rglob('*') if p.is_file()}==set(m['input_files'])|{'manifest.json'}
assert sha(POLICY/'policy/policy.35')==m['base_policy_sha256']
assert sha(POLICY/'contexts/files/file_contexts')==m['base_contexts_sha256']

def packages(args):
 rows=subprocess.check_output(['rpm',*args,'--qf','%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n'],text=True).splitlines()
 out={}
 for row in rows:
  n,v=row.split('\t');out.setdefault(n,[]).append(v)
 return {k:sorted(v) for k,v in out.items()}

def protected():
 paths=set()
 for root in ('/etc/pam.d','/usr/lib/pam.d','/etc/authselect','/etc/phrog','/etc/dracut.conf.d','/usr/lib/modules','/usr/share/plymouth'):
  p=Path(root)
  assert p.is_dir(),root
  paths.update(x for x in p.rglob('*') if x.is_file() or x.is_symlink())
 for name in ('/usr/libexec/phosh-fingerprint-worker','/usr/libexec/phosh-fingerprint-auth','/usr/libexec/pocketfed-verify-oci'):
  p=Path(name)
  if p.exists(): paths.add(p)
 return {str(p):{'link':os.readlink(p)} if p.is_symlink() else {'sha256':sha(p)} for p in sorted(paths)}

before,keep=packages(['-qa']),protected()
assert before['ModemManager']==['0:1.25.95-1.pocketfed.fc46.aarch64']
assert before['gnome-control-center']==['0:51~rc.1-1.fc46.aarch64']
pam=Path('/etc/pam.d/phosh');pam_bytes=pam.read_bytes()
for unit in ('fprintd.service','qsee-supplicant.service','pocketfed-fpc-auth.socket','pocketfed-fpc-provision@.service','phosh-fingerprint-auth.socket'):
 p=Path('/etc/systemd/system')/unit
 assert not p.exists() and not p.is_symlink(),unit
 p.symlink_to('/dev/null')
rpms=sorted(str(p) for p in (INPUT/'rpms').glob('*.rpm'))
expected=packages(['-qp',*rpms]);assert set(expected)==REQUIRED
assert all(len(v)==1 and v[0].endswith(('.aarch64','.noarch')) for v in expected.values())
for unit in ('fprintd.service','qsee-supplicant.service','pocketfed-fpc-auth.socket','pocketfed-fpc-provision@.service','phosh-fingerprint-auth.socket'):
 assert os.readlink('/etc/systemd/system/'+unit)=='/dev/null',unit
# Hash-bound artifacts include locally built RPMs without repository signatures.
# Their exact SHA-256 values were checked above against the recorded local build outputs;
# retain RPM digest and dependency checking, without changing system policy.
subprocess.run(['rpm','-Uvh','--nosignature','--test',*rpms],check=True)
subprocess.run(['rpm','-Uvh','--nosignature',*rpms],check=True)
pam.write_bytes(pam_bytes)
after=packages(['-qa'])
assert all(after.get(n)==v for n,v in expected.items())
assert {n:v for n,v in after.items() if n not in REQUIRED}=={n:v for n,v in before.items() if n not in REQUIRED}
current=protected()
assert all(current.get(p)==v for p,v in keep.items()), 'Existing boot or authentication content changed'
assert set(current)-set(keep)<={'/usr/lib/pam.d/phosh-fingerprint','/usr/lib/pam.d/fprintd','/usr/libexec/phosh-fingerprint-auth','/usr/libexec/phosh-fingerprint-worker'}, 'Unreviewed authentication file added'
for unit in ('fprintd.service','qsee-supplicant.service','pocketfed-fpc-auth.socket','pocketfed-fpc-provision@.service','phosh-fingerprint-auth.socket'):
 assert os.readlink('/etc/systemd/system/'+unit)=='/dev/null',unit
# Rebuild only the compiled regex cache on ARM64. No policy is loaded here.
(POLICY/'policy/policy.35').write_bytes((INPUT/'policy.35').read_bytes())
(POLICY/'contexts/files/file_contexts').write_bytes((INPUT/'file_contexts').read_bytes())
subprocess.run(['sefcontext_compile',str(POLICY/'contexts/files/file_contexts')],check=True)
label=subprocess.check_output(['matchpathcon','-n','-N','/usr/bin/pocketfed-fpc-auth'],text=True).strip()
assert label=='system_u:object_r:pocketfed_fpc_auth_exec_t:s0',label
# This helper only installs payloads. Enabling the normal receiver, broker and
# desktop sockets remains a separate, guarded daily-device trial step.
assert not Path('/var/lib/pocketfed-fpc-auth').exists()
assert not Path('/var/lib/firmware-updates/.sargo-fingerprint').exists()
report={'base_image':m['base_image_id'],'input_manifest_sha256':sha(INPUT/'manifest.json'),'updated_packages':expected,'unrelated_packages_unchanged':True,'protected_file_count':len(keep),'protected_files':keep,'policy_sha256':sha(POLICY/'policy/policy.35'),'file_contexts_sha256':sha(POLICY/'contexts/files/file_contexts'),'file_contexts_bin_sha256':sha(POLICY/'contexts/files/file_contexts.bin'),'broker_executable_label':label,'services_activated':False}
out=Path('/usr/share/pocketfed/fingerprint-trial/daily-upgrade.json');out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(report,indent=2)+'\n')
print('PASS: fourteen exact fingerprint package updates; unrelated packages, boot files and existing PIN policies unchanged; broker policy lookup passed; services remain masked')
