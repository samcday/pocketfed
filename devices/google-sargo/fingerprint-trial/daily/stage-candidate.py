#!/usr/bin/python3
"""Stage the verified candidate with finalization locked; never reboot or enroll."""
import hashlib,json,os,subprocess
from pathlib import Path
ROOT=Path('/var/tmp/sargo-fingerprint-services-20260912')
SERIAL='994AY18RSD'
IMAGE='sha256:39fd4d186f6235332d3ae1c6101b676091243d57d9d7d609a91f8962448f54b1'
MANIFEST='sha256:0e9857f2e728ae874706925166e42bc18123d2b17b28ee1ea65f6f2a88f6a1c0'

def out(*args):return subprocess.check_output(args,text=True).strip()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 assert os.getuid()==os.geteuid()==0
 assert [x for x in Path('/proc/cmdline').read_text().split() if x.startswith('androidboot.serialno=')]==['androidboot.serialno='+SERIAL]
 b=json.loads((ROOT/'baseline.json').read_text());facts=json.loads((ROOT/'base-facts-current.json').read_text())
 s=json.loads(out('rpm-ostree','status','--json'));assert s['transaction'] is None and not any(d.get('staged') for d in s['deployments'])
 booted=next(x for x in s['deployments'] if x['booted']);assert booted['checksum']==b['baseline_checksum'] and booted['container-image-reference-digest']==b['baseline_container_digest']
 assert all(booted.get(k)==v for k,v in b['request_fields'].items())
 assert booted['unlocked']=='none' and out('qbootctl','-x')==b['slot']=='_b'
 assert all(any(d['checksum']==h and d['pinned'] for d in s['deployments']) for h in b['pins'])
 for path,record in facts['selinux'].items():
  p=Path(path)
  if 'sha256' in record:assert sha(p)==record['sha256'],path
  else:assert os.readlink(p)==record['symlink'],path
 assert sha(Path('/etc/pam.d/phosh'))=='695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
 persistent=Path('/ostree/deploy')/booted['osname']/'deploy'/(booted['checksum']+'.'+str(booted['serial']))
 query=['-qa','--qf','%{NAME}\t%{EPOCHNUM}:%{VERSION}-%{RELEASE}.%{ARCH}\n']
 assert sorted(out('rpm',*query).splitlines())==sorted(out('rpm','--root',str(persistent),*query).splitlines())
 units=('fprintd.service','qsee-supplicant.service','pocketfed-fpc-auth.socket','pocketfed-fpc-auth.service','pocketfed-keymaster-startup.service','qsee-app-loader@fpctzappfingerprint.service','qsee-shared-loader@cmnlib64.service','phosh-fingerprint-auth.socket')
 for unit in units:assert out('systemctl','show',unit,'-p','ActiveState','--value')=='inactive',unit
 index=json.loads((ROOT/'oci/index.json').read_text());assert len(index['manifests'])==1
 ref=index['manifests'][0];assert ref['digest']==MANIFEST and ref['annotations']['org.opencontainers.image.ref.name']=='candidate'
 path=ROOT/'oci/blobs/sha256'/MANIFEST.split(':')[1];assert sha(path)==MANIFEST.split(':')[1]
 manifest=json.loads(path.read_text());assert manifest['config']['digest']==IMAGE
 for item in [manifest['config'],*manifest['layers']]:
  p=ROOT/'oci/blobs/sha256'/item['digest'].split(':')[1]
  assert p.stat().st_size==item['size'] and sha(p)==item['digest'].split(':')[1]
 b['root_links']={str(p):os.readlink(p) for p in (Path('/ostree/root.a'),Path('/ostree/root.b'))}
 b['baseline_live_packages']=sorted(out('rpm',*query).splitlines())
 with (ROOT/'stage-attempt.json').open('x') as f:json.dump(b,f,indent=2)
 subprocess.run(['ostree','admin','pin','booted'],check=True)
 masks=['fprintd.service','qsee-supplicant.service','pocketfed-fpc-auth.socket','pocketfed-fpc-provision@.service','phosh-fingerprint-auth.socket']
 # All services are confirmed inactive; persistent masks prevent D-Bus or boot
 # activation during the transition, including masks previously removed live.
 subprocess.run(['systemctl','mask',*masks],check=True)
 assert all(os.readlink('/etc/systemd/system/'+u)=='/dev/null' for u in masks)
 print('Current daily deployment pinned; complete OCI verified; fingerprint activation masked. Staging with finalization locked.',flush=True)
 subprocess.run(['rpm-ostree','rebase','--cache-only','--skip-purge','--lock-finalization','ostree-unverified-image:oci:'+str(ROOT/'oci')+':candidate'],check=True)
if __name__=='__main__':main()
