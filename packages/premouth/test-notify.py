#!/usr/bin/python3
"""Acceptance probe for premouth READY notifications and residual CLI errors.

The probe runs against a synthetic, empty device tree with no display
hardware and no service manager, suitable for an RPM %check section.  Four
cases are exercised over a real Unix datagram NOTIFY_SOCKET:

* missing-dt        - device tree directory does not exist
* malformed-dt      - framebuffer node with malformed properties
* socket-setup-error - handoff socket parent is not a directory
* invalid-cli       - unknown command line option

The first three cases must exit 1, send READY=1 and remove any handoff
socket; the invalid invocation must exit 2 without READY=1.  Each
subprocess is bounded by a five second timeout.

Usage: python3 test-notify.py [PATH-TO-PREMOUTH]
"""

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

TIMEOUT_SECONDS = 5
CASES = ('missing-dt', 'malformed-dt', 'socket-setup-error', 'invalid-cli')


def binary_from_argv(argv):
    if len(argv) > 1:
        return Path(argv[1])
    for variable in ('PREMOUTH_BINARY', 'PREMOUTH'):
        value = os.environ.get(variable)
        if value:
            return Path(value)
    found = shutil.which('premouth')
    if found:
        return Path(found)
    sys.exit('error: pass the premouth binary path as the first argument')


def case_arguments(binary, case, work):
    device_tree = work / 'dt'
    handoff = work / 'handoff.sock'
    if case == 'malformed-dt':
        framebuffer = device_tree / 'chosen' / 'framebuffer@9c000000'
        framebuffer.mkdir(parents=True)
        (framebuffer / 'compatible').write_bytes(b'simple-framebuffer\0')
    elif case == 'socket-setup-error':
        (work / 'not-a-directory').write_text('ordinary file\n')
        handoff = work / 'not-a-directory' / 'handoff.sock'
    if case == 'invalid-cli':
        return [str(binary), 'run', '--unknown-option'], handoff
    return [
        str(binary),
        'run',
        '--dt-base',
        str(device_tree),
        '--socket',
        str(handoff),
    ], handoff


def run_case(binary, root, case):
    work = root / case
    work.mkdir()
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as notify:
        notify.bind(str(work / 'notify'))
        notify.settimeout(1.0)
        args, handoff = case_arguments(binary, case, work)
        environment = os.environ.copy()
        environment['NOTIFY_SOCKET'] = str(work / 'notify')
        run = subprocess.run(
            args,
            env=environment,
            text=True,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
        )
        try:
            message = notify.recv(4096).decode('utf-8', 'replace')
        except socket.timeout:
            message = ''
    expected_code = 2 if case == 'invalid-cli' else 1
    ready = 'READY=1' in message.splitlines()
    problems = []
    if run.returncode != expected_code:
        problems.append(f'exit status {run.returncode}, expected {expected_code}')
    if ready != (case != 'invalid-cli'):
        problems.append(f'READY=1 {"present" if ready else "absent"} in {message!r}')
    if handoff.exists():
        problems.append('handoff socket survived terminal return')
    if problems:
        print(f'FAIL {case}: ' + '; '.join(problems), file=sys.stderr)
        if run.stderr.strip():
            print(run.stderr.strip(), file=sys.stderr)
        return False
    print(f'PASS {case}: exit={run.returncode} ready={ready} handoff_removed=true')
    return True


def main(argv):
    binary = binary_from_argv(argv)
    if not binary.exists():
        sys.exit(f'error: premouth binary not found: {binary}')
    failed = 0
    with tempfile.TemporaryDirectory(prefix='premouth-notify-') as directory:
        root = Path(directory)
        for case in CASES:
            try:
                passed = run_case(binary, root, case)
            except subprocess.TimeoutExpired:
                print(
                    f'FAIL {case}: exceeded {TIMEOUT_SECONDS}s subprocess timeout',
                    file=sys.stderr,
                )
                passed = False
            failed += not passed
    if failed:
        print(f'{failed} of {len(CASES)} cases failed', file=sys.stderr)
        return 1
    print(f'{len(CASES)} of {len(CASES)} cases passed')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
