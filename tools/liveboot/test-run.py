#!/usr/bin/env python3
"""Host-only regression checks for module gating and recorded preparation."""
import argparse
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("liveboot_run", ROOT / "run.py")
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


class ModuleGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "bundle.json"
        self.bundle.write_text(json.dumps({"modules_install": "modules", "release": "test"}))
        self.release = self.root / "modules/lib/modules/test"
        self.release.mkdir(parents=True)
        self.base = ["configfs", "libcomposite", "usb_f_fs", "ublk_drv", "erofs", "overlay"]
        (self.release / "modules.builtin").write_text(
            "\n".join("kernel/" + module + ".ko" for module in self.base) + "\n")

    def test_supplier_order_survives_combined_dracut_lists(self):
        config = self.root / "dracut.conf"
        config.write_text('force_drivers+=" supplier \\\nconsumer "\nadd_drivers+=" supplier gadget-phy dwc3 "\n')
        self.assertEqual(
            RUN.early_modules({"dracut_config": "dracut.conf"}, self.root),
            ["supplier", "consumer", "gadget-phy", "dwc3"])

    def test_installed_compressed_driver_and_builtin_transport_are_accepted(self):
        (self.release / "dwc3-qcom-legacy.ko.zst").write_bytes(b"test module")
        RUN.verify_required_modules(self.bundle, ["dwc3_qcom_legacy"])

    def test_missing_required_driver_is_a_hard_failure(self):
        with self.assertRaisesRegex(ValueError, "dwc3_qcom_legacy"):
            RUN.verify_required_modules(self.bundle, ["dwc3_qcom_legacy"])

    def test_two_module_releases_are_rejected(self):
        (self.release.parent / "stale-build").mkdir()
        with self.assertRaisesRegex(ValueError, "exactly one"):
            RUN.verify_required_modules(self.bundle, [])


class ResidentReleaseTests(unittest.TestCase):
    def test_only_verified_ram_pass_releases_host(self):
        record = {"root_mode": "ram", "result": "pass",
                  "resident": {"smoo_detached": True, "hashes_verified": True},
                  "checks": {"root_transport_ready": True}}
        self.assertTrue(RUN.can_release_usb_host(record))
        for key, value in (("root_mode", "usb"), ("result", "fail"),
                           ("resident", {}), ("checks", {})):
            self.assertFalse(RUN.can_release_usb_host(record | {key: value}))


