#!/usr/bin/python3
"""Host-only checks of the actual instrumented transport/protocol/sensor code."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--prepared', type=Path, required=True)
    args = p.parse_args()
    root = args.prepared.resolve()
    manifest = json.loads((root / 'manifest.json').read_text())
    src = root / ('libfprint-' + manifest['source_commit']) / 'libfprint/drivers/fpcqsee'
    for name, sha in manifest['changed_sources'].items():
        assert hashlib.sha256((src / name).read_bytes()).hexdigest() == sha
    tests = root / 'host-checks'
    tests.mkdir(exist_ok=False)
    cc = ['/usr/bin/gcc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror', '-I', str(src)]
    cases = {
        'protocol': ([src / 'protocol.c', REPO / 'packages/fpc-qsee/test-protocol.c'], []),
        'transport': ([src / 'qsee-transport.c', REPO / 'packages/fpc-qsee/test-transport.c'],
                      ['glob', 'globfree', 'open', 'close', 'mmap', 'munmap', 'ioctl']),
        'sensor': ([src / 'sensor.c', REPO / 'packages/fpc-qsee/test-sensor.c'],
                   ['open', 'close', 'ioctl', 'poll', 'read', 'clock_gettime']),
        'trace': ([HERE / 'test-trace.c'], ['write']),
    }
    results = []
    for name, (sources, wraps) in cases.items():
        exe = tests / name
        cmd = cc + [str(s) for s in sources] + [f'-Wl,--wrap={s}' for s in wraps] + ['-o', str(exe)]
        subprocess.run(cmd, check=True)
        result = subprocess.run([str(exe)], capture_output=True, text=True)
        (tests / (name + '.stdout')).write_text(result.stdout)
        (tests / (name + '.stderr')).write_text(result.stderr)
        result.check_returncode()
        results.append({'name': name, 'returncode': result.returncode,
                        'stdout': result.stdout.strip(), 'trace_lines': len(result.stderr.splitlines())})
    record = {'host_tests': results, 'hardware_accessed': False,
              'trace_patch_sha256': manifest['trace_patch_sha256'],
              'compiler': subprocess.check_output(['/usr/bin/gcc', '--version'], text=True).splitlines()[0],
              'arm64_build': 'pending; Podman inspection was rejected by approval review usage limit',
              'full_libfprint_driver_build': 'pending'}
    (tests / 'results.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
