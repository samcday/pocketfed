#!/usr/bin/python3
"""Apply diagnostic markers to a copy of the exact tested libfprint 1.6 source.

No hardware access, package installation or protocol changes. Keep this patch
outside the production RPM stack until its purpose and results are reviewed.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
COMMIT = '430e24e538ba137b6edcfe2e1b3b8cc29c66fa6a'
ARCHIVE_HASH = '60ed43e7567bd63b2fb0d5aa0df1412540fc8859dd056aa8e2cd41ad956613cd'
PATCHES = {
    '0001-fpcqsee-native-sargo-driver.patch': '0b264cc0b68c872e82805d19aa639bbf2067fe1c2150bc63b7ec715e80507a52',
    '0002-goodixqsee-include-protocol-header.patch': 'dfbee3f9561e422294f6005a2e1c87c6484e3fb124ca6adff6eb063d500d1a76',
    '0003-fpcqsee-handle-empty-database-identification.patch': '0609d7007ed86e8ea855e7c525ae4a811d026e59b9b472b9e960e44eabba4fc5',
    '0004-fpcqsee-complete-identification-state.patch': '450eac116264502f0201cf12d5837134f083b0c87e7ddf4ae2b5c0e622856528',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace(s, old, new):
    assert s.count(old) == 1, (old, s.count(old))
    return s.replace(old, new, 1)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    assert digest(args.archive) == ARCHIVE_HASH
    for name, sha in PATCHES.items():
        assert digest(REPO / 'packages/libfprint' / name) == sha, name
    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=False)
    subprocess.run(['tar', '-xzf', str(args.archive.resolve()), '-C', str(root)], check=True)
    source = root / f'libfprint-{COMMIT}'
    for name in PATCHES:
        subprocess.run(['patch', '-p1', '--fuzz=0', '--batch', '-i',
                        str(REPO / 'packages/libfprint' / name)], cwd=source, check=True,
                       stdout=subprocess.DEVNULL)
    driver = source / 'libfprint/drivers/fpcqsee'
    before = {name: (driver / name).read_text()
              for name in ('protocol.c', 'sensor.c', 'qsee-transport.c', 'fpc-qsee.c')}

    s = before['protocol.c']
    s = replace(s, '#include "protocol.h"', '#ifndef _GNU_SOURCE\n#define _GNU_SOURCE\n#endif\n#include "protocol.h"\n#include "trial-trace.h"')
    s = replace(s, '    r.transport = p->exchange(p->ctx, b, n, &r.outer);',
                '    const uint32_t target = fpc_get_le32(b), command = fpc_get_le32(b + 4);\n'
                '    fpc_trial_trace("protocol.begin", target, command, 0);\n'
                '    r.transport = p->exchange(p->ctx, b, n, &r.outer);\n'
                '    fpc_trial_trace("protocol.transport", target, command, r.transport);\n'
                '    fpc_trial_trace("protocol.outer", target, command, r.outer);')
    s = replace(s, '    if (!r.transport && !r.outer) r.command = (int32_t)fpc_get_le32(b + 8);',
                '    if (!r.transport && !r.outer) r.command = (int32_t)fpc_get_le32(b + 8);\n'
                '    fpc_trial_trace("protocol.end", target, command, r.command);')
    (driver / 'protocol.c').write_text(s)

    s = before['sensor.c']
    s = replace(s, '#include "sensor.h"', '#include "sensor.h"\n#include "trial-trace.h"')
    s = replace(s, '    sensor->fd = open(path, O_RDWR | O_NONBLOCK | O_CLOEXEC);',
                '    fpc_trial_trace("sensor.open.begin", 0, 0, 0);\n'
                '    sensor->fd = open(path, O_RDWR | O_NONBLOCK | O_CLOEXEC);\n'
                '    fpc_trial_trace("sensor.open.end", 0, 0, sensor->fd < 0 ? -errno : 0);')
    for old, phase, value in [
        ('ioctl(sensor->fd, FPC1020_IOC_RESET)', 'reset', '0'),
        ('ioctl(sensor->fd, FPC1020_IOC_SET_WAKEUP, &value)', 'wakeup', 'value')]:
        s = replace(s, f'    return {old} ? -errno : 0;',
                    f'    fpc_trial_trace("sensor.{phase}.begin", {value}, 0, 0);\n'
                    f'    int result = {old} ? -errno : 0;\n'
                    f'    fpc_trial_trace("sensor.{phase}.end", {value}, 0, result);\n'
                    '    return result;')
    (driver / 'sensor.c').write_text(s)

    s = before['qsee-transport.c']
    s = replace(s, '#include "qsee-transport.h"', '#include "qsee-transport.h"\n#include "trial-trace.h"')
    for ioctl, phase in [('TEE_IOC_OPEN_SESSION', 'session'), ('TEE_IOC_INVOKE', 'invoke')]:
        s = replace(s, f'    if (ioctl(session->fd, {ioctl}, &buffer)) {{\n        result = -errno;\n        goto out;\n    }}',
                    f'    fpc_trial_trace("tee.{phase}.begin", 0, 0, 0);\n'
                    f'    if (ioctl(session->fd, {ioctl}, &buffer)) {{\n'
                    '        result = -errno;\n'
                    f'        fpc_trial_trace("tee.{phase}.end", 0, 0, result);\n'
                    '        goto out;\n    }\n'
                    f'    fpc_trial_trace("tee.{phase}.end", 0, 0, request->ret);')
    s = replace(s, '        ioctl(session->fd, TEE_IOC_CLOSE_SESSION, &request);',
                '        fpc_trial_trace("tee.close.begin", 0, 0, 0);\n'
                '        int close_result = ioctl(session->fd, TEE_IOC_CLOSE_SESSION, &request);\n'
                '        fpc_trial_trace("tee.close.end", 0, 0, close_result ? -errno : 0);')
    (driver / 'qsee-transport.c').write_text(s)

    s = before['fpc-qsee.c']
    s = replace(s, '#include "auth-client.h"', '#include "auth-client.h"\n#include "trial-trace.h"')
    s = replace(s, '  gboolean success = FALSE;\n  if (work->operation',
                '  gboolean success = FALSE;\n'
                '  fpc_trial_trace ("worker.begin", work->operation, 0, 0);\n'
                '  if (work->operation')
    s = replace(s, 'out:\n  if (!success && work->operation == OP_OPEN)',
                'out:\n  fpc_trial_trace ("worker.end", work->operation, 0, success ? 0 : -1);\n'
                '  if (!success && work->operation == OP_OPEN)')
    (driver / 'fpc-qsee.c').write_text(s)
    shutil.copyfile(HERE / 'trace.h', driver / 'trial-trace.h')

    diff = []
    for name in (*before, 'trial-trace.h'):
        path = f'libfprint/drivers/fpcqsee/{name}'
        old = before.get(name, '')
        diff.extend(difflib.unified_diff(old.splitlines(True), (driver / name).read_text().splitlines(True),
                                        fromfile=f'a/{path}' if name in before else '/dev/null', tofile=f'b/{path}'))
    patch = root / 'trace.patch'
    patch.write_text(''.join(diff))
    manifest = {'source_commit': COMMIT, 'archive_sha256': ARCHIVE_HASH,
                'base_patch_stack': PATCHES, 'trace_patch_sha256': digest(patch),
                'prepare_script_sha256': digest(Path(__file__)),
                'changed_sources': {n: digest(driver/n) for n in (*before, 'trial-trace.h')},
                'hardware_tested': False, 'arm64_built': False,
                'purpose': 'Identify the last completed native call; no behavioral fix claimed'}
    (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'source': str(source), 'patch': str(patch), 'manifest': str(root/'manifest.json')}, indent=2))


if __name__ == '__main__':
    main()
