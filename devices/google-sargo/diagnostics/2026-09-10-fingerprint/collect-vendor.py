#!/usr/bin/env python3
"""Inspect fixed stock vendor paths through an existing mapping, read-only.

debugfs is never given -w. No mounts, mapper creation, template directories,
firmware extraction to disk, or TA execution. Binary output stays on the phone;
only hashes and selected ELF header fields are emitted.
"""
import datetime
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess

DEVICE = '/dev/mapper/vendor_b'


def debugfs(operation):
    proc = subprocess.run(['debugfs', '-R', operation, DEVICE], capture_output=True, timeout=25)
    if proc.returncode or re.search(rb'not found|not open|error|short read', proc.stderr, re.I):
        raise RuntimeError(proc.stderr.decode(errors='replace'))
    return proc.stdout


listings = {}
for directory in ('/firmware', '/bin/hw', '/bin', '/lib64', '/lib64/hw', '/etc/init'):
    listing = debugfs('ls -l ' + directory).decode()
    listings[directory] = [line for line in listing.splitlines()
                          if re.search(r'fpc|finger|cmnlib|keymaster|QSEECom|qseecomd', line, re.I)]

binaries = {}
for name in ('/firmware/fpctzappfingerprint.mbn', '/firmware/fpctzappfingerprint.mdt',
             '/bin/hw/android.hardware.biometrics.fingerprint@2.1-service.fpc',
             '/lib64/libQSEEComAPI.so', '/lib64/com.fingerprints.extension@1.0.so',
             '/lib64/hw/fingerprint.sdm670.so'):
    try:
        data = debugfs('cat ' + name)
        info = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        if data[:4] == b'\x7fELF':
            endian = '<' if data[5] == 1 else '>'
            info['elf_class'] = {1: 'ELF32', 2: 'ELF64'}.get(data[4], data[4])
            info['elf_machine'] = struct.unpack_from(endian + 'H', data, 18)[0]
            if data[4] == 2:
                shoff = struct.unpack_from(endian + 'Q', data, 40)[0]
                shentsize, shnum, shstrndx = struct.unpack_from(endian + 'HHH', data, 58)
                info['section_header_count'] = shnum
                if shnum and shentsize >= 64 and shoff + shnum * shentsize <= len(data):
                    sections = [struct.unpack_from(endian + 'IIQQQQIIQQ', data, shoff + i * shentsize)
                                for i in range(shnum)]
                    if shstrndx < shnum:
                        strings = sections[shstrndx]
                        names = data[strings[4]:strings[4] + strings[5]]
                        info['symbol_sections'] = [
                            {'name': names[s[0]:].split(b'\0', 1)[0].decode(errors='replace'),
                             'entries': s[5] // s[9] if s[9] else 0}
                            for s in sections if s[1] in (2, 11)]
                    needed = []
                    for section in sections:
                        if section[1] == 6 and section[6] < shnum:
                            strings = sections[section[6]]
                            names = data[strings[4]:strings[4] + strings[5]]
                            for offset in range(section[4], section[4] + section[5], 16):
                                tag, value = struct.unpack_from(endian + 'qQ', data, offset)
                                if tag == 1:
                                    needed.append(names[value:].split(b'\0', 1)[0].decode(errors='replace'))
                    info['needed_libraries'] = needed
                elif shnum:
                    info['section_headers_not_in_file'] = True
        binaries[name] = info
    except RuntimeError as error:
        binaries[name] = {'error': str(error)}

pins = {}
for path in Path('/sys/kernel/debug/pinctrl').glob('*/*'):
    if path.name in ('pinmux-pins', 'pinconf-pins'):
        try:
            pins[str(path)] = [line for line in path.read_text().splitlines()
                               if re.search(r'pin (121|134)\b', line)]
        except OSError as error:
            pins[str(path)] = {'error': str(error)}

print(json.dumps({
    'captured_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'vendor_mapping': DEVICE,
    'build_identity': [line for line in debugfs('cat /build.prop').decode().splitlines()
                       if re.match(r'ro\.vendor\.build\.(fingerprint|security_patch|id)=', line)],
    'listings': listings, 'binary_metadata': binaries, 'pin_state': pins,
}, indent=2))