class PrepareTests(unittest.TestCase):
    def test_serial_and_run_names_cannot_escape_the_artifact_directory(self):
        for name in ["", "../phone", "/tmp/phone", "-s", "phone other", "phone\nother"]:
            with self.subTest(name=name), self.assertRaises(ValueError):
                RUN.safe_name(name)

    def test_prepare_binds_product_and_exact_physical_serial_without_device_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture = root / "fixture"
            (fixture / "kernel-bundle").mkdir(parents=True)
            (fixture / "kernel-bundle/bundle.json").write_text(json.dumps({
                "release": "test", "dtb": {"path": "dtb/qcom/sdm670-google-sargo.dtb"}}))
            recipe = json.loads((ROOT / "profiles/google-sargo.json").read_text())
            (fixture / "fixture.json").write_text(json.dumps({"inputs": {
                "image": {"reference": recipe["fixture_image"]},
                "dtb": recipe["devicetree_name"] + ".dtb"}}))
            for path in [fixture / "rootfs.erofs", fixture / "production-ablx-shim.bin",
                         fixture / "kernel-bundle/kernel.config", root / "kboop", root / "init"]:
                path.write_bytes(b"test artifact")
            args = argparse.Namespace(
                run_dir=root / "serial-selection", fixture=fixture,
                profile=ROOT / "profiles/google-sargo.json", device_serial="TEST-SARGO-123",
                kboop=root / "kboop", init=root / "init", kernel_bundle=None)
            captured = {}

            def assemble(argv, **kwargs):
                captured["argv"] = argv
                captured["environment"] = kwargs["env"]
                artifacts = args.run_dir / "artifacts"
                artifacts.mkdir()
                (artifacts / "boot.img").write_bytes(b"assembled boot image")
                (artifacts / "modules.ero").write_bytes(b"assembled modules")

            with mock.patch.object(RUN, "verify_required_modules"), \
                    mock.patch.object(RUN.subprocess, "run", side_effect=assemble), \
                    mock.patch.object(RUN.os, "open", side_effect=AssertionError("device access")), \
                    contextlib.redirect_stdout(io.StringIO()):
                RUN.prepare(args)
            self.assertIn("--no-boot", captured["argv"])
            self.assertEqual(captured["environment"]["RUST_LOG"], RUN.os.environ.get("RUST_LOG", "info"))
            schemas = Path(captured["environment"]["FASTBOOP_SCHEMA_PATH"])
            devpro = json.loads(next(schemas.glob("*.json")).read_text())
            self.assertEqual(devpro["probe"], [
                {"fastboot.getvar": "product", "equals": "sargo"},
                {"fastboot.getvar": "serialno", "equals": "TEST-SARGO-123"}])
            self.assertEqual(devpro["id"], "pocketfed-google-sargo-TEST-SARGO-123")
            self.assertEqual(json.loads((args.run_dir / "status.json").read_text())["phase"], "prepared")
            manifest = json.loads((args.run_dir / "run.json").read_text())
            self.assertEqual(manifest["kernel_bundle"]["source"], "fixture")
            self.assertEqual(manifest["kernel_config"]["status"], "present")
            self.assertEqual(manifest["kernel_config"]["path"],
                             str(fixture / "kernel-bundle/kernel.config"))
            prepared_path = args.run_dir / "prepared.json"
            self.assertEqual(manifest["inputs"][str(prepared_path)], RUN.sha256(prepared_path))
            self.assertEqual(manifest["inputs"][str(next(schemas.glob("*.json")))],
                             RUN.sha256(next(schemas.glob("*.json"))))
            prepared = json.loads(prepared_path.read_text())
            for key in ["rootfs", "modules_image", "boot_image"]:
                self.assertEqual(prepared[key]["sha256"], RUN.sha256(prepared[key]["path"]))
            self.assertIn("--prepared", manifest["boot_argv"])
            self.assertTrue({"--kernel-bundle", "--rootfs", "--work-dir", "--init"}.isdisjoint(
                manifest["boot_argv"]))

            # Changing the serial probe must fail before touching the UART or
            # launching a host, rather than selecting an unintended Sargo.
            probe_path = next(schemas.glob("*.json"))
            original_probe = probe_path.read_bytes()
            probe_path.write_text("{}")
            host_args = argparse.Namespace(run_dir=args.run_dir, uart=root / "unused-uart", timeout=1)
            with mock.patch.object(RUN.os, "open", side_effect=AssertionError("device access")), \
                    mock.patch.object(RUN.subprocess, "run", side_effect=AssertionError("process access")), \
                    self.assertRaisesRegex(ValueError, "prepared input changed"):
                RUN.boot(host_args)
            probe_path.write_bytes(original_probe)

            # All OS-facing UART actions are mocked: this exercises the actual
            # boot dispatch without opening hardware or launching kboop.
            child = mock.Mock(returncode=0, pid=999999)
            child.poll.return_value = 0
            with mock.patch.object(RUN.tempfile, "gettempdir", return_value=str(root)), \
                    mock.patch.object(RUN.subprocess, "run", return_value=mock.Mock(returncode=1)), \
                    mock.patch.object(RUN.subprocess, "Popen", return_value=child) as dispatch, \
                    mock.patch.object(RUN.os, "open", side_effect=lambda path, flags: 178 if Path(path).name == "control" else 177), \
                    mock.patch.object(RUN.os, "close"), \
                    mock.patch.object(RUN.os, "fchmod"), \
                    mock.patch.object(RUN.termios, "tcgetattr", return_value=[0, 0, 0, 0, 0, 0, [0] * 32]), \
                    mock.patch.object(RUN.termios, "tcsetattr"), \
                    mock.patch.object(RUN.termios, "tcflush"), \
                    mock.patch.object(RUN.fcntl, "ioctl"):
                RUN.boot(host_args)
            self.assertEqual(dispatch.call_args.args[0], manifest["boot_argv"])
            self.assertEqual(json.loads((args.run_dir / "status.json").read_text())["phase"], "stopped")

    def candidate_inputs(self, root, *, dtb="sdm670-google-sargo.dtb", config=True):
        fixture = root / "fixture"
        (fixture / "kernel-bundle").mkdir(parents=True)
        recipe = json.loads((ROOT / "profiles/google-sargo.json").read_text())
        (fixture / "fixture.json").write_text(json.dumps({"inputs": {
            "image": {"reference": recipe["fixture_image"]},
            "dtb": recipe["devicetree_name"] + ".dtb"}}))
        (fixture / "kernel-bundle/bundle.json").write_text(json.dumps({"release": "baseline"}))
        (fixture / "kernel-bundle/kernel.config").write_text("BASELINE_CONFIG=y\n")
        for path in [fixture / "rootfs.erofs", fixture / "production-ablx-shim.bin",
                     root / "kboop", root / "init"]:
            path.write_bytes(b"unchanged userspace or tool")
        candidate = root / "candidate"
        candidate.mkdir()
        bundle = candidate / "bundle.json"
        bundle.write_text(json.dumps({"release": "candidate-ath10k", "dtb": {"path": "dtb/qcom/" + dtb}}))
        if config:
            (candidate / "kernel.config").write_text("CANDIDATE_CONFIG=y\n")
        return argparse.Namespace(run_dir=root / "candidate-run", fixture=fixture,
                                  profile=ROOT / "profiles/google-sargo.json",
                                  device_serial="TEST-SARGO-123", kboop=root / "kboop",
                                  init=root / "init", kernel_bundle=bundle)

    def test_candidate_override_uses_selected_bundle_release_hash_and_config(self):
        for has_config in (True, False):
            with self.subTest(config=has_config), tempfile.TemporaryDirectory() as temporary:
                args = self.candidate_inputs(Path(temporary), config=has_config)
                rootfs_before = (args.fixture / "rootfs.erofs").read_bytes()

                def assemble(argv, **kwargs):
                    self.assertEqual(argv[argv.index("--kernel-bundle") + 1], str(args.kernel_bundle))
                    self.assertEqual(argv[argv.index("--rootfs") + 1], str(args.fixture / "rootfs.erofs"))
                    artifacts = args.run_dir / "artifacts"
                    artifacts.mkdir()
                    (artifacts / "boot.img").write_bytes(b"candidate boot")
                    (artifacts / "modules.ero").write_bytes(b"candidate modules")

                with mock.patch.object(RUN, "verify_required_modules") as gate, \
                        mock.patch.object(RUN.subprocess, "run", side_effect=assemble), \
                        mock.patch.object(RUN.os, "open", side_effect=AssertionError("device access")), \
                        contextlib.redirect_stdout(io.StringIO()):
                    RUN.prepare(args)
                self.assertEqual(gate.call_args.args[0], args.kernel_bundle)
                manifest = json.loads((args.run_dir / "run.json").read_text())
                self.assertEqual(manifest["kernel_release"], "candidate-ath10k")
                self.assertEqual(manifest["kernel_bundle"], {
                    "path": str(args.kernel_bundle), "sha256": RUN.sha256(args.kernel_bundle), "source": "override"})
                self.assertEqual(manifest["inputs"][str(args.kernel_bundle)], RUN.sha256(args.kernel_bundle))
                self.assertNotIn(str(args.fixture / "kernel-bundle/bundle.json"), manifest["inputs"])
                self.assertNotIn(str(args.fixture / "kernel-bundle/kernel.config"), manifest["inputs"])
                config = args.kernel_bundle.parent / "kernel.config"
                if has_config:
                    self.assertEqual(manifest["kernel_config"], {
                        "status": "present", "path": str(config), "sha256": RUN.sha256(config)})
                    self.assertEqual(manifest["inputs"][str(config)], RUN.sha256(config))
                else:
                    self.assertEqual(manifest["kernel_config"], {"status": "absent", "path": None, "sha256": None})
                    self.assertNotIn(str(config), manifest["inputs"])
                self.assertEqual((args.fixture / "rootfs.erofs").read_bytes(), rootfs_before)

    def test_candidate_for_wrong_device_is_rejected_before_assembly(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.candidate_inputs(Path(temporary), dtb="sdm845-oneplus-fajita.dtb")
            with mock.patch.object(RUN.subprocess, "run", side_effect=AssertionError("process access")), \
                    mock.patch.object(RUN.os, "open", side_effect=AssertionError("device access")), \
                    self.assertRaisesRegex(ValueError, "device tree does not match"):
                RUN.prepare(args)
            self.assertEqual(json.loads((args.run_dir / "status.json").read_text())["phase"], "failed")

    def test_candidate_required_module_failure_is_not_hidden_by_baseline(self):
        with tempfile.TemporaryDirectory() as temporary:
            args = self.candidate_inputs(Path(temporary))
            with mock.patch.object(RUN, "verify_required_modules", side_effect=ValueError("missing candidate module")) as gate, \
                    mock.patch.object(RUN.subprocess, "run", side_effect=AssertionError("process access")), \
                    self.assertRaisesRegex(ValueError, "missing candidate module"):
                RUN.prepare(args)
            self.assertEqual(gate.call_args.args[0], args.kernel_bundle)


class BootFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.run = self.root / "run"
        self.run.mkdir()
        (self.run / "run.json").write_text(json.dumps({
            "inputs": {}, "device_serial": "TEST-CLEANUP", "run_id": "run",
            "kernel_release": "test", "boot_argv": ["DO-NOT-LAUNCH"], "environment": {}}))
        self.args = argparse.Namespace(run_dir=self.run, uart=self.root / "unused-uart", timeout=1)
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(RUN.tempfile, "gettempdir", return_value=str(self.root)))
        self.fuser = self.stack.enter_context(mock.patch.object(
            RUN.subprocess, "run", return_value=mock.Mock(returncode=1)))
        self.open_uart = self.stack.enter_context(mock.patch.object(
            RUN.os, "open", side_effect=lambda path, flags: 178 if Path(path).name == "control" else 177))
        self.close_uart = self.stack.enter_context(mock.patch.object(RUN.os, "close"))
        self.stack.enter_context(mock.patch.object(RUN.os, "fchmod"))
        self.read_attrs = self.stack.enter_context(mock.patch.object(
            RUN.termios, "tcgetattr", side_effect=lambda fd: [0, 0, 0, 0, 0, 0, [0] * 32]))
        self.set_attrs = self.stack.enter_context(mock.patch.object(RUN.termios, "tcsetattr"))
        self.stack.enter_context(mock.patch.object(RUN.termios, "tcflush"))
        self.ioctl = self.stack.enter_context(mock.patch.object(RUN.fcntl, "ioctl"))

    def assert_lock_released(self):
        for name in ("TEST-CLEANUP.lock", "smoo-host.lock"):
            path = self.root / f"pocketfed-liveboot-locks-{RUN.os.getuid()}" / name
            with path.open("a") as lock:
                RUN.fcntl.flock(lock, RUN.fcntl.LOCK_EX | RUN.fcntl.LOCK_NB)


