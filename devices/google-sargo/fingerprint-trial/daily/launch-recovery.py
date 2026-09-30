#!/usr/bin/python3
"""One explicitly authorized recovery, after the new daily deployment passes startup.

This is not provisioning and is never run automatically. Refuse existing new
receipts and every state outside the reviewed daily-device failure. No credential
contents leave the process or phone. The native executable durably records the
attempt and original intent before its one reserved-UID Gatekeeper enrollment.
"""
from pathlib import Path
import hashlib,json,os,stat,subprocess,sys

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(*args):return subprocess.check_output(args,text=True).strip()
def regular(p,length=None):
 s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_uid==s.st_gid==0 and stat.S_IMODE(s.st_mode)==0o600 and s.st_nlink==1,p.name
 assert length is None or s.st_size==length,p.name

def check_bundle(root):
 m=json.loads((root/'manifest.json').read_text())
 assert m['serial']=='994AY18RSD' and m['linux_uid']==1000 and m['gatekeeper_uid']=='0x700003e8'
 assert m['automatic_retry'] is False
 assert set(m['files'])=={'recover-storage-once','launch-recovery.py','pocketfed-fpc-storage-recovery-once.service'}
 for name,h in m['files'].items():
  p=root/name;s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_uid==s.st_gid==0 and not (s.st_mode&0o022) and s.st_nlink==1
  assert sha(p)==h,name
 assert m['binary_sha256']==m['files']['recover-storage-once']
 return m

def main():
 assert os.getuid()==os.geteuid()==0
 assert sys.argv[1:]==['run-once-after-approval']
 root=Path(__file__).resolve().parent;m=check_bundle(root)
 tokens=Path('/proc/cmdline').read_text().split()
 assert [s for s in tokens if s.startswith('androidboot.serialno=')]==['androidboot.serialno=994AY18RSD']
 assert not any(s.startswith('pocketfed.liveboot=') for s in tokens)
 assert os.uname().release=='7.1.2-0.pocketfed.sdm670.11.fc46.aarch64'
 assert b'google,sargo' in Path('/proc/device-tree/compatible').read_bytes().split(b'\0')
 state=json.loads(run('rpm-ostree','status','--json'))
 assert state['transaction'] is None and not any(d.get('staged') for d in state['deployments'])
 booted=next(d for d in state['deployments'] if d['booted']);assert booted['checksum']==m['booted_checksum']
 assert run('getenforce')=='Enforcing'
 assert sha(Path('/etc/selinux/targeted/policy/policy.35'))==m['policy_sha256']
 for unit in ('fprintd.service','pocketfed-fpc-auth.socket','pocketfed-fpc-auth.service','phosh-fingerprint-auth.socket'):
  assert run('systemctl','show',unit,'-p','ActiveState','--value')=='inactive',unit
 for unit in ('fprintd.service','pocketfed-fpc-auth.socket','phosh-fingerprint-auth.socket'):
  assert run('systemctl','show',unit,'-p','LoadState','--value')=='masked',unit
 for unit in ('qsee-supplicant.service','qsee-shared-loader@cmnlib64.service','qsee-app-loader@fpctzappfingerprint.service','pocketfed-keymaster-startup.service'):
  assert run('systemctl','show',unit,'-p','ActiveState','--value')=='active',unit
  assert run('systemctl','show',unit,'-p','NRestarts','--value')=='0',unit
 pid=int(run('systemctl','show','qsee-supplicant.service','-p','MainPID','--value'));assert pid>1
 exe=Path('/usr/bin/qsee-sargo-rpmb')
 assert os.readlink('/proc/'+str(pid)+'/exe')==str(exe)
 assert sha(exe)=='300662ae47ff9bcdac15c1f89413b5a1f169e55ff417d92b2c5deb49d158ffbb'
 assert Path('/proc/'+str(pid)+'/cmdline').read_bytes().split(b'\0')==[b'/usr/bin/qsee-sargo-rpmb',b'--serve-authenticated',b'']
 assert run('systemctl','show','qsee-supplicant.service','-p','Restart','--value')=='no'
 store=Path('/var/lib/pocketfed-fpc-auth');s=store.lstat()
 assert stat.S_ISDIR(s.st_mode) and s.st_uid==s.st_gid==0 and stat.S_IMODE(s.st_mode)==0o700
 assert {p.name for p in store.iterdir()}=={'.lock','uid-1000.intent','uid-1000.first-recovery-attempt'}
 for n,size in {'.lock':0,'uid-1000.intent':160,'uid-1000.first-recovery-attempt':132}.items():regular(store/n,size)
 assert (store/'uid-1000.first-recovery-attempt').read_bytes()==b"One controlled recovery of this trial's unpublished native UID 0x700003e8.\nOriginal intent and secret retained. No automatic retry.\n"
 assert {str(p.relative_to('/var/lib/fprint')) for p in Path('/var/lib/fprint').rglob('*')}=={'fpc-qsee','fpc-qsee/device.lock'}
 regular(Path('/var/lib/qsee-supplicant/pocketfed/fpc-sargo-v1.db'),77)
 # Existing bundle directory and runtime unit make this launcher fail closed
 # before native code as well. Native durable receipts survive reboot.
 target=Path('/run/sargo-fingerprint-storage-recovery');target.mkdir(mode=0o755)
 import shutil
 shutil.copy2(root/'recover-storage-once',target/'recover-storage-once')
 subprocess.run(['chcon','--reference=/usr/bin/pocketfed-fpc-auth',str(target/'recover-storage-once')],check=True)
 unit='pocketfed-fpc-storage-recovery-once.service'
 with Path('/run/systemd/system',unit).open('xb') as f:f.write((root/unit).read_bytes())
 subprocess.run(['systemctl','daemon-reload'],check=True)
 subprocess.run(['systemctl','start',unit],check=True)
 print('Recovery service completed; inspect credential metadata and authorization before enrollment.')
if __name__=='__main__':main()
