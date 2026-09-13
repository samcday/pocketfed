#!/usr/bin/env python3
"""Exercise the actual QSEECOM invoke body with mocked allocation/SCM boundaries.

Only synthetic data is used. No kernel module, firmware or device is loaded.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('kernel', type=Path)
parser.add_argument('--expect-per-invoke', action='store_true', help='Prove the original per-invoke allocation is rejected')
parser.add_argument('--output', type=Path)
args = parser.parse_args()
source_path = args.kernel / 'drivers/tee/qseecom/core.c'
source = source_path.read_text()
start = source.index('static int qseecom_tee_memref(')
end = source.index('/*\n * Listener services,', start)
body = source[start:end]
header = (args.kernel / 'include/linux/string.h').read_text()
start = header.index('static inline void memzero_explicit(')
end = header.index('\n}', start) + 2
clear = header[start:end]
fixture_path = Path(__file__).with_name('invoke-pool-fixture.c')
fixture = fixture_path.read_text()
assert fixture.count('/* INSERT_PRODUCTION_FUNCTIONS */') == 1
results = []
with tempfile.TemporaryDirectory(prefix='sargo-invoke-pool-') as tmp:
    tmp = Path(tmp)
    variants = [('production', body)]
    if not args.expect_per_invoke:
        line = 'memzero_explicit(b, staging_size);'
        assert body.count(line) == 1
        variants += [('missing-wipe-mutant', body.replace(line, '(void)b;')),
                     ('short-wipe-mutant', body.replace(line, 'memzero_explicit(b, need);'))]
    for label, variant in variants:
        for page_size in [4096, 65536]:
            c = tmp / f'{label}-{page_size}.c'
            exe = c.with_suffix('')
            c.write_text(fixture.replace('/* INSERT_PRODUCTION_FUNCTIONS */', clear + '\n' + variant))
            command = ['/usr/bin/gcc', '-std=gnu11', '-O2', '-flto',
                       '-Wall', '-Wextra', '-Werror', '-g',
                       '-fsanitize=undefined', '-fsanitize-undefined-trap-on-error',
                       f'-DPAGE_SIZE={page_size}', str(c), '-o', str(exe)]
            subprocess.run(command, check=True)
            run = subprocess.run([str(exe)], text=True, capture_output=True)
            expected = 91 if args.expect_per_invoke else (90 if label != 'production' else 0)
            assert run.returncode == expected, (label, page_size, run.returncode, run.stdout, run.stderr)
            if expected:
                assert run.stderr == ('PER-INVOKE pool creation or destruction\n' if expected == 91 else 'UNWIPED invoke staging at free\n')
            results.append({'variant': label, 'page_size': page_size,
                            'exit_status': run.returncode, 'expected_exit_status': expected,
                            'stdout': run.stdout.strip(), 'stderr': run.stderr.strip()})
result = {'scope': 'Synthetic production-function fixture; no hardware, DMA, concurrency or full-kernel validation',
          'source_sha256': hashlib.sha256(source_path.read_bytes()).hexdigest(),
          'production_body_sha256': hashlib.sha256(body.encode()).hexdigest(),
          'fixture_sha256': hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
          'runner_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
          'compiler': subprocess.check_output(['/usr/bin/gcc', '--version'], text=True).splitlines()[0],
          'architecture': subprocess.check_output(['uname', '-m'], text=True).strip(),
          'flags': '-O2 -flto -Wall -Wextra -Werror -fsanitize=undefined -fsanitize-undefined-trap-on-error',
          'expected_per_invoke_baseline': args.expect_per_invoke, 'passed': True, 'runs': results}
if args.output:
    args.output.write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result, indent=2))