class BootCleanupTests(BootFixture):
    def test_another_smoo_host_is_rejected_before_uart_or_device_access(self):
        locks = self.root / f"pocketfed-liveboot-locks-{RUN.os.getuid()}"
        locks.mkdir(mode=0o700)
        with (locks / "smoo-host.lock").open("a") as holder:
            RUN.fcntl.flock(holder, RUN.fcntl.LOCK_EX | RUN.fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, "only one USB-root session"):
                RUN.boot(self.args)
        self.open_uart.assert_not_called()
        self.fuser.assert_not_called()
        self.assert_lock_released()

    def test_existing_uart_reader_releases_device_lease_without_opening_uart(self):
        self.fuser.return_value = mock.Mock(returncode=0, stdout=b"1234", stderr=b"")
        with self.assertRaisesRegex(ValueError, "already open"):
            RUN.boot(self.args)
        self.open_uart.assert_not_called()
        self.assert_lock_released()

    def test_termios_failure_closes_uart_and_releases_device_lease(self):
        self.read_attrs.side_effect = RUN.termios.error(5, "UART disconnected")
        with self.assertRaises(RUN.termios.error):
            RUN.boot(self.args)
        self.close_uart.assert_called_once_with(177)
        self.assert_lock_released()

    def test_child_exit_during_termination_does_not_skip_uart_cleanup(self):
        child = mock.Mock(returncode=0, pid=999999)
        child.poll.side_effect = [KeyboardInterrupt, None]
        with mock.patch.object(RUN.subprocess, "Popen", return_value=child), \
                mock.patch.object(RUN.os, "killpg", side_effect=ProcessLookupError):
            RUN.boot(self.args)
        child.wait.assert_called_once_with(timeout=10)
        self.close_uart.assert_any_call(177)
        self.close_uart.assert_any_call(178)
        self.assertEqual(self.set_attrs.call_count, 2)
        self.assertFalse((self.run / "control").exists())
        self.assert_lock_released()


