#!/usr/bin/python3
"""Create a read-only vendor_b mapping from revalidated slot-1 LP metadata.

Disposable liveboot only. The physical partitions are opened read-only, the
logical-partition geometry and metadata checksums are verified, the vendor_b
extent must equal the extent observed on daily sam-sargo on 11 September 2026,
the ext4 superblock at that extent must be valid, and the resulting mapping
is a read-only device-mapper table. No partition, metadata or filesystem byte
is written. The mapping exists so the unchanged firmware helper can read the
pinned vendor build through debugfs; firmware bytes never appear in output.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import subprocess
import sys

SERIAL = '994AY18RSD'
SUPER = Path('/dev/disk/by-partlabel/system_b')
SUPER_NAME = 'system_b'
SLOT = 1  # slot-b metadata lives in slot 1 of the retrofit super partition system_b
NAME = 'vendor_b'
EXPECTED = {'start_sector': 1759464, 'num_sectors': 991624, 'source': SUPER_NAME}
BUILD = 'google/sargo/sargo:12/SP2A.220505.008/8782922:user/release-keys'
RECEIPT = Path('/run/pocketfed-fpc-pool-vendor-b/receipt.json')
GEOMETRY_MAGIC = 0x616c4467
HEADER_MAGIC = 0x414c5030
RESERVED_BYTES = 4096
GEOMETRY_SIZE = 4096
BLKGETSIZE64 = 0x80081272


class Refused(Exception):
    pass


def out(*args, timeout=30):
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def pread(fd, offset, length):
    data = os.pread(fd, length, offset)
    if len(data) != length:
        raise Refused(f'short read at {offset}: {len(data)} of {length}')
    return data


def cstring(raw):
    return raw.split(b'\0', 1)[0].decode('ascii', errors='replace')


def parse_geometry(blob):
    magic, struct_size = struct.unpack_from('<II', blob, 0)
    if magic != GEOMETRY_MAGIC:
        raise Refused('geometry magic mismatch')
    if not 52 <= struct_size <= GEOMETRY_SIZE:
        raise Refused('geometry struct size out of range')
    zeroed = blob[:8] + bytes(32) + blob[40:struct_size]
    if hashlib.sha256(zeroed).digest() != blob[8:40]:
        raise Refused('geometry checksum mismatch')
    max_size, slot_count, block_size = struct.unpack_from('<III', blob, 40)
    if not max_size or max_size % 512 or slot_count < 1 or not block_size:
        raise Refused('geometry values out of range')
    return {'metadata_max_size': max_size, 'metadata_slot_count': slot_count,
            'logical_block_size': block_size}


def parse_metadata(blob):
    magic, major, minor, header_size = struct.unpack_from('<IHHI', blob, 0)
    if magic != HEADER_MAGIC:
        raise Refused('metadata header magic mismatch')
    if not 128 <= header_size <= len(blob):
        raise Refused('metadata header size out of range')
    tables_size, = struct.unpack_from('<I', blob, 44)
    if header_size + tables_size > len(blob):
        raise Refused('metadata tables exceed the slot')
    zeroed = blob[:12] + bytes(32) + blob[44:header_size]
    if hashlib.sha256(zeroed).digest() != blob[12:44]:
        raise Refused('metadata header checksum mismatch')
    tables = blob[header_size:header_size + tables_size]
    if hashlib.sha256(tables).digest() != blob[48:80]:
        raise Refused('metadata tables checksum mismatch')
    descriptors = {}
    for index, table in enumerate(('partitions', 'extents', 'groups', 'block_devices')):
        offset, count, entry = struct.unpack_from('<III', blob, 80 + index * 12)
        if entry and offset + count * entry > tables_size:
            raise Refused(f'{table} table exceeds the tables area')
        descriptors[table] = (offset, count, entry)

    def rows(table, minimum):
        offset, count, entry = descriptors[table]
        if count and entry < minimum:
            raise Refused(f'{table} entries are too small')
        return [tables[offset + i * entry:offset + (i + 1) * entry] for i in range(count)]

    extents = [dict(zip(('num_sectors', 'target_type', 'target_data', 'target_source'),
                        struct.unpack_from('<QIQI', row, 0))) for row in rows('extents', 24)]
    block_devices = []
    for row in rows('block_devices', 64):
        first, alignment, alignment_offset, size = struct.unpack_from('<QIIQ', row, 0)
        block_devices.append({'first_logical_sector': first, 'alignment': alignment,
                              'alignment_offset': alignment_offset, 'size': size,
                              'partition_name': cstring(row[24:60]),
                              'flags': struct.unpack_from('<I', row, 60)[0]})
    partitions = []
    for row in rows('partitions', 52):
        attributes, first_extent, num_extents, group = struct.unpack_from('<IIII', row, 36)
        if first_extent + num_extents > len(extents):
            raise Refused('partition extents out of range')
        partitions.append({'name': cstring(row[:36]), 'attributes': attributes,
                           'group_index': group,
                           'extents': extents[first_extent:first_extent + num_extents]})
    return {'version': f'{major}.{minor}', 'header_size': header_size,
            'tables_size': tables_size, 'raw_sha256': hashlib.sha256(blob[:header_size + tables_size]).hexdigest(),
            'partitions': partitions, 'block_devices': block_devices}


def resolve_extent(metadata):
    matches = [p for p in metadata['partitions'] if p['name'] == NAME]
    if len(matches) != 1:
        raise Refused(f'{NAME} appears {len(matches)} times in the metadata')
    extents = matches[0]['extents']
    if len(extents) != 1:
        raise Refused(f'{NAME} has {len(extents)} extents; exactly one linear extent is required')
    extent = extents[0]
    if extent['target_type'] != 0:
        raise Refused(f'{NAME} extent is not linear')
    if extent['target_source'] >= len(metadata['block_devices']):
        raise Refused(f'{NAME} extent references an unknown block device')
    device = metadata['block_devices'][extent['target_source']]
    return {'start_sector': extent['target_data'], 'num_sectors': extent['num_sectors'],
            'source': device['partition_name'], 'source_size_bytes': device['size'],
            'attributes': matches[0]['attributes']}


def lpdump_extent():
    """Advisory cross-check with the image's own lpdump; never authoritative."""
    for argv in ((['lpdump', '-s', str(SLOT), str(SUPER)]), ['lpdump', str(SUPER)]):
        try:
            result = out(*argv)
        except (OSError, subprocess.TimeoutExpired) as error:
            return {'argv': argv, 'error': repr(error)}
        if result.returncode:
            continue
        text = result.stdout
        if f'Slot {SLOT}:' in text and 'Slot 0:' in text:
            text = text.split(f'Slot {SLOT}:', 1)[1]
        match = re.search(r'Name: ' + NAME + r'\n(.*?)(?=\n-{5,}|\Z)', text, re.S)
        if not match:
            return {'argv': argv, 'error': NAME + ' not listed', 'stdout': text[:4000]}
        lines = re.findall(r'^\s*(\d+) \.\. (\d+) linear (\S+) (\d+)\s*$', match.group(1), re.M)
        return {'argv': argv, 'stdout': text[:4000],
                'extents': [{'start_sector': int(d), 'num_sectors': int(b) - int(a) + 1, 'source': c}
                            for a, b, c, d in lines]}
    return {'argv': argv, 'error': 'lpdump exited nonzero', 'stderr': result.stderr[:2000]}


