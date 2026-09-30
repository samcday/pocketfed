#!/usr/bin/python3
"""Require only the six recorded package and three policy-file changes."""
import argparse,hashlib,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('evidence',type=Path);a=p.parse_args();root=a.evidence
b=json.loads((root/'base-facts-current.json').read_text());c=json.loads((root/'candidate-facts-current.json').read_text());m=json.loads((root/'context/inputs/manifest.json').read_text())
packages={};allowed=set()
for r in m['package_artifacts']:
 path=Path(r['path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==r['sha256']
 line=subprocess.check_output(['rpm','-qp','--qf','%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}',str(path)],text=True)
 name,evra=line.split('\t');assert name not in packages;packages[name]=evra
 allowed.update(subprocess.check_output(['rpm','-qpl',str(path)],text=True).splitlines())
rows=lambda r:dict(line.split('\t',1) for line in r['packages_evra'])
bp,cp=rows(b),rows(c)
assert {k:v for k,v in cp.items() if k not in packages}=={k:v for k,v in bp.items() if k not in packages}
assert all(cp.get(k)==v for k,v in packages.items())
for key in ('kernel_release','boot','fingerprint_dt','fingerprint_modules','initramfs_modules','authentication','activation_masks','broker_runtime_state_present','initialization_marker_present'):
 assert b[key]==c[key],key
changes={}
for key in ('files','systemd'):
 delta={k for k in set(b[key])|set(c[key]) if b[key].get(k)!=c[key].get(k)}
 assert delta<=allowed,(key,sorted(delta-allowed));changes[key]=sorted(delta)
allowed_policy={'/etc/selinux/targeted/policy/policy.35','/etc/selinux/targeted/contexts/files/file_contexts','/etc/selinux/targeted/contexts/files/file_contexts.bin'}
delta={k for k in set(b['selinux'])|set(c['selinux']) if b['selinux'].get(k)!=c['selinux'].get(k)};assert delta==allowed_policy,delta
report=c['upgrade_report'];assert report['base_image']==m['base_image_id']
for name,target in [('policy.35','/etc/selinux/targeted/policy/policy.35'),('file_contexts','/etc/selinux/targeted/contexts/files/file_contexts')]:
 assert c['selinux'][target]['sha256']==m['input_files'][name]
assert c['selinux']['/etc/selinux/targeted/contexts/files/file_contexts.bin']['sha256']==report['file_contexts_bin_sha256']
assert report['services_activated'] is False
result={'status':'Independent image comparison passed; not yet staged or booted','base_image':m['base_image_id'],'candidate_image':'sha256:39fd4d186f6235332d3ae1c6101b676091243d57d9d7d609a91f8962448f54b1','updated_packages':packages,'package_count':len(cp),'preserved':['complete embedded boot payload','kernel, DT and fingerprint modules','current baseline initramfs module inventory','PIN/authentication policy','all unrelated package versions','unrelated systemd files','five activation masks'],'changed_package_files':changes,'changed_policy_files':sorted(delta),'initramfs_module_count':len(c['initramfs_modules']),'broker_policy_sha256':report['policy_sha256'],'sources':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},'evidence':{n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in ('base-facts-current.json','candidate-facts-current.json','build-r2.log')}}
(root/'comparison.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ('status','package_count','initramfs_module_count','changed_package_files')},indent=2))
