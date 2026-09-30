#!/usr/bin/python3
"""Snapshot explicit optional-listener sources for a local qsee-supplicant RPM."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile

HERE = Path(__file__).resolve().parent
FILES = ('main.c', 'rpmb-protocol.c', 'rpmb-protocol.h', 'rpmb-mmc.c', 'rpmb-mmc.h',
         'sargo-device.h', 'write-policy.h', 'test-rpmb-protocol.c', 'test-rpmb-mmc.c',
         'test-sargo-device.c', 'test-receiver.c', 'Makefile', 'README.md',
         '90-sargo-rpmb.conf', 'source-origin.json', 'LICENSE.MIT')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    contents = {name: (HERE / 'sargo-rpmb' / name).read_bytes() for name in FILES}
    contents['sources.json'] = (json.dumps({name: hashlib.sha256(data).hexdigest()
        for name, data in contents.items()}, sort_keys=True, indent=2) + '\n').encode()
    # Uncompressed deterministic source archive: no compiled/private artifacts.
    with args.output.open('xb') as stream, tarfile.open(fileobj=stream, mode='w') as archive:
        for name, data in sorted(contents.items()):
            info = tarfile.TarInfo('sargo-rpmb/' + name)
            info.size = len(data); info.mode = 0o644; info.mtime = 0
            archive.addfile(info, io.BytesIO(data))
    print(json.dumps({'archive': str(args.output),
        'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest()}))


if __name__ == '__main__': main()
