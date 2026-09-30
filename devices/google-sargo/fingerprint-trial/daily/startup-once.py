#!/usr/bin/python3
"""Start the verified daily service prerequisites once; no credential operation."""
from pathlib import Path
import hashlib,json,os,stat,subprocess
ROOT=Path('/var/tmp/sargo-fingerprint-services-20260912')
UNITS=('qsee-supplicant.service','qsee-shared-loader@cmnlib64.service','qsee-app-loader@fpctzappfingerprint.service','pocketfed-keymaster-startup.service')

def out(*args):return subprocess.check_output(args,text=True).strip()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 assert os.getuid()==os.geteuid()==0
 assert [x for x in Path('/proc/cmdline').read_text().split() if x.startswith('androidboot.serialno=')]==['androidboot.serialno=994AY18RSD']
 expected=json.loads((ROOT/'staged-inspection.json').read_text())
 assert expected['status']=='locked staged inspection passed' and not expected['errors']
 s=json.loads(out('rpm-ostree','status','--json'));assert s['transaction'] is None and not any(d.get('staged') for d in s['deployments'])
 b=next(d for d in s['deployments'] if d['booted']);assert b['checksum']==expected['staged_checksum']
 assert b['container-image-reference-digest']==expected['manifest']
 assert os.uname().release=='7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
 assert out('getenforce')=='Enforcing' and sha(Path('/etc/selinux/targeted/policy/policy.35'))==expected['policy_sha256']
 assert sha(Path('/etc/pam.d/phosh'))=='695d627f3d54bf6010b001bef211792f536437c34b01d60833862c4a9509d5b6'
 assert os.getxattr('/usr/bin/pocketfed-fpc-auth','security.selinux').rstrip(b'\0')==b'system_u:object_r:pocketfed_fpc_auth_exec_t:s0'
 for unit in (*UNITS,'fprintd.service','pocketfed-fpc-auth.socket','pocketfed-fpc-auth.service','phosh-fingerprint-auth.socket'):
  assert out('systemctl','show',unit,'-p','ActiveState','--value')=='inactive',unit
 for unit in ('fprintd.service','qsee-supplicant.service','pocketfed-fpc-auth.socket','phosh-fingerprint-auth.socket'):
  assert out('systemctl','show',unit,'-p','LoadState','--value')=='masked',unit
 source=Path('/usr/share/doc/qsee-supplicant-sargo-rpmb/90-sargo-rpmb.conf')
 assert sha(source)=='6fd338c6f56e3aebda0335e88190e593a3dd413aa90ddf1c7712209bb9fb740a'
 def drop(unit,name,text):
  directory=Path('/etc/systemd/system')/(unit+'.d');directory.mkdir(mode=0o755,exist_ok=True)
  st=directory.lstat();assert stat.S_ISDIR(st.st_mode) and st.st_uid==st.st_gid==0 and not(st.st_mode&0o022)
  path=directory/name
  if path.exists() or path.is_symlink():assert path.is_file() and not path.is_symlink() and path.read_text()==text
  else:
   with path.open('x') as f:f.write(text)
   path.chmod(0o644)
 with (ROOT/'startup-attempt.json').open('x') as f:json.dump({'deployment':b['checksum'],'automatic_retry':False,'operation':'listener, loaders and per-boot HMAC startup only'},f)
 drop('qsee-supplicant.service','90-sargo-rpmb.conf',source.read_text())
 for unit in UNITS[1:3]:
  drop(unit,'99-fingerprint-lifetime.conf','[Unit]\nBindsTo=qsee-supplicant.service\n[Service]\nRestart=no\nTimeoutStartSec=infinity\nTimeoutStopSec=infinity\nLimitCORE=0\n')
 drop('pocketfed-fpc-auth.service','99-fingerprint-startup.conf','[Service]\nType=exec\nRestart=no\n')
 drop('fprintd.service','99-fingerprint-lifetime.conf','[Unit]\nBindsTo=qsee-supplicant.service\n[Service]\nRestart=no\nTimeoutStopSec=infinity\nLimitCORE=0\n')
 subprocess.run(['systemctl','unmask','qsee-supplicant.service'],check=True)
 subprocess.run(['systemctl','daemon-reload'],check=True)
 try:
  subprocess.run(['systemctl','start','pocketfed-keymaster-startup.service'],check=True)
  for unit in UNITS:assert out('systemctl','show',unit,'-p','ActiveState','--value')=='active',unit
 except BaseException:
  # Retain the attempt and journal. Stop sessions in reverse dependency order;
  # the units deliberately impose no forced timeout on synchronous secure calls.
  for unit in reversed(UNITS):subprocess.run(['systemctl','stop',unit],check=True)
  raise
 report={'status':'daily normal prerequisites started','deployment':b['checksum'],'selinux':'Enforcing','units':{u:out('systemctl','show',u,'-p','ActiveState,SubState,Result,NRestarts') for u in UNITS},'credential_operation':False}
 (ROOT/'startup-result.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':main()