class UARTControlTests(BootFixture):
    def test_spontaneous_reboot_disarms_control_until_fresh_matching_token(self):
        child = mock.Mock(returncode=0, pid=999999)
        child.poll.side_effect = [None, None, None, 0, 0]
        serial = [b"Kernel command line: pocketfed.liveboot=run\n",
                  b"[    0.000000] Linux version 7.1.2-installed\n",
                  b"Kernel command line: root=LABEL=pfroot ostree=true\n"]
        with mock.patch.object(RUN.subprocess, "Popen", return_value=child), \
                mock.patch.object(RUN.select, "select", return_value=([177, 178], [], [])), \
                mock.patch.object(RUN.os, "read", side_effect=lambda fd, size: serial.pop(0) if fd == 177 else b"help\n"), \
                mock.patch.object(RUN, "uart_sysrq") as transmit:
            RUN.boot(self.args)
        transmit.assert_called_once_with(177, "help")
        state = json.loads((self.run / "status.json").read_text())
        self.assertFalse(state["control_ready"])
        self.assertEqual(state["control_disabled_reason"], "new or unmatched kernel boot")
        records = [json.loads(line) for line in (self.run / "control.log").read_text().splitlines()]
        self.assertEqual([record["status"] for record in records],
                         ["accepted", "sent", "rejected-unverified-run", "rejected-unverified-run"])

    def test_fifo_commands_are_gated_by_exact_current_uart_token(self):
        child = mock.Mock(returncode=0, pid=999999)
        child.poll.side_effect = [None, None, None, None, None, 0, 0]
        serial = [b"Kernel command line: pocketfed.liveboot=run-other\n",
                  b"Kernel command line: pocketfed.liveboot=run\r\n"]
        commands = [b"reboot\n", b"help\n", b"reboot\n", b"help\n"]
        ready = [([177, 178], [], []), ([177, 178], [], []), ([178], [], []),
                 ([178], [], []), ([], [], [])]

        def read(fd, size):
            return serial.pop(0) if fd == 177 else commands.pop(0)

        with mock.patch.object(RUN.subprocess, "Popen", return_value=child), \
                mock.patch.object(RUN.select, "select", side_effect=ready), \
                mock.patch.object(RUN.os, "read", side_effect=read), \
                mock.patch.object(RUN, "uart_sysrq") as transmit:
            RUN.boot(self.args)
        self.assertEqual(transmit.call_args_list, [mock.call(177, "help"), mock.call(177, "reboot")])
        records = [json.loads(line) for line in (self.run / "control.log").read_text().splitlines()]
        self.assertEqual([record["status"] for record in records],
                         ["rejected-unverified-run", "accepted", "sent", "accepted", "sent", "rejected-unverified-run"])
        self.assertTrue(all(record["run_id"] == "run" and "time" in record for record in records))
        self.assertFalse((self.run / "control").exists())
        self.assertFalse(json.loads((self.run / "status.json").read_text())["control_ready"])
        self.assertTrue(self.open_uart.call_args_list[0].args[1] & RUN.os.O_RDWR)
        self.assert_lock_released()

    def test_invalid_and_oversized_fifo_lines_never_become_commands(self):
        commands, pending = RUN.control_lines(b"", b"help\nreboot now\nx" * 100)
        self.assertLessEqual(len(pending), 64)
        self.assertNotIn("reboot", commands)
        commands, pending = RUN.control_lines(b"", b"x" * 1000)
        self.assertEqual(commands, [])
        commands, pending = RUN.control_lines(pending, b"help\nreboot\n")
        self.assertEqual(commands, ["reboot"])
        self.assertEqual(pending, b"")

    def test_ftdi_sequence_restores_baud_before_sending_allowlisted_key(self):
        events = []
        self.set_attrs.side_effect = lambda fd, when, attrs: events.append(("baud", attrs[4], attrs[5]))
        with mock.patch.object(RUN.os, "write", side_effect=lambda fd, data: events.append(("write", data)) or len(data)), \
                mock.patch.object(RUN.termios, "tcdrain", side_effect=lambda fd: events.append(("drain",))), \
                mock.patch.object(RUN.time, "sleep", side_effect=lambda seconds: events.append(("sleep", seconds))):
            RUN.uart_sysrq(177, "help")
        self.assertEqual(events, [
            ("baud", RUN.termios.B300, RUN.termios.B300), ("write", b"\0"), ("drain",), ("sleep", 0.1),
            ("baud", RUN.termios.B115200, RUN.termios.B115200), ("sleep", 0.2), ("write", b"h"), ("drain",)])

    def test_ftdi_write_failure_still_restores_115200_and_sends_no_key(self):
        with mock.patch.object(RUN.os, "write", side_effect=OSError("UART gone")) as write, \
                self.assertRaisesRegex(OSError, "UART gone"):
            RUN.uart_sysrq(177, "reboot")
        self.assertEqual(self.set_attrs.call_args.args[2][4:6], [RUN.termios.B115200] * 2)
        write.assert_called_once_with(177, b"\0")

    def test_stalled_drain_deadline_restores_baud_and_cancels_alarm(self):
        handlers = {}

        def remember_handler(signum, handler):
            handlers[signum] = handler

        def stalled_drain(fd):
            handlers[RUN.signal.SIGALRM](RUN.signal.SIGALRM, None)

        with mock.patch.object(RUN.os, "write", return_value=1) as write, \
                mock.patch.object(RUN.signal, "getsignal", return_value=RUN.signal.SIG_DFL), \
                mock.patch.object(RUN.signal, "getitimer", return_value=(0, 0)), \
                mock.patch.object(RUN.signal, "signal", side_effect=remember_handler), \
                mock.patch.object(RUN.signal, "setitimer") as timer, \
                mock.patch.object(RUN.termios, "tcdrain", side_effect=stalled_drain), \
                self.assertRaisesRegex(TimeoutError, "two seconds"):
            RUN.uart_sysrq(177, "reboot")
        self.assertEqual(self.set_attrs.call_args.args[2][4:6], [RUN.termios.B115200] * 2)
        write.assert_called_once_with(177, b"\0")
        self.assertEqual(timer.call_args_list, [mock.call(RUN.signal.ITIMER_REAL, 2.0),
                                              mock.call(RUN.signal.ITIMER_REAL, 0)])
        self.assertEqual(handlers[RUN.signal.SIGALRM], RUN.signal.SIG_DFL)


class SysRqClientTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run = Path(temporary.name) / "run"
        self.run.mkdir()
        (self.run / "run.json").write_text(json.dumps({"run_id": "run"}))
        (self.run / "status.json").write_text(json.dumps({"run_id": "run", "phase": "hosting", "control_ready": True}))
        self.args = argparse.Namespace(run_dir=self.run, key="help")

    def test_missing_reader_fails_without_waiting(self):
        RUN.os.mkfifo(self.run / "control", 0o600)
        with self.assertRaisesRegex(ValueError, "no active host is reading"):
            RUN.sysrq(self.args)

    def test_disarmed_or_mismatched_run_is_rejected_before_opening_fifo(self):
        for state in [{"run_id": "other", "phase": "hosting", "control_ready": True},
                      {"run_id": "run", "phase": "stopped", "control_ready": True},
                      {"run_id": "run", "phase": "hosting", "control_ready": False}]:
            (self.run / "status.json").write_text(json.dumps(state))
            with mock.patch.object(RUN.os, "open", side_effect=AssertionError("must not open FIFO")), \
                    self.assertRaises(ValueError):
                RUN.sysrq(self.args)

    def test_client_queues_only_one_allowlisted_line_to_private_fifo(self):
        path = self.run / "control"
        RUN.os.mkfifo(path, 0o600)
        info = path.stat()
        with mock.patch.object(RUN.os, "open", return_value=188) as opened, \
                mock.patch.object(RUN.os, "fstat", return_value=info), \
                mock.patch.object(RUN.os, "write", return_value=5) as write, \
                mock.patch.object(RUN.os, "close") as close, \
                contextlib.redirect_stdout(io.StringIO()):
            RUN.sysrq(self.args)
        flags = opened.call_args.args[1]
        self.assertTrue(flags & RUN.os.O_NONBLOCK)
        self.assertTrue(flags & RUN.os.O_NOFOLLOW)
        write.assert_called_once_with(188, b"help\n")
        close.assert_called_once_with(188)


if __name__ == "__main__":
    unittest.main()
