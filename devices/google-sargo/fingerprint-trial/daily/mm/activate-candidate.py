#!/usr/bin/python3
"""Activate only the fully inspected staged deployment; this DOES reboot."""
from pathlib import Path
import hashlib,importlib.util,json,subprocess,sys
ROOT=Path('/var/tmp/sargo-fingerprint-mm-20260912')
assert sys.argv[1:]==['activate-reviewed-candidate']
# Repeat read-only identity, payload, request, pin, slot and finalization-lock checks.
spec=importlib.util.spec_from_file_location('staged',ROOT/'inspect-staged.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.main()
i=json.loads((ROOT/'staged-inspection.json').read_text());p=json.loads((ROOT/'boot-preview-validation.json').read_text())
assert p['status']=='regular-file boot preview passed' and p['locked'] and p['partition_written'] is False
assert p['staged_checksum']==i['staged_checksum'] and p['manifest']==i['manifest']
assert hashlib.sha256(Path(p['preview_path']).read_bytes()).hexdigest()==p['boot_preview']['sha256']
with (ROOT/'activation-attempt.json').open('x') as f:json.dump({'checksum':i['staged_checksum'],'manifest':i['manifest'],'reboot_requested':True},f)
print('Activating the exact inspected fingerprint deployment; reboot follows.',flush=True)
# Container-derived deployments require the manifest digest, not the commit ID.
subprocess.run(['rpm-ostree','finalize-deployment',i['manifest']],check=True)
