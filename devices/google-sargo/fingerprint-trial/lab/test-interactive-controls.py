#!/usr/bin/python3
"""Real GLib loop checks: readiness, phase boundaries and physical cancellation."""
import os
from gi.repository import GLib
import fprintd_interactive as client
from device_controls import Buttons, ButtonSequence, Cancelled, DOWN, EVENT

client.emit = lambda *args: None
client.retain_database = lambda report: report.update(private_export_mock=True)


class Bus:
    def signal_subscribe(self, *args):
        self.callback = args[-1]
        self.member = args[2]
        return 1
    def signal_unsubscribe(self, subscription): self.callback = None


class Screen:
    def show(self, *args): pass


def check(mode, verify_only=False):
    read_fd, write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)
    buttons = Buttons.__new__(Buttons)
    buttons.devices = {read_fd: {'sequence': ButtonSequence()}}
    class Controls:
        screen = Screen()
        def __init__(self):
            self.buttons = buttons; self.phases = []; self.ready = False
        def wait(self, phase, instruction):
            self.phases.append(phase)
            assert not self.ready, 'A preceding readiness press leaked to the next stage'
            if mode == 'cancel-wait': raise Cancelled('test cancellation while waiting')
            self.ready = True
    controls = Controls(); bus = Bus(); calls = []; report = {}; starts = 0
    real_timer = GLib.timeout_add_seconds
    def timer(seconds, callback):
        assert controls.ready, 'Scan timeout started before device readiness'
        return real_timer(seconds, callback)
    GLib.timeout_add_seconds = timer
    def call(path, interface, method, args=None):
        nonlocal starts
        calls.append(method)
        if method == 'GetAll': return ({},)
        if method == 'ListEnrolledFingers': return (['right-index-finger'],)
        if method in ('EnrollStart', 'VerifyStart'):
            assert controls.ready, 'Fingerprint operation started before readiness'
            controls.ready = False; starts += 1
            if mode == 'cancel-active':
                def cancel():
                    os.write(write_fd, EVENT.pack(0, 0, 1, DOWN, 1)); return False
                GLib.idle_add(cancel)
            else:
                statuses = ('verify-match', 'verify-no-match') if verify_only else ('enroll-completed', 'verify-match', 'verify-no-match')
                status = statuses[starts - 1]
                def complete():
                    bus.callback(None, None, None, None, bus.member, GLib.Variant('(sb)', (status, True)))
                    return False
                GLib.idle_add(complete)
        return ()
    try:
        try: client.run(bus, '/device', call, report, controls, verify_only=verify_only)
        except (Cancelled, RuntimeError):
            assert mode != 'success'
        else: assert mode == 'success'
        assert calls[-1] == 'Release'
        if mode == 'success':
            assert controls.phases == (['match', 'nonmatch'] if verify_only else ['enroll', 'match', 'nonmatch'])
            assert starts == (2 if verify_only else 3) and calls.count('VerifyStop') == 2
            if verify_only:
                assert not any(c.startswith('Enroll') for c in calls)
                assert report['restored_enrollment_found'] and 'private_export_mock' not in report
            else:
                assert calls.count('EnrollStop') == 1
        elif mode == 'cancel-wait':
            assert starts == 0 and not any(c.endswith('Stop') for c in calls)
        else:
            assert starts == 1 and calls.count('VerifyStop' if verify_only else 'EnrollStop') == 1
            assert report['interactive'][0]['cancelled_on_device']
    finally:
        GLib.timeout_add_seconds = real_timer
        buttons.close(); os.close(write_fd)


for verify_only in (False, True):
    for mode in ('success', 'cancel-wait', 'cancel-active'): check(mode, verify_only)
print('PASS readiness and cancellation for enrollment and restored verification; no enrollment or export in verify-only mode')
