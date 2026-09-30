#!/usr/bin/python3
"""Read the exact daily deployment and preserve staging comparison metadata."""
import hashlib,json,os,subprocess
from pathlib import Path
out=lambda *args:subprocess.check_output(args,text=True).strip()
assert [x for x in Path('/proc/cmdline').read_text().split() if x.startswith('androidboot.serialno=')]==['androidboot.serialno=994AY18RSD']
s=json.loads(out('rpm-ostree','status','--json'))
assert s['transaction'] is None and not any(d.get('staged') for d in s['deployments'])
d=next(d for d in s['deployments'] if d['booted'])
assert d['checksum']=='d639fe55e1cf11b2756f367fef1dad99ab7e2705c19b0b72f73e80c265d16b89'
assert out('getenforce')=='Enforcing'
r={'baseline_checksum':d['checksum'],'baseline_container_digest':d['container-image-reference-digest'],
   'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
   'slot':out('qbootctl','-x'),'pins':[v['checksum'] for v in s['deployments'] if v.get('pinned')],
   'request_fields':{k:v for k,v in d.items() if k.startswith('requested-') or k in ('regenerate-initramfs','initramfs-args','initramfs-etc')},
   'pam_sha256':hashlib.sha256(Path('/etc/pam.d/phosh').read_bytes()).hexdigest(),
   'policy_sha256':hashlib.sha256(Path('/etc/selinux/targeted/policy/policy.35').read_bytes()).hexdigest(),
   'live_packages':sorted(out('rpm','-qa','--qf','%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n').splitlines()),
   'var_available_bytes':os.statvfs('/var').f_bavail*os.statvfs('/var').f_frsize}
assert os.uname().release=='7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
assert r['pam_sha256']=='695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
units=('fprintd.service','phosh-fingerprint-auth.socket','qsee-supplicant.service',
       'pocketfed-fpc-auth.socket','pocketfed-fpc-auth.service','pocketfed-keymaster-startup.service',
       'qsee-app-loader@fpctzappfingerprint.service','qsee-shared-loader@cmnlib64.service')
r['units']={u:out('systemctl','show',u,'-p','ActiveState','-p','LoadState','-p','FragmentPath','-p','DropInPaths') for u in units}
r['local_unit_files']={}
for prefix in ('/etc/systemd/system','/run/systemd/system'):
 for p in Path(prefix).rglob('*'):
  if any(t in str(p) for t in ('fingerprint','fprint','fpc','qsee','keymaster')):
   if p.is_symlink():r['local_unit_files'][str(p)]={'symlink':os.readlink(p)}
   elif p.is_file():r['local_unit_files'][str(p)]={'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'text':p.read_text()}
r['command_line']=Path('/proc/cmdline').read_text().strip()
r['local_settings_binary']={}
p=Path('/usr/local/libexec/gnome-control-center-fingerprint-20260913')
if p.is_file():r['local_settings_binary']={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
print(json.dumps(r,indent=2))
