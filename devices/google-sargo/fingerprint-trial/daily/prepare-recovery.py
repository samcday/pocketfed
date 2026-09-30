#!/usr/bin/python3
"""Host-only: prepare a frozen daily-device recovery bundle, never execute it."""
import argparse,hashlib,json,shutil
from pathlib import Path
HERE=Path(__file__).resolve().parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def prepare(output,binary,booted_checksum,policy_sha256):
 assert not output.exists()
 for s in (booted_checksum,policy_sha256): assert len(s)==64 and set(s)<=set('0123456789abcdef')
 assert binary.is_file()
 output.mkdir(mode=0o700)
 shutil.copy2(binary,output/'recover-storage-once')
 (output/'recover-storage-once').chmod(0o700)
 shutil.copy2(HERE/'launch-recovery.py',output)
 unit=(HERE.parents[3]/'packages/fpc-auth/pocketfed-fpc-provision@.service').read_text()
 assert 'ExecStart=/usr/bin/pocketfed-fpc-auth provision %i' in unit
 unit=unit.replace('Description=Provision native fingerprint service credential for UID %i','Description=One authorized storage recovery for sam-sargo UID 1000')
 unit=unit.replace('ConditionKernelVersion=>=7.1.2-0.pocketfed.sdm670.11','ConditionKernelVersion=7.1.2-0.pocketfed.sdm670.11.fc46.aarch64\nConditionKernelCommandLine=androidboot.serialno=994AY18RSD')
 unit=unit.replace('ExecStart=/usr/bin/pocketfed-fpc-auth provision %i','ExecStart=/run/sargo-fingerprint-storage-recovery/recover-storage-once recover-storage-sam-sargo-994AY18RSD-uid-1000')
 unit+='\n[Unit]\nStartLimitIntervalSec=infinity\nStartLimitBurst=1\n'
 (output/'pocketfed-fpc-storage-recovery-once.service').write_text(unit)
 manifest={'serial':'994AY18RSD','linux_uid':1000,'gatekeeper_uid':'0x700003e8','booted_checksum':booted_checksum,'policy_sha256':policy_sha256,'binary_sha256':sha(binary),'files':{p.name:sha(p) for p in output.iterdir()},'prior_receipt_preserved':True,'original_intent_snapshot_retained':True,'automatic_retry':False}
 (output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 return manifest
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',required=True,type=Path);p.add_argument('--binary',required=True,type=Path);p.add_argument('--booted-checksum',required=True);p.add_argument('--policy-sha256',required=True);a=p.parse_args()
 print(json.dumps(prepare(a.output,a.binary,a.booted_checksum,a.policy_sha256),indent=2))
