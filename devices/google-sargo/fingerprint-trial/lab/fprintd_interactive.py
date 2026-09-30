#!/usr/bin/python3
"""Touch-driven fprintd checks and private retention of this lab's new database."""
import base64
import hashlib
from pathlib import Path
import stat
import time
from gi.repository import Gio, GLib
from lab_report import emit


def suffix(number):
    out = ''
    while True:
        out = chr(97 + number % 26) + out
        number = number // 26 - 1
        if number < 0: return out


def retain_database(report):
    # Only this freshly enrolled lab account and the dedicated Linux FPC file.
    # These private UART records must not be copied into public result summaries.
    root = Path('/var/lib/fprint/fprintlab')
    files = [Path('/var/lib/qsee-supplicant/pocketfed/fpc-sargo-v1.db')]
    for p in root.rglob('*'):
        assert not p.is_symlink()
        if p.is_file():
            files.append(p)
    assert len(files) <= 9, 'unexpected number of lab metadata files'
    manifests = []
    index = 0
    for p in files:
        info = p.lstat()
        assert stat.S_ISREG(info.st_mode) and info.st_uid == 0 and info.st_nlink == 1
        assert 0 < info.st_size <= 256 * 1024
        content = p.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        parts = [content[i:i + 8192] for i in range(0, len(content), 8192)]
        relative = str(p.relative_to('/var/lib'))
        for sequence, part in enumerate(parts):
            emit('private_fingerprint_' + suffix(index), {'path': relative, 'sha256': digest,
                'sequence': sequence, 'count': len(parts), 'bytes': len(content),
                'private_data': base64.b64encode(part).decode()})
            index += 1
        manifests.append({'path': relative, 'bytes': len(content), 'sha256': digest})
    report['private_database_export'] = manifests
    emit('fingerprint_database_retained', {'files': len(manifests), 'private_records': index})
    assert len(files) >= 2, 'native database exported, but fprintd metadata was absent'


def run(bus, path, call, report, controls=None, *, verify_only=False):
    name = 'net.reactivated.Fprint'; iface = name + '.Device'
    progress = 0
    report['interactive'] = []

    def exercise(phase, instruction, enrollment, expected):
        nonlocal progress
        member = 'EnrollStatus' if enrollment else 'VerifyStatus'
        start = 'EnrollStart' if enrollment else 'VerifyStart'
        stop = 'EnrollStop' if enrollment else 'VerifyStop'
        events = []; terminal = None; expired = False; cancelled = False; input_error = None
        loop = GLib.MainLoop()
        def signal(connection, sender, object_path, interface, signal_name, args, *unused):
            nonlocal terminal, progress
            status, done = args.unpack()
            event = {'phase': phase, 'status': status, 'done': done}
            events.append(event)
            emit('fingerprint_progress_' + suffix(progress), event); progress += 1
            if controls:
                messages = {'enroll-stage-passed': 'Good. Lift, then touch again.',
                    'enroll-retry-scan': 'Lift and try again.',
                    'enroll-swipe-too-short': 'Cover more of the sensor.',
                    'enroll-finger-not-centered': 'Center your finger on the sensor.',
                    'enroll-remove-and-retry': 'Lift your finger, then try again.'}
                controls.screen.show(phase.title(), messages.get(status, status),
                    instruction, 'VOLUME DOWN cancels.')
            if done or (not enrollment and status in ('verify-match', 'verify-no-match')):
                terminal = status; loop.quit()
        subscription = bus.signal_subscribe(name, iface, member, path, None,
                                            Gio.DBusSignalFlags.NONE, signal)
        active = False
        watches = []
        def volume(fd, condition):
            nonlocal cancelled, input_error
            try:
                if condition & (GLib.IO_HUP | GLib.IO_ERR):
                    raise RuntimeError('Volume input disconnected')
                if 'cancel' in controls.buttons.read(fd):
                    cancelled = True; loop.quit()
            except Exception as error:
                input_error = str(error); loop.quit()
            return True
        def timeout():
            nonlocal expired
            expired = True; loop.quit(); return False
        timer = None
        try:
            if controls:
                # Waiting here has no timeout and issues no fingerprint start.
                controls.wait(phase, instruction)
                for fd in controls.buttons.devices:
                    watches.append(GLib.io_add_watch(fd, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                        lambda source, condition, fd=fd: volume(fd, condition)))
            else:
                emit('fingerprint_cue_' + phase, {'phase': phase, 'instruction': instruction,
                     'starts_in_seconds': 20})
                time.sleep(20)
            timer = GLib.timeout_add_seconds(150 if enrollment else 45, timeout)
            call(path, iface, start, GLib.Variant('(s)', ('right-index-finger' if enrollment else 'any',)))
            active = True
            if terminal is None: loop.run()
            result = {'phase': phase, 'events': events, 'terminal': terminal, 'timed_out': expired,
                      'cancelled_on_device': cancelled, 'input_error': input_error}
            report['interactive'].append(result)
            if cancelled: raise RuntimeError('Cancelled with Volume Down during ' + phase)
            if input_error: raise RuntimeError(input_error)
            assert not expired and terminal == expected, 'interactive result did not match expected phase: ' + phase
        finally:
            if timer is not None and not expired: GLib.source_remove(timer)
            for watch in watches: GLib.source_remove(watch)
            if active:
                # One explicit stop; never restart an ambiguous operation here.
                call(path, iface, stop)
            bus.signal_unsubscribe(subscription)

    call(path, iface, 'Claim', GLib.Variant('(s)', ('fprintlab',)))
    try:
        properties = call(path, 'org.freedesktop.DBus.Properties', 'GetAll', GLib.Variant('(s)', (iface,)))[0]
        report['device_properties'] = {k: v.unpack() if isinstance(v, GLib.Variant) else v
            for k, v in properties.items() if k in ('name', 'scan-type', 'num-enroll-stages', 'finger-present', 'finger-needed')}
        if not verify_only:
            exercise('enroll', 'Enroll your right index finger: repeatedly touch and lift it, varying placement slightly.', True, 'enroll-completed')
        fingers = call(path, iface, 'ListEnrolledFingers', GLib.Variant('(s)', ('fprintlab',)))[0]
        assert fingers == ['right-index-finger']
        report['enrolled_finger_count'] = 1
        if not verify_only:
            if controls: controls.screen.show('Enrollment complete', 'Saving the new test fingerprint. Keep USB connected.')
            retain_database(report)
        else:
            report['restored_enrollment_found'] = True
        exercise('match', 'Lift your finger, then touch the same finger you enrolled.', False, 'verify-match')
        exercise('nonmatch', 'Lift your finger, then touch a different finger that was not enrolled.', False, 'verify-no-match')
    finally:
        call(path, iface, 'Release')