def main():
    os.umask(0o077)
    if os.geteuid():
        raise Refused('root is required')
    cmdline = Path('/proc/cmdline').read_text().split()
    if f'androidboot.serialno={SERIAL}' not in cmdline:
        raise Refused('not the daily sam-sargo serial')
    if 'pocketfed.root_mode=usb' not in cmdline or not any(x.startswith('pocketfed.liveboot=') for x in cmdline):
        raise Refused('not a disposable liveboot')
    if out('findmnt', '-n', '-o', 'FSTYPE', '/').stdout.strip() != 'overlay':
        raise Refused('root is not the disposable overlay')
    if b'google,sargo' not in Path('/sys/firmware/devicetree/base/compatible').read_bytes().split(b'\0'):
        raise Refused('not google,sargo')
    mapper = Path('/dev/mapper') / NAME
    if os.path.lexists(mapper):
        raise Refused(f'{mapper} already exists')
    if out('dmsetup', 'info', NAME).returncode == 0:
        raise Refused(f'device-mapper already knows {NAME}')
    st = SUPER.stat()
    if not stat.S_ISBLK(st.st_mode):
        raise Refused(f'{SUPER} is not a block device')
    super_devno = f'{os.major(st.st_rdev)}:{os.minor(st.st_rdev)}'
    for line in Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        if fields[2] == super_devno:
            raise Refused('the physical slot-b system partition is mounted; refusing')
    receipt = {'serial': SERIAL, 'super': str(SUPER), 'super_realpath': os.path.realpath(SUPER),
               'super_devno': super_devno, 'slot': SLOT, 'expected': EXPECTED, 'writes_performed': False}
    fd = os.open(SUPER, os.O_RDONLY | os.O_CLOEXEC)
    try:
        size = bytearray(8)
        fcntl.ioctl(fd, BLKGETSIZE64, size)
        receipt['super_size_bytes'] = struct.unpack('<Q', size)[0]
        geometry = parse_geometry(pread(fd, RESERVED_BYTES, GEOMETRY_SIZE))
        backup_geometry = parse_geometry(pread(fd, RESERVED_BYTES + GEOMETRY_SIZE, GEOMETRY_SIZE))
        if geometry != backup_geometry:
            raise Refused('primary and backup geometry disagree')
        receipt['geometry'] = geometry
        if SLOT >= geometry['metadata_slot_count']:
            raise Refused('metadata slot count does not include the slot-b metadata')
        base = RESERVED_BYTES + 2 * GEOMETRY_SIZE
        primary_offset = base + SLOT * geometry['metadata_max_size']
        backup_offset = base + (geometry['metadata_slot_count'] + SLOT) * geometry['metadata_max_size']
        primary = parse_metadata(pread(fd, primary_offset, geometry['metadata_max_size']))
        backup = parse_metadata(pread(fd, backup_offset, geometry['metadata_max_size']))
        receipt['metadata'] = {
            'primary_offset': primary_offset, 'backup_offset': backup_offset,
            'version': primary['version'], 'primary_sha256': primary['raw_sha256'],
            'backup_sha256': backup['raw_sha256'],
            'partitions': [{'name': p['name'], 'extents': p['extents']} for p in primary['partitions']],
            'block_devices': [{'partition_name': d['partition_name'], 'size': d['size'],
                               'first_logical_sector': d['first_logical_sector']}
                              for d in primary['block_devices']]}
        if (primary['partitions'], primary['block_devices']) != (backup['partitions'], backup['block_devices']):
            raise Refused('primary and backup slot-b metadata disagree')
        observed = resolve_extent(primary)
        receipt['observed'] = observed
        for key, value in EXPECTED.items():
            if observed[key] != value:
                raise Refused(f'{NAME} {key} is {observed[key]}, expected {value}; geometry changed, stopping')
        end_bytes = (observed['start_sector'] + observed['num_sectors']) * 512
        if end_bytes > observed['source_size_bytes'] or end_bytes > receipt['super_size_bytes']:
            raise Refused(f'{NAME} extent exceeds its source partition')
        superblock = pread(fd, observed['start_sector'] * 512 + 1024, 1024)
        if superblock[56:58] != b'\x53\xef':
            raise Refused('no ext4 superblock at the declared vendor_b extent')
        blocks = struct.unpack_from('<I', superblock, 4)[0]
        incompat = struct.unpack_from('<I', superblock, 0x60)[0]
        if incompat & 0x80:
            blocks |= struct.unpack_from('<I', superblock, 0x150)[0] << 32
        block_size = 1024 << struct.unpack_from('<I', superblock, 24)[0]
        fs_bytes = blocks * block_size
        receipt['ext4'] = {'blocks': blocks, 'block_size': block_size, 'bytes': fs_bytes,
                           'uuid': superblock[104:120].hex(), 'label': cstring(superblock[120:136]),
                           'feature_incompat': incompat,
                           'state': struct.unpack_from('<H', superblock, 58)[0]}
        if fs_bytes > observed['num_sectors'] * 512:
            raise Refused('ext4 size exceeds the declared extent')
    finally:
        os.close(fd)
    cross = lpdump_extent()
    receipt['lpdump'] = cross
    if 'extents' in cross:
        expected_view = [{'start_sector': observed['start_sector'], 'num_sectors': observed['num_sectors'],
                          'source': observed['source']}]
        if cross['extents'] != expected_view:
            raise Refused('lpdump disagrees with the parsed slot-b metadata')
        receipt['lpdump_agrees'] = True
    table = f"0 {observed['num_sectors']} linear {SUPER} {observed['start_sector']}"
    created = out('dmsetup', 'create', NAME, '--readonly', '--table', table)
    if created.returncode:
        raise Refused('dmsetup create failed: ' + created.stderr.strip())
    receipt['dm_table_requested'] = table
    try:
        applied = out('dmsetup', 'table', NAME).stdout.strip()
        receipt['dm_table_applied'] = applied
        if applied != f"0 {observed['num_sectors']} linear {super_devno} {observed['start_sector']}":
            raise Refused('applied device-mapper table differs from the request')
        mst = mapper.stat()
        if not stat.S_ISBLK(mst.st_mode):
            raise Refused(f'{mapper} is not a block device')
        mapper_devno = f'{os.major(mst.st_rdev)}:{os.minor(mst.st_rdev)}'
        ro = Path('/sys/dev/block') / mapper_devno / 'ro'
        receipt['mapper_devno'] = mapper_devno
        receipt['block_read_only'] = ro.read_text().strip() == '1'
        if not receipt['block_read_only']:
            raise Refused('mapping is not read-only')
        props = out('debugfs', '-R', 'cat /build.prop', str(mapper), timeout=60)
        fingerprints = [line.split('=', 1)[1] for line in props.stdout.splitlines()
                        if line.startswith('ro.vendor.build.fingerprint=')]
        receipt['vendor_build'] = fingerprints
        if props.returncode or fingerprints != [BUILD]:
            raise Refused('mapped filesystem is not the pinned daily vendor build')
    except BaseException:
        out('dmsetup', 'remove', NAME)
        receipt['mapping_removed_after_failure'] = True
        raise
    receipt['result'] = 'read-only vendor_b mapping verified'
    RECEIPT.parent.mkdir(mode=0o700, exist_ok=True)
    with RECEIPT.open('x') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    summary = {key: receipt[key] for key in ('observed', 'ext4', 'dm_table_applied', 'block_read_only',
                                              'vendor_build', 'result')}
    summary['lpdump_agrees'] = receipt.get('lpdump_agrees', False)
    summary['metadata_version'] = receipt['metadata']['version']
    print('FPC_POOL_VENDOR_B_RESULT ' + json.dumps(summary), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Refused as error:
        print('FPC_POOL_VENDOR_B_REFUSED ' + json.dumps({'reason': str(error)}), flush=True)
        sys.exit(1)
