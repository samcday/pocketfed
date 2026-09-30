#!/usr/bin/python3
"""Check that trace formatting cannot leak instruction addresses or payloads."""
import importlib.util
import json
from pathlib import Path
import contextlib
import io
import sys
import tempfile
from unittest.mock import patch

path = Path(__file__).with_name('trace-init.py')
spec = importlib.util.spec_from_file_location('fpc_kernel_trace', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
parse = module.metadata
entry = ' initialize-once-8576 [001] d..2. 4213.492102: app_enter: (qcom_scm_qseecom_app_send+0x0/0x40)'
assert parse(entry) == {'pid': 8576, 'cpu': 1, 'time': '4213.492102', 'event': 'app_enter'}
exit_line = ' initialize-once-8576 [007] d..2. 4213.492125: app_exit: (ffff812345678abc <- ffff812345670000) status=-5'
result = parse(exit_line)
assert result['status'] == -5
assert 'ffff' not in json.dumps(result) and 'initialize-once' not in json.dumps(result)
assert parse(' python3-1 [000] ..... 1.000000: tracing_mark_write: FPC_TRACE_READY') == {'ready': True}
assert parse(' python3-1 [000] ..... 1.000000: other_event: payload=secret') is None
assert parse('corrupt trace line') is None
assert parse(' python3-1 [000] ..... 1.000000: quirk_exit: (private address)')['event'] == 'quirk_exit'
try:
    parse(' python3-1 [000] ..... 1.000000: app_exit: (address) status=wrong')
    raise AssertionError('malformed status accepted')
except ValueError:
    pass
assert module.EVENTS['quirk_exit'][2] == ''
assert all(fetch in ('', ' status=$retval:s32') for _, _, fetch in module.EVENTS.values())
events = [{'event': name, 'status': 0} for name in
          ['app_enter', 'scm_enter', 'quirk_enter', 'quirk_exit', 'scm_exit', 'app_exit'] * 2]
assert module.complete_trace([{'ready': True}] + events)
assert not module.complete_trace(events[1:])
assert not module.complete_trace(events + events)
bad = [dict(e) for e in events]
bad[4]['status'] = -1
assert not module.complete_trace(bad)
# Regression: changing snapshots under the same report name conflict in the
# checksummed collector. Exercise the actual distinct-name producer interface.
sys.path.insert(0, str(path.parent.parent))
import lab_report
with tempfile.TemporaryDirectory() as directory:
    output = io.StringIO()
    with patch.object(lab_report, 'Path', lambda _: Path(directory)), contextlib.redirect_stdout(output):
        for name in ('firmware', 'rpmb'):
            lab_report.emit(module.startup_report_name(name), {'unit': name, 'status': 0})
    reports = lab_report.collect(output.getvalue().encode())
    assert set(reports) == {'kernel_trace_startup_firmware', 'kernel_trace_startup_rpmb'}
print('Trace metadata, boundary ordering and progress-report regression checks passed')
