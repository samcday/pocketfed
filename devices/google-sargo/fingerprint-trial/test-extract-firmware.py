#!/usr/bin/python3
"""Synthetic split images only. No phone, vendor bytes, mounts, or TAs."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('firmware', Path(__file__).with_name('extract-firmware.py'))
firmware = importlib.util.module_from_spec(spec)
spec.loader.exec_module(firmware)


def synthetic_images():
    files = {}
    for base, count in firmware.GROUPS.items():
        header = bytearray(64 + count * 56)
        header[:7] = b'\x7fELF\x02\x01\x01'
        struct.pack_into('<H', header, 18, 183)
        struct.pack_into('<Q', header, 32, 64)
        struct.pack_into('<HH', header, 54, 56, count)
        segments = [header, b'synthetic signature'] + [bytes([i]) * (i + 3) for i in range(2, count)]
        for i, data in enumerate(segments):
            struct.pack_into('<Q', header, 64 + i * 56 + 32, len(data))
        for i, data in enumerate(segments):
            files[f'{base}.b{i:02}'] = bytes(data)
        files[base + '.mdt'] = bytes(header) + segments[1]
    return files


def synthetic_manifest(files):
    return {'source': str(firmware.SOURCE), 'vendor_build': firmware.BUILD,
            'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                      for name, data in files.items()}}


class Extraction(unittest.TestCase):
    def test_cached_boot_needs_no_vendor_mapping_and_repairs_missing_links(self):
        files = synthetic_images()
        manifest = synthetic_manifest(files)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = firmware.install_payloads(files, root)
            (root / 'cmnlib64.mdt').unlink()
            with mock.patch.object(firmware, 'inspect_source', side_effect=AssertionError('vendor unavailable')):
                cached, origin = firmware.prepare_payloads(root, manifest, use_cache=True, expected_uid=os.getuid())
                self.assertEqual(cached, files)
                self.assertEqual(origin, 'verified private bundle')
                self.assertEqual(firmware.install_payloads(cached, root), bundle)
            self.assertEqual((root / 'cmnlib64.mdt').read_bytes(), files['cmnlib64.mdt'])

    def test_first_boot_still_checks_stock_source(self):
        files = synthetic_images()
        manifest = synthetic_manifest(files)
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(firmware, 'inspect_source', return_value=(files, manifest)) as inspect:
                cached, origin = firmware.prepare_payloads(Path(tmp), manifest, use_cache=True, expected_uid=os.getuid())
                self.assertEqual(cached, files)
                self.assertEqual(origin, 'verified stock vendor source')
                inspect.assert_called_once_with()

    def test_damaged_cache_never_falls_back_to_overwriting(self):
        files = synthetic_images()
        manifest = synthetic_manifest(files)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = firmware.install_payloads(files, root)
            target = root / '.sargo-fingerprint' / bundle / 'cmnlib64.b02'
            original = target.read_bytes()
            target.write_bytes(b'x' * len(original))
            with mock.patch.object(firmware, 'inspect_source') as inspect:
                with self.assertRaises(ValueError):
                    firmware.prepare_payloads(root, manifest, use_cache=True, expected_uid=os.getuid())
                inspect.assert_not_called()
            self.assertEqual(target.read_bytes(), b'x' * len(original))

    def test_cache_refuses_symlinks_hardlinks_and_unsafe_modes(self):
        files = synthetic_images()
        manifest = synthetic_manifest(files)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = firmware.install_payloads(files, root)
            private = root / '.sargo-fingerprint'
            target = private / bundle / 'cmnlib64.b02'
            def check():
                return firmware.cached_payloads(root, manifest, expected_uid=os.getuid())
            target.chmod(0o644)
            with self.assertRaises(ValueError): check()
            target.chmod(0o600)
            alias = root / 'hardlink'
            os.link(target, alias)
            with self.assertRaises(ValueError): check()
            alias.unlink()
            target.rename(alias)
            target.symlink_to(alias)
            with self.assertRaises(OSError): check()
            target.unlink()
            alias.rename(target)
            private.chmod(0o777)
            with self.assertRaises(ValueError): check()
            private.chmod(0o755)
            self.assertEqual(check(), files)
            with self.assertRaises(ValueError):
                firmware.cached_payloads(root, manifest, expected_uid=os.getuid() + 1)

    def test_signatures_and_truncation(self):
        files = synthetic_images()
        self.assertEqual(len(firmware.validate_structure(files)), 2)
        files['fpctzappfingerprint.mdt'] += b'changed signature'
        with self.assertRaises(ValueError):
            firmware.validate_structure(files)
        files = synthetic_images()
        files['cmnlib64.b02'] = files['cmnlib64.b02'][:-1]
        with self.assertRaises(ValueError):
            firmware.validate_structure(files)

    def test_manifest_rejects_changed_bytes(self):
        files = synthetic_images()
        observed = {'files': {name: {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                              for name, data in files.items()}}
        manifest = {'source': str(firmware.SOURCE), 'vendor_build': firmware.BUILD, **observed}
        firmware.validate_manifest(files, observed, manifest)
        corrupt = json.loads(json.dumps(observed))
        corrupt['files']['cmnlib64.b02']['sha256'] = '0' * 64
        with self.assertRaises(ValueError):
            firmware.validate_manifest(files, corrupt, manifest)

    def test_idempotence_and_incomplete_install(self):
        files = synthetic_images()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = firmware.install_payloads(files, root)
            self.assertEqual(firmware.install_payloads(files, root), bundle)
            for name, data in files.items():
                self.assertEqual((root / name).read_bytes(), data)
                self.assertEqual((root / name).stat().st_mode & 0o777, 0o600)
            (root / 'cmnlib64.mdt').unlink()
            firmware.install_payloads(files, root)
            self.assertEqual((root / 'cmnlib64.mdt').read_bytes(), files['cmnlib64.mdt'])

    def test_conflict_and_modified_bundle_fail_closed(self):
        files = synthetic_images()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            conflict = root / 'cmnlib64.mdt'
            conflict.write_bytes(b'unrelated existing firmware')
            with self.assertRaises(ValueError):
                firmware.install_payloads(files, root)
            self.assertEqual(conflict.read_bytes(), b'unrelated existing firmware')
            self.assertFalse((root / 'fpctzappfingerprint.mdt').exists())
            conflict.unlink()
            firmware.install_payloads(files, root)
            conflict.write_bytes(b'corrupt staged firmware')
            with self.assertRaises(ValueError):
                firmware.install_payloads(files, root)

    def test_unexpected_firmware_symlink_is_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'cmnlib64.mdt').symlink_to('other-vendor/cmnlib64.mdt')
            with self.assertRaises(ValueError):
                firmware.install_payloads(synthetic_images(), root)
            self.assertEqual((root / 'cmnlib64.mdt').readlink(), Path('other-vendor/cmnlib64.mdt'))


if __name__ == '__main__':
    unittest.main()
