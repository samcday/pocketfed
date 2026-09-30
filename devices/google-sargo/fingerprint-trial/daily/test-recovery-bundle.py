#!/usr/bin/python3
"""Root build-container checks; no live services, credentials or devices."""
from pathlib import Path
import hashlib,importlib.util,json,os,tempfile
HERE=Path(__file__).resolve().parent

def load(name):
 spec=importlib.util.spec_from_file_location(name,HERE/(name+'.py'));m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
prepare=load('prepare-recovery');launch=load('launch-recovery')
assert os.getuid()==0, 'Run in the offline root build container'
with tempfile.TemporaryDirectory() as directory:
 root=Path(directory);binary=root/'synthetic-binary';binary.write_bytes(b'synthetic executable; never run\n')
 manifest=prepare.prepare(root/'bundle',binary,'a'*64,'b'*64)
 assert launch.check_bundle(root/'bundle')==manifest
 unit=(root/'bundle/pocketfed-fpc-storage-recovery-once.service').read_text()
 assert 'ConditionKernelCommandLine=androidboot.serialno=994AY18RSD' in unit
 assert 'ConditionKernelVersion=7.1.2-0.pocketfed.sdm670.11.fc46.aarch64' in unit
 assert 'StartLimitBurst=1' in unit and 'StartLimitIntervalSec=infinity' in unit
 assert 'TimeoutStopSec=infinity' in unit and 'TimeoutStartSec=infinity' in unit
 assert 'DeviceAllow=/dev/teepriv' not in unit and 'DeviceAllow=/dev/mmc' not in unit
 assert 'recover-storage-sam-sargo-994AY18RSD-uid-1000' in unit and '%i' not in unit
 assert not any('WantedBy=' in line or 'RequiredBy=' in line for line in unit.splitlines())
 for kind in ('binary','unit','symlink','writable','identity'):
  bundle=root/kind;prepare.prepare(bundle,binary,'a'*64,'b'*64)
  p=bundle/'recover-storage-once'
  if kind=='binary':p.write_bytes(b'altered')
  elif kind=='unit':(bundle/'pocketfed-fpc-storage-recovery-once.service').write_text(unit.replace('0x700003e8','0').replace('UID 1000','UID 0'))
  elif kind=='symlink':p.unlink();p.symlink_to(binary)
  elif kind=='writable':p.chmod(0o777)
  else:
   m=json.loads((bundle/'manifest.json').read_text());m['linux_uid']=0;(bundle/'manifest.json').write_text(json.dumps(m))
  try:launch.check_bundle(bundle)
  except AssertionError:pass
  else:raise AssertionError('unsafe bundle accepted: '+kind)
print('PASS: frozen recovery bundle integrity, ownership/modes, symlink refusal, fixed daily identity and unit activation/device limits')
