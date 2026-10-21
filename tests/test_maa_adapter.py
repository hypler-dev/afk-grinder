"""The SDK boundary uses fakes; these tests never capture or inject OS input."""

import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from afk_grinder.recognition import maa_adapter as adapter


class SDKBoundaryTests(unittest.TestCase):
    def fake_modules(self, *, refused=None, native_version="v5.14.3"):
        success = SimpleNamespace(done=True, succeeded=True)
        tasker = Mock()
        tasker.bind.return_value = True
        tasker.post_stop.return_value = success
        tasker_type = Mock(return_value=tasker)
        for name in ("set_log_dir", "set_save_draw", "set_save_on_error", "set_debug_mode",
                     "set_stdout_level", "set_reco_image_cache_limit"):
            getattr(tasker_type, name).return_value = name != refused
        resource = Mock()
        resource.set_cpu.return_value = refused != "set_cpu"

        class Base:
            def __init__(self):
                pass

            def post_connection(self):
                return success

        modules = {
            "maa.library": SimpleNamespace(Library=SimpleNamespace(version=lambda: native_version)),
            "maa.tasker": SimpleNamespace(Tasker=tasker_type),
            "maa.resource": SimpleNamespace(Resource=lambda: resource),
            "maa.controller": SimpleNamespace(CustomController=Base),
            "maa.define": SimpleNamespace(LoggingLevelEnum=SimpleNamespace(Off=0)),
            "numpy": SimpleNamespace(zeros=lambda *a, **k: Mock(), uint8="uint8"),
        }
        return modules, tasker_type, tasker

    def probe(self, *, require_replacement=False, marker=None, loader_observation=None, **kwargs):
        modules, tasker_type, tasker = self.fake_modules(**kwargs)
        self.template_check = Mock()
        self.loader_check = Mock(return_value=loader_observation)
        if marker is not None:
            modules["maa.library"].Library.framework = Mock(return_value=SimpleNamespace(AfkGrinderReplacementProbe=marker))
        with patch.dict(adapter.os.environ, {}, clear=True), \
             patch.object(adapter.importlib.metadata, "version", return_value="5.14.3"), \
             patch.object(adapter.importlib.util, "find_spec", return_value=object()), \
             patch.object(adapter.importlib, "import_module", side_effect=modules.__getitem__), \
             patch.object(adapter, "_probe_replacement_template", self.template_check), \
             patch.object(adapter, "_windows_replacement_loads", self.loader_check):
            report = adapter.probe_sdk(require_replacement=require_replacement)
        return report, tasker_type, tasker

    def test_success_requires_all_privacy_options_and_cancellation(self):
        report, tasker_type, tasker = self.probe()
        self.assertFalse(report["native_input"])
        self.assertFalse(report["persistent_images"])
        self.assertEqual(report["capture_source"], "synthetic")
        tasker_type.set_log_dir.assert_called_once_with("")
        tasker_type.set_save_draw.assert_called_once_with(False)
        tasker_type.set_save_on_error.assert_called_once_with(False)
        tasker_type.set_reco_image_cache_limit.assert_called_once_with(2)
        tasker.post_stop.assert_called_once()

    def test_every_required_option_refusal_fails_closed(self):
        for name in ("set_log_dir", "set_save_draw", "set_save_on_error", "set_debug_mode",
                     "set_stdout_level", "set_reco_image_cache_limit", "set_cpu"):
            with self.subTest(name=name), self.assertRaises(adapter.SDKError):
                self.probe(refused=name)

    def test_private_replacement_diagnostic_requires_loaded_library_marker(self):
        marker = Mock(return_value=adapter.REPLACEMENT_PROBE.encode("ascii"))
        report, _, tasker = self.probe(require_replacement=True, marker=marker)
        self.assertEqual(report["replacement_probe"], adapter.REPLACEMENT_PROBE)
        self.assertEqual(report["synthetic_template_match"], "passed")
        self.template_check.assert_called_once_with()
        self.assertFalse(report["native_input"])
        self.assertEqual(report["capture_source"], "synthetic")
        marker.assert_called_once_with()
        tasker.post_stop.assert_called_once()
        with self.assertRaisesRegex(adapter.SDKError, "marker is unavailable"):
            self.probe(require_replacement=True)
        for value in (None, b"wrong", "afk-grinder-sdk-replacement-v1"):
            with self.subTest(value=value), self.assertRaisesRegex(adapter.SDKError, "marker did not match"):
                self.probe(require_replacement=True, marker=Mock(return_value=value))

    def test_normal_diagnostic_does_not_call_replacement_export(self):
        marker = Mock(side_effect=RuntimeError("must not run"))
        report, _, _ = self.probe(marker=marker)
        marker.assert_not_called()
        self.assertNotIn("replacement_probe", report)
        self.assertNotIn("synthetic_template_match", report)
        self.assertNotIn("windows_sdk_loads", report)
        self.template_check.assert_not_called()
        self.loader_check.assert_not_called()

    def test_windows_load_observation_is_private_and_platform_specific(self):
        marker = Mock(return_value=adapter.REPLACEMENT_PROBE.encode("ascii"))
        observation = {"schema_version": 1, "scope": "synthetic-replacement-worker", "loaded": [], "unobserved": []}
        for system in ("darwin", "win32"):
            with self.subTest(system=system), patch.object(adapter.sys, "platform", system):
                report, _, _ = self.probe(require_replacement=True, marker=marker, loader_observation=observation)
            if system == "win32":
                self.assertIs(report["windows_sdk_loads"], observation)
                self.loader_check.assert_called_once_with()
            else:
                self.assertNotIn("windows_sdk_loads", report)
                self.loader_check.assert_not_called()
        with patch.object(adapter.sys, "platform", "win32"), patch.object(adapter.sys, "frozen", False, create=True):
            with self.assertRaisesRegex(adapter.SDKError, "requires a frozen worker"):
                adapter._windows_replacement_loads()

    def test_replacement_template_requires_exact_original_match_and_always_closes(self):
        from afk_grinder.recognition.matcher import TemplateHit
        valid = TemplateHit("sdk-replacement", .99, (11, 9, 16, 16))
        for result in ((valid,), (), (TemplateHit("other", .99, valid.box),),
                       (TemplateHit(valid.template_id, .99, (12, 9, 16, 16)),),
                       (TemplateHit(valid.template_id, float("nan"), valid.box),),
                       (TemplateHit(valid.template_id, True, valid.box),)):
            instance = Mock()
            instance.match.return_value = result
            with self.subTest(result=result), \
                 patch('afk_grinder.recognition.matcher.TemplateMatcher', return_value=instance) as factory:
                if result == (valid,):
                    adapter._probe_replacement_template()
                    spec = factory.call_args.args[0][0]
                    width, height, pixels = instance.match.call_args.args
                    self.assertEqual((width, height), (96, 64))
                    self.assertEqual(instance.match.call_args.kwargs, {"timeout": 2})
                    for row in range(16):
                        offset = ((9 + row) * 96 + 11) * 3
                        self.assertEqual(pixels[offset:offset + 48], spec.pixels[row * 48:(row + 1) * 48])
                else:
                    with self.assertRaises(adapter.SDKError):
                        adapter._probe_replacement_template()
            instance.close.assert_called_once_with()
        instance = Mock()
        instance.match.side_effect = adapter.SDKError("Synthetic timeout")
        with patch('afk_grinder.recognition.matcher.TemplateMatcher', return_value=instance), \
             self.assertRaises(adapter.SDKError):
            adapter._probe_replacement_template()
        instance.close.assert_called_once_with()

    def test_replacement_mode_rejected_before_import_and_reserved_to_worker(self):
        with patch.object(adapter.importlib, "import_module") as load:
            with self.assertRaisesRegex(adapter.SDKError, "must be a boolean"):
                adapter.probe_sdk(require_replacement="yes")
        load.assert_not_called()
        from afk_grinder.__main__ import main

        with patch.object(sys, "argv", ["AFKGrinder", "--dry-run", "--sdk-replacement-probe"]), \
             patch.object(sys, "stderr", Mock()), self.assertRaises(SystemExit) as exited:
            main()
        self.assertEqual(exited.exception.code, 2)

    def test_native_version_must_match_exact_pin(self):
        with self.assertRaisesRegex(adapter.SDKError, "Expected native SDK"):
            self.probe(native_version="5.14.4")

    def test_distribution_version_rejected_before_native_import(self):
        with patch.dict(adapter.os.environ, {}, clear=True), \
             patch.object(adapter.importlib.metadata, "version", return_value="5.14.2"), \
             patch.object(adapter.importlib, "import_module") as load:
            with self.assertRaisesRegex(adapter.SDKError, "Expected MaaFw"):
                adapter.probe_sdk()
            load.assert_not_called()

    def test_missing_extra_reports_optional_dependency(self):
        with patch.dict(adapter.os.environ, {}, clear=True), \
             patch.object(adapter.importlib.metadata, "version", side_effect=importlib.metadata.PackageNotFoundError):
            with self.assertRaisesRegex(adapter.SDKError, "optional"):
                adapter.probe_sdk()

    def test_metadata_without_sdk_module_is_optional_not_ready(self):
        with patch.dict(adapter.os.environ, {}, clear=True), \
             patch.object(adapter.importlib.metadata, "version", return_value="5.14.3"), \
             patch.object(adapter.importlib.util, "find_spec", return_value=None):
            with self.assertRaisesRegex(adapter.SDKError, "optional"):
                adapter.probe_sdk()

    def test_windowed_cli_handles_missing_standard_streams(self):
        from afk_grinder.__main__ import main

        with patch.object(sys, "argv", ["AFKGrinder", "--sdk-check"]), \
             patch.object(sys, "stdout", None), patch.object(sys, "stderr", None), \
             patch.object(adapter, "diagnostic", return_value={"native_input": False}) as check:
            main()
            check.assert_called_once()
        with patch.object(sys, "argv", ["AFKGrinder", "--sdk-check"]), \
             patch.object(sys, "stdout", None), patch.object(sys, "stderr", None), \
             patch.object(adapter, "diagnostic", side_effect=adapter.SDKError("optional")), \
             self.assertRaises(SystemExit) as exited:
            main()
        self.assertEqual(exited.exception.code, 1)

    def test_external_binary_override_rejected_before_import(self):
        with patch.dict(adapter.os.environ, {"MAAFW_BINARY_PATH": "/untrusted"}), \
             patch.object(adapter.importlib, "import_module") as load:
            with self.assertRaisesRegex(adapter.SDKError, "overrides are disabled"):
                adapter.probe_sdk()
            load.assert_not_called()

    def test_controller_rejects_all_input_and_returns_frame_copy(self):
        frame = Mock()
        controller = adapter.read_only_controller_type(object)(frame)
        callbacks = {"start_app": ("x",), "stop_app": ("x",), "click": (1, 2),
                     "swipe": (1, 2, 3, 4, 5), "touch_down": (0, 1, 2, 3),
                     "touch_move": (0, 1, 2, 3), "touch_up": (0,), "click_key": (1,),
                     "input_text": ("x",), "key_down": (1,), "key_up": (1,),
                     "scroll": (1, 2), "relative_move": (1, 2)}
        for name, arguments in callbacks.items():
            with self.subTest(name=name):
                self.assertIs(getattr(controller, name)(*arguments), False)
        self.assertIsNone(controller.shell("x", 1))
        self.assertEqual(controller.get_features(), 0)
        self.assertIs(controller.screencap(), frame.copy.return_value)

    def test_pending_job_times_out_without_calling_unbounded_wait(self):
        job = Mock(done=False)
        with patch.object(adapter.time, "monotonic", side_effect=[10, 11]), \
             self.assertRaisesRegex(adapter.SDKError, "deadline"):
            adapter.wait_for_job(job, 0.5)
        job.wait.assert_not_called()

    def test_failed_job_and_invalid_deadlines_rejected(self):
        with self.assertRaisesRegex(adapter.SDKError, "failed"):
            adapter.wait_for_job(SimpleNamespace(done=True, succeeded=False))
        for value in (0, -1, float("nan"), float("inf"), 6):
            with self.subTest(value=value), self.assertRaises(ValueError):
                adapter.wait_for_job(None, value)

    def test_process_deadline_covers_native_import_and_teardown(self):
        with patch.object(adapter.subprocess, "run", side_effect=subprocess.TimeoutExpired("probe", 1)) as run:
            with self.assertRaisesRegex(adapter.SDKError, "process was terminated"):
                adapter.diagnostic(1)
            self.assertEqual(run.call_args.kwargs["timeout"], 1)

    def test_subprocess_failure_and_invalid_report_never_pass(self):
        for code, output, error in ((1, "", "unknown failure"), (0, "not json", ""),
                                    (0, '{"native_input": true}', "")):
            with self.subTest(output=output), \
                 patch.object(adapter.subprocess, "run", return_value=subprocess.CompletedProcess([], code, output, error)), \
                 self.assertRaises(adapter.SDKError):
                adapter.diagnostic()

    def test_private_report_works_without_stdout_and_is_removed(self):
        paths = []

        def worker(command, **kwargs):
            path = Path(command[-1])
            paths.append(path)
            path.write_text(json.dumps({"ok": True, "report": {"native_input": False}}))
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(adapter.subprocess, "run", side_effect=worker):
            self.assertEqual(adapter.diagnostic(), {"native_input": False})
        self.assertFalse(paths[0].exists())

    def test_worker_report_failure_oversize_and_malformed_payloads_fail_closed(self):
        for payload in ("x" * 4097, '[]', '{"ok": true}',
                        '{"ok": true, "report": {"native_input": true}}',
                        '{"ok": false, "error": "required option refused"}'):
            def worker(command, **kwargs):
                Path(command[-1]).write_text(payload)
                return subprocess.CompletedProcess(command, 0, "", "")

            with self.subTest(payload=payload[:50]), \
                 patch.object(adapter.subprocess, "run", side_effect=worker), \
                 self.assertRaises(adapter.SDKError):
                adapter.diagnostic()

    def test_package_import_does_not_load_sdk(self):
        code = "import afk_grinder.recognition.maa_adapter, sys; assert 'maa' not in sys.modules"
        subprocess.run([sys.executable, "-c", code], check=True, timeout=10,
                       cwd=Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    unittest.main()
