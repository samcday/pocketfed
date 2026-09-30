#!/usr/bin/env python3
"""Read-only fingerprint inventory; run over SSH stdin, save stdout locally.

Does not open biometric devices, read templates, invoke TAs, activate services,
mount filesystems, load modules, or change authentication. Firmware names only.
"""
import datetime
import glob
import json
import os
from pathlib import Path
import re
import subprocess


def command(argv):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=25)
        return {"argv": argv, "returncode": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"argv": argv, "error": str(error)}


def text(path):
    try:
        return Path(path).read_text().strip()
    except OSError as error:
        return str(error)


pattern = re.compile(r"fingerprint|fpctz|fpc102|qsee|qcomtee|keymaster|cmnlib", re.I)
dt = Path('/sys/firmware/devicetree/base')
nodes = {}
for root, dirs, files in os.walk(dt):
    compatible = Path(root, 'compatible')
    raw = compatible.read_bytes() if compatible.exists() else b''
    if pattern.search(root) or pattern.search(raw.decode('ascii', errors='replace')):
        props = {}
        for name in files:
            if name in ('compatible', 'status', 'reg', 'no-map', 'interrupts',
                        'interrupt-parent', 'memory-region', 'pinctrl-names',
                        'pinctrl-0', 'clocks', 'clock-names') or 'gpio' in name:
                value = Path(root, name).read_bytes()
                props[name] = ({"strings": value.rstrip(b'\0').decode('ascii').split('\0')}
                               if name in ('compatible', 'status', 'pinctrl-names', 'clock-names')
                               else {"hex": value.hex()})
        nodes[str(Path(root).relative_to(dt))] = props

devices = {}
for bus in ('spi', 'platform', 'tee'):
    for path in sorted(Path('/sys/bus', bus, 'devices').glob('*')):
        alias = text(path / 'modalias') if (path / 'modalias').exists() else ''
        if bus == 'spi' or pattern.search(str(path) + alias):
            devices[str(path)] = {"modalias": alias,
                                  "driver": os.path.realpath(path / 'driver') if (path / 'driver').exists() else None}

firmware = []
for base in ('/usr/lib/firmware', '/var/lib/firmware', '/var/run/firmware'):
    for root, dirs, files in os.walk(base):
        for name in files:
            if pattern.search(name):
                firmware.append(str(Path(root, name)))

kver = os.uname().release
config = Path('/usr/lib/modules', kver, 'config')
config_lines = [line for line in config.read_text().splitlines()
                if re.search(r'CONFIG_(TEE|QCOM.*(?:SCM|TEE|QSEE)|QSEECOM|FPC|FINGERPRINT|SPI_QCOM)', line)]
packages = command(['rpm', '-qa', '--qf', '%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n'])
packages['stdout'] = '\n'.join(sorted(line for line in packages.get('stdout', '').splitlines()
                                     if re.match(r'^(kernel|libfprint|fprintd|qsee|qcomtee|tee-|optee|phosh-|blob-wrangler)', line)))
units = command(['systemctl', 'list-unit-files', '--no-pager', '--no-legend'])
units['stdout'] = '\n'.join(line for line in units.get('stdout', '').splitlines()
                            if re.search(r'fprint|qsee|qcomtee|tee-supp|blob-wrangler', line, re.I))
modules = command(['lsmod'])
modules['stdout'] = '\n'.join(line for line in modules.get('stdout', '').splitlines()
                              if re.search(r'tee|qsee|fpc|finger', line, re.I))
output = {
    'captured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'kernel': kver,
    'model': (dt / 'model').read_bytes().rstrip(b'\0').decode(),
    'compatible': (dt / 'compatible').read_bytes().rstrip(b'\0').decode().split('\0'),
    'device_nodes': sorted({p for spec in ('/dev/tee*', '/dev/qsee*', '/dev/*fpc*', '/dev/*finger*') for p in glob.glob(spec)}),
    'dt_matches': nodes, 'bus_devices': devices, 'matching_firmware_paths': firmware,
    'kernel_config': config_lines, 'packages': packages, 'units': units, 'loaded_modules': modules,
    'kernel_messages': command(['journalctl', '-k', '-b', '--no-pager', '-o', 'short-monotonic', '-g', 'qsee|qcomtee|fingerprint|fpc|qcom_scm']),
    'qcomtee_module': command(['modinfo', 'qcomtee']),
    'blob_config': text('/usr/share/blob-wrangler/configs/google,sargo.toml'),
    'auth_fingerprint_references': command(['grep', '-HnE', 'fprint|fingerprint', '/etc/pam.d/phosh', '/etc/pam.d/system-auth', '/etc/pam.d/fingerprint-auth']),
}
print(json.dumps(output, indent=2))
