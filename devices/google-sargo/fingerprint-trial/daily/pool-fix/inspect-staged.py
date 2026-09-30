#!/usr/bin/python3
"""Read the actual locked deployment, pin set, payloads and labels before activation."""
import ast,hashlib,json,os,re,subprocess
from pathlib import Path
from staged_state import read_staged
ROOT=Path('/var/tmp/sargo-fingerprint-pool-20260913')
MANIFEST=json.loads((ROOT/'candidate-identity.json').read_text())['manifest']

def out(*args):return subprocess.check_output(args,text=True).strip()
def facts(p):
 if p.is_symlink():return {'symlink':os.readlink(p)}
 if p.is_file():return {'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':p.stat().st_size}
 return None

def main():
 assert [x for x in Path('/proc/cmdline').read_text().split() if x.startswith('androidboot.serialno=')]==['androidboot.serialno=994AY18RSD']
 old=json.loads((ROOT/'stage-attempt.json').read_text());expected=json.loads((ROOT/'candidate-facts-current.json').read_text())
 s=json.loads(out('rpm-ostree','status','--json'));assert s['transaction'] is None
 staged=[d for d in s['deployments'] if d.get('staged')];assert len(staged)==1;d=staged[0]
 assert d['container-image-reference-digest']==MANIFEST
 assert all(d.get(k)==v for k,v in old['request_fields'].items())
 assert next(x for x in s['deployments'] if x['booted'])['checksum']==old['baseline_checksum']
 assert all(any(x['checksum']==h and x['pinned'] for x in s['deployments']) for h in [old['baseline_checksum'],*old['pins']])
 assert out('qbootctl','-x')==old['slot']
 assert all(os.readlink(p)==v for p,v in old['root_links'].items())
 state=read_staged()
 assert state['locked'] is True and state['target']['name']==d['checksum']+'.'+str(d['serial'])
 root=Path('/ostree/deploy')/d['osname']/'deploy'/(d['checksum']+'.'+str(d['serial']))
 def path(name):
  if name.startswith('/etc/') and not (root/'etc').exists():return root/'usr'/name.lstrip('/')
  return root/name.lstrip('/')
 errors=[]
 for group in ('files','systemd','authentication','selinux'):
  for name,record in expected[group].items():
   target=path(name)
   actual=facts(target)
   # The independent boot parser's legacy files inventory hashes through
   # LPAC certificate symlinks. Preserve the current link target as well as
   # checking those recorded bytes, without following a link outside this root.
   if group=='files' and 'sha256' in record and target.is_symlink():
    if not Path(name).is_symlink() or os.readlink(target)!=os.readlink(name):
     errors.append(['symlink_changed',name,os.readlink(target)])
    if target.resolve().is_relative_to(root.resolve()):
     actual={'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size}
   if actual!=record:errors.append([group,name,actual,record])
 packages=sorted(out('rpm','--root',str(root),'-qa','--qf','%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n').splitlines())
 expected_packages=sorted(expected['packages_evra']+['tailscale\t0:1.98.8-1.fc45.aarch64'])
 assert packages==expected_packages,[sorted(set(packages)-set(expected_packages)),sorted(set(expected_packages)-set(packages))]
 tree=ast.parse((ROOT/'boot-parser.py').read_text());tree.body=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.FunctionDef))]
 ns={};exec(compile(tree,'boot-parser.py','exec'),ns)
 module=root/'usr/lib/modules'/expected['kernel_release'];boot=ns['boot_facts'](module)
 assert boot==expected['boot']
 for unit in expected['activation_masks']:
  assert os.readlink('/etc/systemd/system/'+unit)=='/dev/null'
  assert os.readlink(path('/etc/systemd/system/'+unit))=='/dev/null'
 broker=root/'usr/bin/pocketfed-fpc-auth'
 labels={str(p.relative_to(root)):os.getxattr(p,'security.selinux').rstrip(b'\0').decode() for p in (broker,root/'usr/bin/qsee-sargo-rpmb',root/'usr/libexec/phosh-fingerprint-worker')}
 # ostree executes as install_t, which can read raw unmapped contexts. The
 # SSH caller cannot, so getxattr can report unlabeled_t under the old policy.
 # Require the exact stored label AND that this checkout shares that object's
 # inode. Startup independently requires the mapped label after the new boot.
 raw=out('ostree','--repo=/ostree/repo','ls','-C','-X',d['checksum'],'/usr/bin/pocketfed-fpc-auth')
 match=re.fullmatch(r"-00755 0 0 +(\d+) ([0-9a-f]{64}) \{ (.*) \} /usr/bin/pocketfed-fpc-auth",raw)
 assert match and int(match[1])==broker.stat().st_size,raw
 attrs=ast.literal_eval(match[3])
 assert attrs==[(b'security.selinux',b'system_u:object_r:pocketfed_fpc_auth_exec_t:s0')],attrs
 obj=Path('/ostree/repo/objects')/match[2][:2]/(match[2][2:]+'.file')
 assert os.path.samefile(broker,obj), 'checkout does not share the verified object inode'
 labels['stored_broker_context']='system_u:object_r:pocketfed_fpc_auth_exec_t:s0'
 labels['broker_object_checksum']=match[2]
 labels['broker_same_object_inode']=True
 report={'status':'locked staged inspection passed' if not errors else 'staged content mismatch','staged_checksum':d['checksum'],'staged_serial':d['serial'],'manifest':MANIFEST,'baseline_checksum':old['baseline_checksum'],'slot':old['slot'],'root_links':old['root_links'],'locked':True,'package_count':len(packages),'requests_and_pins_preserved':True,'boot':boot,'policy_sha256':expected['selinux']['/etc/selinux/targeted/policy/policy.35']['sha256'],'labels':labels,'errors':errors,'root':str(root),'regenerate_initramfs':d.get('regenerate-initramfs')}
 (ROOT/'staged-inspection.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps({k:report[k] for k in ('status','staged_checksum','locked','package_count','requests_and_pins_preserved','labels','errors')},indent=2))
 assert not errors
if __name__=='__main__':main()
