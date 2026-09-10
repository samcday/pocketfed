#!/usr/bin/env python3
"""Check packaged configuration in generated source and the installed binary.

Do not set --defaults or use a fixture output-directory override here: those
would conceal a broken build that retained upstream development defaults.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', required=True, type=Path)
parser.add_argument('--binary', required=True, type=Path)
args = parser.parse_args()

expected = {
    'DEFAULTSDIR': '/usr/share/phosh-first-boot',
    'LOCALEDIR': '/usr/share/locale',
    'OUTPUTDIR': '/var/lib/phosh-first-boot',
}
config = dict(re.findall(r'pub static (\w+): &str = "([^"]*)";', args.config.read_text()))
for constant, value in expected.items():
    if config.get(constant) != value:
        raise SystemExit(f'{constant}: expected {value!r}, got {config.get(constant)!r}')

binary = args.binary.read_bytes()
for value in expected.values():
    if value.encode() not in binary:
        raise SystemExit(f'Packaged binary does not contain configured path {value!r}')
for value in ('/usr/local/share/phosh-first-boot', '/usr/local/share/locale', '/run/phosh-first-boot'):
    if value.encode() in binary:
        raise SystemExit(f'Packaged binary contains upstream development path {value!r}')

# GApplication handles --help before startup; this needs neither display nor bus.
environment = os.environ.copy()
environment['LC_ALL'] = 'C'
result = subprocess.run([str(args.binary.resolve()), '--help'], env=environment,
                        text=True, capture_output=True, check=True, timeout=15)
defaults = expected['DEFAULTSDIR'] + '/defaults.conf'
if f'default is {defaults}' not in result.stdout:
    raise SystemExit(f'Packaged binary --help did not expose expected default {defaults!r}:\n{result.stdout}')
print('Packaged Meson paths and binary --help defaults passed.')
