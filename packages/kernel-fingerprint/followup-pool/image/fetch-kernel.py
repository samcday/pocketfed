#!/usr/bin/python3
"""Download this approved COPR build and verify the four installed kernel RPMs privately."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.parse
import urllib.request
from copr.v3 import Client

OUT = Path(__file__).resolve().parents[4] / 'out/fingerprint-pool-fix-20260913'
FINGERPRINT = 'e58892d1cbf2fac58a3490c94e2c57a4a2603023'
NAMES = ('kernel', 'kernel-core', 'kernel-modules', 'kernel-modules-core')


def download(url, path):
    assert urllib.parse.urlparse(url).hostname == 'download.copr.fedorainfracloud.org'
    with urllib.request.urlopen(url, timeout=60) as response, path.open('xb') as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)


def main():
    client = Client.create_from_config_file()
    build = client.build_proxy.get(10980882)
    assert build['ownername'] == 'samcday'
    assert build['project_dirname'] == 'kernel-sdm670-mainline:custom:fingerprint-trial'
    assert build['source_package']['version'] == '7.1.2-0.pocketfed.sdm670.12'
    chroot = client.build_chroot_proxy.get(10980882, 'fedora-rawhide-aarch64')
    assert build['state'] == chroot['state'] == 'succeeded', (build['state'], chroot['state'])
    assert not (OUT / 'kernel-rpms.json').exists()
    root = OUT / 'kernel-rpms'
    root.mkdir()
    key = OUT / 'kernel-copr-pubkey.gpg'
    download('https://download.copr.fedorainfracloud.org/results/samcday/kernel-sdm670-mainline/pubkey.gpg', key)
    db = OUT / 'kernel-rpmdb'
    db.mkdir()
    subprocess.run(['rpm', '--dbpath', str(db), '--import', str(key)], check=True)
    records = []
    for name in NAMES:
        filename = name + '-7.1.2-0.pocketfed.sdm670.12.fc46.aarch64.rpm'
        path = root / filename
        url = chroot['result_url'] + filename
        download(url, path)
        verification = subprocess.check_output(['rpm', '--dbpath', str(db), '-Kv', str(path)], text=True)
        assert 'key fingerprint: ' + FINGERPRINT + ': OK' in verification, verification
        assert 'NOKEY' not in verification and 'NOT OK' not in verification
        nevra = subprocess.check_output(['rpm', '-qp', '--qf', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}', str(path)], text=True)
        assert nevra + '.rpm' == filename
        records.append({'path': str(path), 'url': url, 'nevra': nevra,
                        'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                        'bytes': path.stat().st_size, 'signature_fingerprint': FINGERPRINT,
                        'signature_verification': verification})
        print('Verified ' + filename, flush=True)
    report = {'build_id': 10980882, 'state': 'succeeded', 'chroot': 'fedora-rawhide-aarch64',
              'source_rpm_sha256': '389c6ed63da1d6cf96c9d014131b01ffea0d7e71b9cf322dd0f4e0bf74cc6c9b',
              'rpms': records}
    (OUT / 'kernel-rpms.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
