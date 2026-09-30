#!/usr/bin/python3
"""Real ARM64 exporter / host OpenSSL interoperability; synthetic data only."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--binary', type=Path, required=True)
p.add_argument('--image', required=True)
args = p.parse_args()
os.umask(0o077)
with tempfile.TemporaryDirectory(prefix='sargo-lab-export-test-') as temp:
    root = Path(temp)
    public = root / 'public'; public.mkdir()
    subprocess.run(['openssl', 'genpkey', '-algorithm', 'RSA', '-pkeyopt', 'rsa_keygen_bits:3072',
                    '-out', str(root / 'private.pem')], check=True, capture_output=True)
    subprocess.run(['openssl', 'pkey', '-in', str(root / 'private.pem'), '-pubout',
                    '-out', str(public / 'public.pem')], check=True, capture_output=True)
    (public / 'invalid.pem').write_text('invalid public key\n')
    def encrypt(data, key='public.pem'):
        return subprocess.run(['podman', 'run', '--rm', '-i', '--network=none',
            '--security-opt', 'label=disable', '-v', str(args.binary.resolve().parent) + ':/program:ro',
            '-v', str(public) + ':/public:ro', args.image,
            '/program/' + args.binary.name, '/public/' + key], input=data, capture_output=True)
    original = os.urandom(160)
    result = encrypt(original)
    assert result.returncode == 0 and len(result.stdout) == 384
    recovered = subprocess.run(['openssl', 'pkeyutl', '-decrypt', '-inkey', str(root / 'private.pem'),
        '-pkeyopt', 'rsa_padding_mode:oaep', '-pkeyopt', 'rsa_oaep_md:sha256'],
        input=result.stdout, capture_output=True, check=True)
    assert recovered.stdout == original
    for data in (b'', original[:-1], original + b'x'):
        result = encrypt(data)
        assert result.returncode != 0 and result.stdout == b''
    result = encrypt(original, 'invalid.pem')
    assert result.returncode != 0 and result.stdout == b''
    print('PASS real ARM64 RSA-OAEP exporter / host decryption, exact input length and invalid-key refusal; private key stayed on host')
