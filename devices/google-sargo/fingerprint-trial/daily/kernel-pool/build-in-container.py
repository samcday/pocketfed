#!/usr/bin/python3
"""Build only the experimental module with the packaged kernel's native compiler."""
import json
from pathlib import Path
import subprocess

commands = [
    ['dnf', '-y', 'install', 'flex', 'bison', 'bc', 'openssl-devel',
     'elfutils-libelf-devel', 'dwarves', 'kmod'],
]
make = ['make', '-C', '/source', 'O=/build', 'ARCH=arm64',
        'LOCALVERSION=-0.pocketfed.sdm670.11.fc46.aarch64', '-j8']
commands.extend([
    make + ['modules_prepare'],
    make + ['M=/source/drivers/tee/qseecom', 'MO=/build/qseecom', 'modules'],
])
Path('/build/build-commands.json').write_text(json.dumps(commands, indent=2) + '\n')
for command in commands:
    print('BUILD_COMMAND ' + json.dumps(command), flush=True)
    subprocess.run(command, check=True)
