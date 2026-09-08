#!/usr/bin/python3
"""Exercise the portable helper against temporary files, never the host /usr."""
import contextlib
import copy
import importlib.util
import io
import json
import os
import shutil
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("live_swipe", Path(__file__).with_name("live-swipe.py"))
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)
XML = b'<schemalist><schema id="mobi.phosh.osk" path="/mobi/phosh/osk/"><key name="swipe-typing" type="b"><default>false</default></key></schema></schemalist>'
ELF = b"\x7fELF\x02\x01" + bytes(12) + b"\xb7\x00" + b"prototype"


class LiveSwipeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bundle = self.root / "bundle"
        (self.bundle / "payload").mkdir(parents=True)
        self.manifest = self.bundle / "manifest.json"
        self.payload = {name: XML if name == live.SCHEMA else ELF + name.encode() for name in live.TARGETS}
        self.doc = {"format": 1, "architecture": "aarch64", "files": {name: {"sha256": live.sha(data)} for name, data in self.payload.items()}}
        for name, data in self.payload.items():
            (self.bundle / "payload" / name).write_bytes(data)
        self.save_manifest()

    def save_manifest(self):
        self.manifest.write_text(json.dumps(self.doc))

    def targets(self):
        schemas = self.root / "usr/share/glib-2.0/schemas"
        binaries = self.root / "usr/bin"
        schemas.mkdir(parents=True)
        binaries.mkdir(parents=True)
        targets = {name: schemas / name if name == live.SCHEMA else binaries / name for name in live.TARGETS}
        stable = {}
        for name, target in targets.items():
            target.write_bytes(b"stable-" + name.encode())
            stable[name] = (live.sha(target.read_bytes()),)
        (schemas / "gschemas.compiled").write_bytes(b"old-compiled")
        for name, value in [("SCHEMAS", schemas), ("TARGETS", targets), ("STABLE", stable)]:
            self.enterContext(patch.object(live, name, value))
        return targets, schemas

    def test_verify_valid_payload_without_phone_or_privileges(self):
        payload, digest = live.load_payload(self.manifest)
        self.assertEqual(payload, self.payload)
        self.assertEqual(digest, live.sha(self.manifest.read_bytes()))

    def test_manifest_rejects_extra_destination(self):
        self.doc["files"]["../../etc/shadow"] = {"sha256": "a" * 64}
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "exactly"):
            live.load_payload(self.manifest)

    def test_manifest_change_after_sudo_preflight_is_rejected(self):
        _, digest = live.load_payload(self.manifest)
        self.manifest.write_text(self.manifest.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "changed after preflight"):
            live.load_payload(self.manifest, digest)

    def test_payload_tampering_or_symlink_is_rejected(self):
        path = self.bundle / "payload/verbisaged"
        path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            live.load_payload(self.manifest)
        path.unlink()
        other = self.root / "other"
        other.write_bytes(self.payload["verbisaged"])
        path.symlink_to(other)
        with self.assertRaisesRegex(ValueError, "nonsymlink"):
            live.load_payload(self.manifest)

    def test_wrong_architecture_elf_is_rejected_even_with_correct_hash(self):
        path = self.bundle / "payload/verbisaged"
        data = ELF[:18] + b"\x3e\x00" + ELF[20:]
        path.write_bytes(data)
        self.doc["files"]["verbisaged"]["sha256"] = live.sha(data)
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, "aarch64 ELF"):
            live.load_payload(self.manifest)

    def test_known_stable_and_identical_prototype_are_eligible(self):
        targets, _ = self.targets()
        live.validate_targets(self.payload)
        for name, path in targets.items():
            path.write_bytes(self.payload[name])
        live.validate_targets(self.payload)

    def test_other_experiment_or_override_is_preserved(self):
        targets, schemas = self.targets()
        override = schemas / live.OVERRIDE
        override.write_bytes(b"unrelated")
        with self.assertRaisesRegex(ValueError, "unrelated"):
            live.validate_targets(self.payload)
        self.assertEqual(override.read_bytes(), b"unrelated")
        override.unlink()
        targets["verbisaged"].write_bytes(b"other experiment")
        with self.assertRaisesRegex(ValueError, "preserve the other experiment"):
            live.validate_targets(self.payload)
        self.assertEqual(targets["verbisaged"].read_bytes(), b"other experiment")

    def test_staging_fingerprint_ignores_unlock_and_cached_update_only(self):
        before = {"deployments": [
            {"checksum": "pending", "staged": True, "pinned": False, "requested-packages": ["retained"]},
            {"checksum": "booted", "booted": True, "pinned": True, "unlocked": "none"},
        ], "cached-update": {"timestamp": 1}}
        after = copy.deepcopy(before)
        after["deployments"][1]["unlocked"] = "development"
        after["cached-update"]["timestamp"] = 2
        with patch.object(live, "run", side_effect=[json.dumps(before), json.dumps(after)]):
            first = live.deployment_state()[0]
            self.assertEqual(first, live.deployment_state()[0])
        for field, value in [("checksum", "other"), ("pinned", True), ("requested-packages", ["changed"]), ("regenerate-initramfs", True)]:
            changed = copy.deepcopy(after)
            changed["deployments"][0][field] = value
            with patch.object(live, "run", return_value=json.dumps(changed)):
                with self.assertRaisesRegex(ValueError, "changed during"):
                    live.same_deployment(first)
        after["transaction"] = ["upgrade"]
        with patch.object(live, "run", return_value=json.dumps(after)):
            with self.assertRaisesRegex(ValueError, "transaction"):
                live.deployment_state()

    def test_prepare_then_atomic_replace_keeps_running_inode_and_modes(self):
        targets, schemas = self.targets()
        path = targets["verbisaged"]
        old = path.read_bytes()
        with path.open("rb") as running, patch.object(live.os, "fchown") as chown, patch.object(live, "run") as commands:
            live.replace_files({path: self.payload["verbisaged"], schemas / live.OVERRIDE: live.OVERRIDE_BYTES})
            self.assertEqual(running.read(), old)
            self.assertEqual(path.read_bytes(), self.payload["verbisaged"])
            self.assertEqual(path.stat().st_mode & 0o777, 0o755)
            self.assertEqual((schemas / live.OVERRIDE).stat().st_mode & 0o777, 0o644)
            self.assertEqual([call.args[0][0] for call in commands.call_args_list], ["chcon", "chcon", "restorecon", "restorecon"])
            self.assertEqual(chown.call_count, 2)
        self.assertEqual(list(path.parent.glob(".live-swipe-*")), [])

    def test_partial_replace_failure_restores_files_and_removes_new_override(self):
        targets, schemas = self.targets()
        path = targets["verbisaged"]
        old = path.read_bytes()
        override = schemas / live.OVERRIDE
        failed = False
        def command(args):
            nonlocal failed
            if args[0] == "restorecon" and Path(args[-1]) == path and not failed:
                failed = True
                raise subprocess.CalledProcessError(1, args)
            return ""
        with patch.object(live.os, "fchown"), patch.object(live, "run", side_effect=command):
            with self.assertRaises(subprocess.CalledProcessError):
                live.replace_files({override: live.OVERRIDE_BYTES, path: self.payload["verbisaged"]})
        self.assertEqual(path.read_bytes(), old)
        self.assertFalse(override.exists())
        self.assertEqual(list(schemas.glob(".live-swipe-*")), [])
        self.assertEqual(list(path.parent.glob(".live-swipe-*")), [])

    @unittest.skipUnless(shutil.which("glib-compile-schemas") and shutil.which("gsettings"), "GLib tools required")
    def test_real_schema_compilation_enables_default_without_touching_inputs(self):
        _, schemas = self.targets()
        (schemas / live.SCHEMA).write_bytes(XML)
        before = {p.name: p.read_bytes() for p in schemas.iterdir()}
        with contextlib.redirect_stdout(io.StringIO()):
            result = live.compile_schema(self.payload)
        self.assertTrue(result)
        self.assertEqual({p.name: p.read_bytes() for p in schemas.iterdir()}, before)

    def test_hotfix_and_stale_deployment_refused_before_any_write(self):
        self.targets()
        for unlock in ["hotfix", "development"]:
            with patch.object(live.os, "geteuid", return_value=0), patch.object(live.os, "uname") as uname, patch.object(live, "same_deployment") as unchanged, patch.object(live, "deployment_state", return_value=("expected", unlock)), patch.object(live, "compile_schema") as compiler, patch.object(live, "require_overlay") as overlay:
                uname.return_value.machine = "aarch64"
                if unlock == "development":
                    unchanged.side_effect = ValueError("stale deployment")
                with self.assertRaises(ValueError):
                    live.write_usr(self.manifest, live.sha(self.manifest.read_bytes()), "expected")
                compiler.assert_not_called()
                overlay.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
