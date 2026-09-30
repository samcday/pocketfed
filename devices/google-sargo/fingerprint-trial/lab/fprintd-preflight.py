#!/usr/bin/python3
"""One real fprintd enrollment start/cancel on the dedicated native lab user."""
import json
import os
from pathlib import Path
import pwd
import resource
import subprocess
from gi.repository import Gio, GLib
from lab_report import emit

RUN = 'sargo-fingerprint-lab-fprintd-preflight-20260911'
PREFIX = 'pocketfed-fingerprint-lab-'
report = {'run_id': RUN, 'serial': '99NAY1AZG1', 'linux_uid': 1234,
          'gatekeeper_enrollment': False, 'steps': [], 'signals': []}
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
os.umask(0o077)


def operation(action, unit):
    r = subprocess.run(['systemctl', action, unit], capture_output=True, timeout=90)
    step = {'action': action, 'unit': unit, 'status': r.returncode,
            'state': subprocess.check_output(['systemctl', 'show', unit, '-p', 'ActiveState',
              '-p', 'SubState', '-p', 'MainPID', '-p', 'Result', '-p', 'NRestarts'], text=True).splitlines()}
    report['steps'].append(step)
    assert r.returncode == 0, 'service operation failed: ' + unit


try:
    tokens = Path('/proc/cmdline').read_text().split()
    assert 'androidboot.serialno=99NAY1AZG1' in tokens and 'pocketfed.liveboot=' + RUN in tokens
    assert 'pocketfed.root_mode=usb' in tokens
    assert pwd.getpwnam('fprintlab').pw_uid == 1234
    receipt = os.open('/run/fprintd-lab-preflight-attempt', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(receipt, b'One enrollment start/cancel; no automatic retry.\n'); os.close(receipt)
    for name in ('firmware', 'rpmb', 'cmnlib', 'fpc', 'keymaster'):
        operation('start', PREFIX + name + '.service')
    assert not list(Path('/var/lib/qsee-supplicant').iterdir()), 'initial database namespace is not empty'
    operation('start', 'pocketfed-fpc-auth.socket')
    operation('start', 'fprintd.service')
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    name = 'net.reactivated.Fprint'; iface = name + '.Device'
    def call(path, interface, method, args=None):
        result = bus.call_sync(name, path, interface, method, args, None, Gio.DBusCallFlags.NONE, 120000, None)
        report['steps'].append({'dbus': method, 'status': 'returned'})
        return result.unpack()
    paths = call('/net/reactivated/Fprint/Manager', name + '.Manager', 'GetDevices')[0]
    assert len(paths) == 1
    path = paths[0]
    call(path, iface, 'Claim', GLib.Variant('(s)', ('fprintlab',)))
    claimed = True; enrolling = False
    loop = GLib.MainLoop()
    def signal(connection, sender, object_path, interface, member, args, *unused):
        status, done = args.unpack()
        report['signals'].append({'status': status, 'done': done})
        if done: loop.quit()
    subscription = bus.signal_subscribe(name, iface, 'EnrollStatus', path, None,
                                       Gio.DBusSignalFlags.NONE, signal)
    try:
        call(path, iface, 'EnrollStart', GLib.Variant('(s)', ('right-index-finger',)))
        enrolling = True
        GLib.timeout_add_seconds(6, lambda: (loop.quit(), False)[1])
        loop.run()
        completed = [s for s in report['signals'] if s['done']]
        report['unexpected_completed_enrollment'] = any(s['status'] == 'enroll-completed' for s in completed)
        enrolling = False
        call(path, iface, 'EnrollStop')
        assert not completed, 'enrollment finished before deliberate cancellation'
        report['cancellation'] = 'EnrollStop returned successfully'
    finally:
        # Do not start another enrollment, even when the first failed.
        if enrolling:
            call(path, iface, 'EnrollStop')
        if claimed:
            call(path, iface, 'Release'); claimed = False
        bus.signal_unsubscribe(subscription)
    # A fresh Claim must reload the persisted empty database after cancellation.
    call(path, iface, 'Claim', GLib.Variant('(s)', ('fprintlab',)))
    try:
        fingers = call(path, iface, 'ListEnrolledFingers', GLib.Variant('(s)', ('fprintlab',)))[0]
        assert not fingers
    except GLib.Error as error:
        assert Gio.DBusError.get_remote_error(error) == 'net.reactivated.Fprint.Error.NoEnrolledPrints'
    report['enrolled_finger_count'] = 0
    call(path, iface, 'Release')
    db = Path('/var/lib/qsee-supplicant/pocketfed/fpc-sargo-v1.db')
    report['database_bytes'] = db.stat().st_size
    import hashlib
    metadata = json.loads((Path(__file__).parent / 'authorization.json').read_text())
    assert hashlib.sha256(Path('/var/lib/pocketfed-fpc-auth/uid-1234.credential').read_bytes()).hexdigest() == metadata['credential_sha256']
    report['credential_unchanged'] = True
    for unit in ('fprintd.service', 'pocketfed-fpc-auth.socket', 'pocketfed-fpc-auth.service'):
        operation('stop', unit)
    for name in ('keymaster', 'fpc', 'cmnlib', 'rpmb'):
        operation('stop', PREFIX + name + '.service')
    report['result'] = 'fprintd enrollment start/cancel and database reopen passed'
except Exception as error:
    report['error'] = str(error)
finally:
    report['events'] = {}
    for unit in (PREFIX + 'rpmb.service', 'pocketfed-fpc-auth.service', 'fprintd.service'):
        log = subprocess.check_output(['journalctl', '-b', '-u', unit, '-o', 'cat', '--no-pager'], text=True)
        # These services log status/errors, not wire messages or template bytes.
        report['events'][unit] = log.splitlines()
    emit('fprintd_preflight_finished', report)
