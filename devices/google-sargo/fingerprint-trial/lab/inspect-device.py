#!/usr/bin/python3
"""Report test-sargo metadata during disposable liveboot; no secure calls."""
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from lab_report import emit

sys.dont_write_bytecode = True
SERIAL = '99NAY1AZG1'
LAB_BUILD = 'google/sargo/sargo:12/SP2A.220505.002/8353555:user/release-keys'


def command(*args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=30)
    return {'status': result.returncode, 'stdout': result.stdout.strip(),
            'stderr': result.stderr.strip()}


def device(path):
    info = path.stat()
    return {'path': str(path), 'kind': 'char' if stat.S_ISCHR(info.st_mode) else 'block',
            'major': os.major(info.st_rdev), 'minor': os.minor(info.st_rdev),
            'uid': info.st_uid, 'gid': info.st_gid,
            'mode': oct(stat.S_IMODE(info.st_mode))}


def authentication_firmware():
    """Hash only allowlisted signed program partitions, never credential stores."""
    sizes = {'keymaster_a': 524288, 'keymaster_b': 524288,
             'tz_a': 2097152, 'tz_b': 2097152}
    result = {}
    for label, expected_size in sizes.items():
        path = Path('/dev/disk/by-partlabel') / label
        try:
            with path.open('rb', buffering=0) as stream:
                info = os.fstat(stream.fileno())
                assert stat.S_ISBLK(info.st_mode), 'expected block partition'
                sysfs = Path('/sys/dev/block') / f'{os.major(info.st_rdev)}:{os.minor(info.st_rdev)}'
                properties = dict(line.split('=', 1) for line in (sysfs / 'uevent').read_text().splitlines())
                assert properties['PARTNAME'] == label, 'partition label mismatch'
                assert int((sysfs / 'size').read_text()) * 512 == expected_size, 'partition size mismatch'
                digest = hashlib.sha256()
                remaining = expected_size
                while remaining:
                    data = stream.read(min(65536, remaining))
                    assert data, 'short partition read'
                    digest.update(data)
                    remaining -= len(data)
            result[label] = {'size': expected_size, 'sha256': digest.hexdigest()}
        except Exception as error:
            result[label] = {'error': str(error)}
    return result


def main():
    cmdline = Path('/proc/cmdline').read_text().split()
    run_id = next(x.split('=', 1)[1] for x in cmdline if x.startswith('pocketfed.liveboot='))
    assert run_id.startswith('sargo-fingerprint-lab-')
    assert 'pocketfed.root_mode=usb' in cmdline
    compatible = Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0')
    assert b'google,sargo' in compatible
    serial = next(x.split('=', 1)[1] for x in cmdline if x.startswith('androidboot.serialno='))
    assert serial == SERIAL, 'unexpected device serial'
    root_type = command('findmnt', '-n', '-o', 'FSTYPE', '/')
    assert root_type['stdout'] == 'overlay', 'inspection requires disposable root'
    report = {'schema_version': 1, 'run_id': run_id, 'serial': serial,
              'kernel': os.uname().release, 'root': root_type,
              'selinux': command('getenforce'), 'secure_calls': False}
    patterns = ('tee*', 'fpc1020', 'mmcblk*rpmb', 'mapper/vendor*')
    report['devices'] = [device(p) for pattern in patterns for p in sorted(Path('/dev').glob(pattern))]
    base = Path('/sys/block/mmcblk0/device')
    report['mmc'] = {name: (base / name).read_text().strip()
                     for name in ('type', 'raw_rpmb_size_mult', 'enhanced_rpmb_supported', 'rel_sectors')
                     if (base / name).exists()}
    rpmb = Path('/sys/bus/mmc_rpmb/devices/mmcblk0rpmb')
    report['rpmb_identity'] = {'sysfs_device': str(rpmb.resolve()),
                               'card': str(base.resolve()),
                               'dev': (rpmb / 'dev').read_text().strip()}
    units = ('blob-wrangler.service', 'qsee-supplicant.service',
             'qsee-shared-loader@cmnlib64.service',
             'qsee-app-loader@fpctzappfingerprint.service',
             'pocketfed-fingerprint-firmware.service', 'fprintd.service',
             'pocketfed-fpc-auth.socket', 'phosh-fingerprint-auth.socket')
    report['services'] = {unit: command('systemctl', 'show', unit, '-p', 'LoadState',
                                      '-p', 'ActiveState', '-p', 'MainPID') for unit in units}
    report['partitions'] = command('lsblk', '-r', '-n', '-o', 'NAME,TYPE,SIZE,RO,PARTLABEL,MOUNTPOINTS')
    report['authentication_firmware'] = authentication_firmware()
    report['vendor_builds'] = {}
    for vendor in sorted(Path('/dev/mapper').glob('vendor*')):
        number = vendor.stat().st_rdev
        identity = f'{os.major(number)}:{os.minor(number)}'
        if any(row.split()[2] == identity and 'rw' in row.split()[5].split(',')
               for row in Path('/proc/self/mountinfo').read_text().splitlines()):
            report['vendor_builds'][vendor.name] = {'error': 'writable mount'}
            continue
        result = command('/usr/bin/debugfs', '-R', 'cat /build.prop', str(vendor))
        report['vendor_builds'][vendor.name] = {
            'status': result['status'], 'diagnostic': result['stderr'],
            'fingerprint': [line.split('=', 1)[1] for line in result['stdout'].splitlines()
                            if line.startswith('ro.vendor.build.fingerprint=')]}
    if Path('/dev/mapper/vendor_b').exists():
        try:
            # The installed helper has no .py suffix.
            from importlib.machinery import SourceFileLoader
            loader = SourceFileLoader('firmware', '/usr/libexec/pocketfed-fingerprint-firmware')
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            # Separate lab inspection pins the build observed on this serial.
            # The installed production helper/manifest are not edited or run.
            module.BUILD = LAB_BUILD
            payloads, observed = module.inspect_source()
            manifest = json.loads(module.MANIFEST.read_text())
            report['firmware'] = {'result': 'lab build inspected',
                                  'same_file_bytes_as_sam_sargo': observed['files'] == manifest['files'],
                                  'files': len(payloads), 'metadata': observed}
        except Exception as error:
            report['firmware'] = {'error': str(error)}
    emit('inspection', report)


if __name__ == '__main__':
    main()
