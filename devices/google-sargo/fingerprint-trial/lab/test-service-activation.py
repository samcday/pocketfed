#!/usr/bin/python3
"""Execute the generated activation fragment against a masked-unit model."""
import ast
from pathlib import Path, PurePosixPath
import sys

tree = ast.parse(Path(sys.argv[1]).read_text())
body = next(node.body for node in tree.body if isinstance(node, ast.Try))
begin = next(i for i, node in enumerate(body) if isinstance(node, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == 'unit_names' for t in node.targets))
end = next(i for i, node in enumerate(body[begin:], begin) if isinstance(node, ast.For)
           and isinstance(node.iter, ast.Tuple)
           and [x.value for x in node.iter.elts] == ['firmware', 'rpmb', 'cmnlib', 'fpc', 'keymaster'])
fragment = compile(ast.Module(body=body[begin:end + 1], type_ignores=[]), '<activation>', 'exec')

for leave_masked in (False, True):
    state = {'guard': False, 'ready': False, 'masked': True, 'started': []}

    class FakePath(PurePosixPath):
        def touch(self, *, exist_ok):
            assert str(self) == '/run/pocketfed-fingerprint-lab/normal-chain-ready'
            assert not exist_ok and state['guard'] and not state['masked']
            state['ready'] = True

    class Systemctl:
        def run(self, args, **kwargs):
            if args[0] == '/usr/bin/python3':
                assert args[1] == '/lab/guard-device.py'
                assert not state['ready'] and not state['started']
                state['guard'] = True
            elif args[:2] == ['systemctl', 'unmask']:
                assert state['guard'] and not state['ready']
                assert 'qsee-supplicant.service' in args
                state['masked'] = leave_masked
            else:
                assert args == ['systemctl', 'daemon-reload']

        def check_output(self, args, **kwargs):
            assert args[:2] == ['systemctl', 'show']
            return 'masked\n' if state['masked'] and args[2] == 'qsee-supplicant.service' else 'loaded\n'

    def operation(action, unit):
        assert action == 'start' and state['ready'] and not state['masked']
        state['started'].append(unit)

    try:
        exec(fragment, {'Path': FakePath, 'subprocess': Systemctl(),
                        '__file__': '/lab/controller.py', 'operation': operation})
    except AssertionError:
        assert leave_masked and not state['ready'] and not state['started']
    else:
        assert not leave_masked and len(state['started']) == 5

print('PASS identity/inactivity guard before unmask; effective load-state check before readiness/start; retained mask stops activation')
