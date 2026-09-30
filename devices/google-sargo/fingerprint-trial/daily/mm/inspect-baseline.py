#!/usr/bin/python3
"""Read the exact daily deployment and preserve staging comparison metadata."""
import hashlib,json,os,subprocess
from pathlib import Path
out=lambda *args:subprocess.check_output(args,text=True).strip()
assert [x for x in Path('/proc/cmdline').read_text().split() if x.startswith('androidboot.serialno=')]==['androidboot.serialno=994AY18RSD']
s=json.loads(out('rpm-ostree','status','--json'))
assert s['transaction'] is None and not any(d.get('staged') for d in s['deployments'])
d=next(d for d in s['deployments'] if d['booted'])
assert d['checksum']=='06d451841d0119060d454da1744bdb47ce1bec3815530775aec3be4f235560b2'
assert out('getenforce')=='Enforcing'
r={'baseline_checksum':d['checksum'],'baseline_container_digest':d['container-image-reference-digest'],
   'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
   'slot':out('qbootctl','-x'),'pins':[v['checksum'] for v in s['deployments'] if v.get('pinned')],
   'request_fields':{k:v for k,v in d.items() if k.startswith('requested-') or k in ('regenerate-initramfs','initramfs-args','initramfs-etc')},
   'pam_sha256':hashlib.sha256(Path('/etc/pam.d/phosh').read_bytes()).hexdigest(),
   'policy_sha256':hashlib.sha256(Path('/etc/selinux/targeted/policy/policy.35').read_bytes()).hexdigest(),
   'live_packages':sorted(out('rpm','-qa','--qf','%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n').splitlines()),
   'var_available_bytes':os.statvfs('/var').f_bavail*os.statvfs('/var').f_frsize}
print(json.dumps(r,indent=2))
