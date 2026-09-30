#!/usr/bin/python3
"""Local volume-button readiness and console instructions for test-sargo."""
import fcntl
import os
from pathlib import Path
import select
import struct
import subprocess
import textwrap

UP, DOWN = 115, 114
EVENT = struct.Struct('@llHHi')
KEY_BYTES = 96


def bit(data, key):
    return bool(data[key // 8] & (1 << (key % 8)))


class Cancelled(Exception):
    pass


class ButtonSequence:
    """Require a fresh Up press/release; held keys never advance a stage."""
    def __init__(self, held=()):
        self.held = set(held)
        self.pressed = set()

    def event(self, kind, code, value):
        if kind == 0 and code == 3:  # SYN_DROPPED: never infer readiness.
            raise RuntimeError('Volume-button input overrun')
        if kind != 1 or code not in (UP, DOWN):
            return None
        if code in self.held:
            if value == 0: self.held.remove(code)
            return None
        if value == 1:
            if code == DOWN: return 'cancel'
            self.pressed.add(code)
        elif value == 0 and code in self.pressed:
            self.pressed.remove(code)
            return 'ready'
        return None


class Buttons:
    def __init__(self):
        self.devices = {}
        try:
            found = set()
            for event in sorted(Path('/sys/class/input').glob('event*')):
                device = event / 'device'
                name = (device / 'name').read_text().strip()
                # The two physical volume sources in the Sargo device tree.
                expected = {'gpio-keys': UP, 'pm8941_resin': DOWN}.get(name)
                if expected is None: continue
                assert '/devices/platform/' in str(device.resolve())
                fd = os.open('/dev/input/' + event.name, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
                self.devices[fd] = {'name': name, 'path': '/dev/input/' + event.name}
                capabilities = bytearray(KEY_BYTES)
                fcntl.ioctl(fd, 0x80004521 | (KEY_BYTES << 16), capabilities, True)  # EVIOCGBIT(EV_KEY)
                assert bit(capabilities, expected), 'Physical volume key capability missing'
                found.add(expected)
            assert found == {UP, DOWN}, 'Both physical volume buttons are required'
            self.arm()
        except BaseException:
            self.close()
            raise

    def arm(self):
        for fd, device in self.devices.items():
            # Discard presses made during the preceding stage.
            while True:
                try:
                    if not os.read(fd, EVENT.size * 64): raise RuntimeError('Volume input disconnected')
                except BlockingIOError: break
            held = bytearray(KEY_BYTES)
            fcntl.ioctl(fd, 0x80004518 | (KEY_BYTES << 16), held, True)  # EVIOCGKEY
            device['sequence'] = ButtonSequence(k for k in (UP, DOWN) if bit(held, k))

    def read(self, fd):
        try: data = os.read(fd, EVENT.size * 64)
        except BlockingIOError: return []
        if not data or len(data) % EVENT.size:
            raise RuntimeError('Volume input disconnected or malformed')
        actions = []
        for offset in range(0, len(data), EVENT.size):
            _, _, kind, code, value = EVENT.unpack_from(data, offset)
            action = self.devices[fd]['sequence'].event(kind, code, value)
            if action: actions.append(action)
        return actions

    def wait(self):
        while True:
            actions = []
            for fd in select.select(list(self.devices), [], [])[0]:
                actions.extend(self.read(fd))
            if 'cancel' in actions: raise Cancelled('Cancelled with Volume Down')
            if 'ready' in actions: return

    def close(self):
        for fd in self.devices: os.close(fd)
        self.devices.clear()


class Screen:
    def __init__(self):
        self.fd = os.open('/dev/tty1', os.O_RDWR | os.O_CLOEXEC)
        fcntl.ioctl(self.fd, 0x5606, 1)  # VT_ACTIVATE
        fcntl.ioctl(self.fd, 0x4b3a, 0)  # KDSETMODE(KD_TEXT)
        env = dict(os.environ, TERM='linux')
        self.setup = {}
        for command in (['setterm', '--blank', '0', '--powersave', 'off', '--powerdown', '0'],):
            try:
                self.setup[command[0]] = subprocess.run(command, stdin=self.fd, stdout=self.fd,
                    stderr=subprocess.DEVNULL, env=env, timeout=5).returncode
            except (OSError, subprocess.TimeoutExpired): self.setup[command[0]] = 'unavailable'
        fonts = sorted(Path('/usr/lib/kbd/consolefonts').glob('*Terminus32*'))
        if fonts:
            try:
                self.setup['setfont'] = subprocess.run(['setfont', '-C', '/dev/tty1', str(fonts[0])],
                    capture_output=True, timeout=5).returncode
            except (OSError, subprocess.TimeoutExpired): self.setup['setfont'] = 'unavailable'

    def show(self, title, *paragraphs):
        rows = ['TEST-SARGO FINGERPRINT LAB', '', title, '']
        for paragraph in paragraphs:
            rows.extend(textwrap.wrap(paragraph, width=54)); rows.append('')
        text = '\x1b[?25l\x1b[0m\x1b[2J\x1b[H' + '\r\n'.join(rows)
        data = text.encode()
        while data: data = data[os.write(self.fd, data):]

    def close(self):
        os.close(self.fd)


class Controls:
    def __init__(self, emit):
        self.emit = emit
        self.buttons = Buttons()
        try: self.screen = Screen()
        except BaseException:
            self.buttons.close(); raise
        emit('device_controls_ready', {'buttons': list({v['name'] for v in self.buttons.devices.values()}),
            'console': 'tty1', 'console_setup': self.screen.setup,
            'readiness': 'fresh Volume Up press and release; no readiness deadline',
            'cancel': 'Volume Down'})

    def wait(self, phase, instruction):
        self.buttons.arm()
        self.screen.show('Ready: ' + phase, instruction,
            'Press and release VOLUME UP when ready.',
            'VOLUME DOWN cancels. You can leave this screen waiting.',
            'Keep the USB cable connected.')
        self.emit('fingerprint_waiting_' + phase, {'phase': phase, 'instruction': instruction,
            'readiness': 'device Volume Up', 'timeout_seconds': None})
        self.buttons.wait()
        self.emit('fingerprint_ready_' + phase, {'phase': phase, 'source': 'physical Volume Up'})
        self.screen.show(phase.title() + ' in progress', instruction, 'VOLUME DOWN cancels.')

    def close(self):
        self.buttons.close(); self.screen.close()
