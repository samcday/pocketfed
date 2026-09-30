#!/usr/bin/python3
"""Exercise measured app startup with read-only RPMB; no enrollment/identity."""
import subprocess
from lab_report import emit

PREFIX = 'pocketfed-fingerprint-lab-'
report = {'credential_operations': False, 'rpmb_writes': False, 'steps': []}


def state(unit):
    return subprocess.check_output(['systemctl', 'show', unit, '-p', 'ActiveState', '-p', 'SubState',
                                    '-p', 'MainPID', '-p', 'Result', '-p', 'NRestarts'], text=True).splitlines()


def operation(action, name):
    unit = PREFIX + name + '.service'
    step = {'action': action, 'unit': unit}
    try:
        result = subprocess.run(['systemctl', action, unit], capture_output=True, text=True, timeout=90)
        step['status'] = result.returncode
    except subprocess.TimeoutExpired:
        step['observation_timeout'] = True
    step['state'] = state(unit)
    report['steps'].append(step)
    emit('startup_' + action + '_' + name, step)
    if step.get('status') != 0:
        raise RuntimeError('service operation did not complete successfully: ' + unit)


try:
    for name in ('firmware', 'rpmb', 'cmnlib', 'fpc', 'keymaster', 'probe'):
        operation('start', name)
    # The second helper invocation must find a usable wrapped key and skip HMAC
    # recomputation. This changes no Gatekeeper credential or fingerprint DB.
    operation('restart', 'keymaster')
    for name in ('probe', 'keymaster', 'fpc', 'cmnlib', 'rpmb'):
        operation('stop', name)
    report['result'] = 'startup and clean shutdown passed'
except Exception as error:
    report['error'] = str(error)
    # No retry or forced teardown after an uncertain synchronous secure call.
finally:
    report['events'] = {}
    for name in ('firmware', 'rpmb', 'cmnlib', 'keymaster', 'fpc', 'probe'):
        text = subprocess.check_output(['journalctl', '-b', '-u', PREFIX + name + '.service',
                                        '-o', 'cat', '--no-pager'], text=True)
        prefixes = ('event=', 'wrapped_key ', 'get_hmac_parameters ', 'compute_shared_hmac ',
                    'sharing_check_length=', 'hmac_state=', 'initialization_status=',
                    'before_reset ', 'after_initialize ', 'initialize ', 'deep_sleep ',
                    'sensor open:', 'sensor reset:', 'TA attach:', '{"result":')
        report['events'][name] = [line for line in text.splitlines() if line.startswith(prefixes)]
    emit('startup_finished', report)
