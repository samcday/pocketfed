#!/usr/bin/python3
"""Read exact stock QSEE firmware with debugfs; never mount or write the source.

--inspect emits hashes and structural metadata only. --extract requires the
installed, pinned manifest and writes device-local firmware; it loads no TA.
--ensure first accepts a complete, hash-verified private bundle from an earlier
extraction, so boot does not require a transient vendor mapping to survive.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import struct
import subprocess
import tempfile

SOURCE = Path('/dev/mapper/vendor_b')
DESTINATION = Path('/var/lib/firmware-updates')
MANIFEST = Path('/usr/share/pocketfed/fingerprint-trial/firmware-manifest.json')
GROUPS = {'fpctzappfingerprint': 8, 'cmnlib64': 6}
NAMES = tuple(name for base, count in GROUPS.items()
              for name in (base + '.mdt', *(f'{base}.b{i:02}' for i in range(count))))
BUILD = 'google/sargo/sargo:12/SP2A.220505.008/8782922:user/release-keys'


def read_vendor(path):
    """All paths are internal constants. debugfs opens its source read-only."""
    result = subprocess.run(['/usr/bin/debugfs', '-R', 'cat ' + path, str(SOURCE)],
                            capture_output=True, timeout=30, check=True)
    # debugfs may report filesystem errors while exiting zero. Only its normal
    # version banner is accepted; diagnostic text is never treated as payload.
    diagnostics = result.stderr.decode(errors='replace').splitlines()
    if any(line and not re.fullmatch(r'debugfs [0-9][^\r\n]*', line)
           for line in diagnostics):
        raise ValueError('debugfs refused ' + path + ': ' + '; '.join(diagnostics))
    return result.stdout


def validate_device():
    compatible = Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0')
    if b'google,sargo' not in compatible:
        raise ValueError('this firmware trial is restricted to google,sargo')


def inspect_source():
    validate_device()
    source_stat = SOURCE.stat()
    if not stat.S_ISBLK(source_stat.st_mode):
        raise ValueError('vendor_b is not an existing block device')
    device_number = f'{os.major(source_stat.st_rdev)}:{os.minor(source_stat.st_rdev)}'
    # Never request write access, even when the mapper permits it. A
    # concurrently writable mounted filesystem is not a stable extraction view.
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        if fields[2] == device_number and 'rw' in fields[5].split(','):
            raise ValueError('vendor_b has a writable mount; refusing extraction')
    build_prop = read_vendor('/build.prop').decode()
    identities = [line.split('=', 1)[1] for line in build_prop.splitlines()
                  if line.startswith('ro.vendor.build.fingerprint=')]
    if identities != [BUILD]:
        raise ValueError('unexpected vendor build; inspect and review a new manifest')
    payloads = {name: read_vendor('/firmware/' + name) for name in NAMES}
    structure = validate_structure(payloads)
    ro_path = Path('/sys/dev/block') / device_number / 'ro'
    return payloads, {
        'source': str(SOURCE), 'vendor_build': BUILD,
        'block_read_only': ro_path.read_text().strip() == '1',
        'access': 'debugfs without -w; no source mount or writes',
        'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                  for name, data in payloads.items()},
        'structure': structure,
    }


def validate_structure(payloads):
    """Validate the pinned split ELF64 layout without rebuilding any byte."""
    if set(payloads) != set(NAMES):
        raise ValueError('incomplete or unexpected firmware file set')
    structures = {}
    for base, count in GROUPS.items():
        mdt = payloads[base + '.mdt']
        if len(mdt) < 64 or mdt[:7] != b'\x7fELF\x02\x01\x01':
            raise ValueError(base + ': expected little-endian ELF64 MDT')
        machine = struct.unpack_from('<H', mdt, 18)[0]
        phoff = struct.unpack_from('<Q', mdt, 32)[0]
        phsize, phnum = struct.unpack_from('<HH', mdt, 54)
        if machine != 183 or phnum != count or phsize != 56 or phoff != 64:
            raise ValueError(base + ': unexpected AArch64 program header layout')
        if phoff + phsize * count > len(mdt):
            raise ValueError(base + ': truncated program headers')
        sizes = []
        for index in range(count):
            size = struct.unpack_from('<Q', mdt, phoff + index * phsize + 32)[0]
            segment = payloads[f'{base}.b{index:02}']
            if not size or len(segment) != size or size > 16 * 1024 * 1024:
                raise ValueError(f'{base}.b{index:02}: wrong segment length')
            sizes.append(size)
        if mdt != payloads[base + '.b00'] + payloads[base + '.b01']:
            raise ValueError(base + ': MDT is not the exact header and signature segments')
        structures[base] = {'elf_class': 64, 'machine': machine,
                            'program_headers': count, 'segment_bytes': sizes,
                            'raw_mdt_equals_b00_plus_b01': True}
    return structures


def validate_manifest(payloads, observed, manifest):
    validate_structure(payloads)
    if manifest['source'] != str(SOURCE) or manifest['vendor_build'] != BUILD:
        raise ValueError('manifest names an unexpected source or vendor build')
    if manifest['files'] != observed['files']:
        raise ValueError('stock firmware does not match the pinned hashes and lengths')


def install_payloads(payloads, destination):
    """Stage a complete immutable bundle, then expose its flat firmware names.

    Only this bundle's exact symlinks are reused. Existing unrelated paths are
    never replaced; different firmware requires an explicit new trial review.
    """
    hashes = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
    bundle_id = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    relative_bundle = Path('.sargo-fingerprint') / bundle_id
    destination.mkdir(mode=0o755, parents=True, exist_ok=True)
    if destination.is_symlink():
        raise ValueError('destination itself must not be a symlink')
    private = destination / '.sargo-fingerprint'
    private.mkdir(mode=0o755, exist_ok=True)
    if private.is_symlink():
        raise ValueError('bundle directory must not be a symlink')
    bundle = destination / relative_bundle
    for name in payloads:
        target = destination / name
        if os.path.lexists(target) and (not target.is_symlink() or
                os.readlink(target) != str(relative_bundle / name)):
            raise ValueError('refusing to replace existing firmware path: ' + str(target))
    if os.path.lexists(bundle):
        if bundle.is_symlink() or not bundle.is_dir():
            raise ValueError('invalid existing firmware bundle')
        for name, data in payloads.items():
            target = bundle / name
            if target.is_symlink() or not target.is_file() or target.read_bytes() != data:
                raise ValueError('existing bundle has changed: ' + name)
    else:
        staged = Path(tempfile.mkdtemp(prefix='.staging-', dir=private))
        try:
            for name, data in payloads.items():
                with (staged / name).open('xb') as output:
                    os.fchmod(output.fileno(), 0o600)
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
            staged.chmod(0o755)
            staged.rename(bundle)
        finally:
            if staged.exists():
                shutil.rmtree(staged)
    # Consumers require this oneshot's successful completion. An interrupted
    # first install can leave some links, but the next run repairs missing ones
    # only after revalidating the complete source and bundle.
    for name in payloads:
        target = destination / name
        if not os.path.lexists(target):
            target.symlink_to(relative_bundle / name)
    return bundle_id


def cached_payloads(destination, manifest, *, expected_uid=0):
    """Accept exact private firmware bytes, never merely the presence of links.

    No cache returns None for initial source extraction. A present but damaged
    cache fails closed. expected_uid exists for synthetic unprivileged tests;
    the command-line path always uses root ownership.
    """
    if manifest['source'] != str(SOURCE) or manifest['vendor_build'] != BUILD:
        raise ValueError('manifest names an unexpected source or vendor build')
    records = manifest['files']
    if set(records) != set(NAMES):
        raise ValueError('manifest file set is incomplete or unexpected')
    for record in records.values():
        if (type(record['bytes']) is not int or not 0 < record['bytes'] <= 16 * 1024 * 1024
                or not re.fullmatch(r'[0-9a-f]{64}', record['sha256'])):
            raise ValueError('invalid manifest length or digest')
    hashes = {name: record['sha256'] for name, record in records.items()}
    bundle_id = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    private = destination / '.sargo-fingerprint'
    bundle = private / bundle_id
    for directory in (destination, private, bundle):
        if not os.path.lexists(directory):
            return None
        s = directory.lstat()
        if (not stat.S_ISDIR(s.st_mode) or s.st_uid != expected_uid
                or s.st_mode & 0o022):
            raise ValueError('unsafe firmware cache directory: ' + str(directory))
    payloads = {}
    for name, record in records.items():
        fd = os.open(bundle / name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as source:
            s = os.fstat(source.fileno())
            if (not stat.S_ISREG(s.st_mode) or s.st_uid != expected_uid or
                    stat.S_IMODE(s.st_mode) != 0o600 or s.st_nlink != 1 or
                    s.st_size != record['bytes']):
                raise ValueError('unsafe or truncated firmware cache file: ' + name)
            data = source.read(record['bytes'] + 1)
        payloads[name] = data
    observed = {'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                          for name, data in payloads.items()}}
    validate_manifest(payloads, observed, manifest)
    return payloads


def prepare_payloads(destination, manifest, *, use_cache=False, expected_uid=0):
    payloads = cached_payloads(destination, manifest, expected_uid=expected_uid) if use_cache else None
    if payloads is not None:
        return payloads, 'verified private bundle'
    payloads, observed = inspect_source()
    validate_manifest(payloads, observed, manifest)
    return payloads, 'verified stock vendor source'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--inspect', action='store_true')
    mode.add_argument('--extract', action='store_true')
    mode.add_argument('--ensure', action='store_true')
    args = parser.parse_args()
    if args.inspect:
        payloads, observed = inspect_source()
        observed['captured_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        print(json.dumps(observed, indent=2))
        return
    if os.geteuid() != 0:
        raise ValueError('extraction requires root')
    validate_device()
    if Path('/usr/lib/firmware/updates').resolve() != DESTINATION:
        raise ValueError('firmware updates search root has an unexpected target')
    manifest = json.loads(MANIFEST.read_text())
    # A lock serializes this extractor; it does not authorize runtime firmware
    # replacement. Keep every QSEE client stopped during trial preparation.
    import fcntl
    with open('/run/pocketfed-fingerprint-firmware/extraction.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        payloads, origin = prepare_payloads(DESTINATION, manifest, use_cache=args.ensure)
        bundle_id = install_payloads(payloads, DESTINATION)
    print(json.dumps({'result': 'verified and available', 'files': len(payloads),
                      'bundle_sha256': bundle_id, 'destination': str(DESTINATION),
                      'origin': origin}))


if __name__ == '__main__':
    main()
