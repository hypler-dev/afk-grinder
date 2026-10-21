"""Read-only pack admission, cancellation and preview identity with fakes."""

from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from afk_grinder import __version__
from afk_grinder.capture import CapturedWindow
from afk_grinder.desktop_controller import DesktopController
from afk_grinder.pack_inspection import PackInspectionError, PackInspectionReport
from afk_grinder.recognition.content_calibration import ContentCalibration
from afk_grinder.recognition.frame_geometry import layout_from_capture
from afk_grinder.recognition.pack_results import AnchorHit
from afk_grinder.recognition.packs import load_pack
from afk_grinder.recognition.state import StateInspection
from tests.test_desktop_controller import Clock, FakeBackend, FakeJobs, FakeRunner, TARGET_ONE, TARGET_TWO
from tools.make_fixture_demo import generate


class PackControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.directory, _, _ = generate(Path(cls.temporary.name) / "demo", "a" * 40)
        cls.pack = load_pack(cls.directory, app_version=__version__)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.clock = Clock()
        self.runner = FakeRunner()
        self.backend = FakeBackend((TARGET_ONE,), ("Input permission denied",))
        self.controller = DesktopController(
            backend=self.backend, runner=self.runner, job_factory=FakeJobs(), clock=self.clock,
            pack_picker=lambda: self.directory, pack_loader=lambda _: self.pack,
        )
        self.controller._scan_thread.join(1)
        self.controller.get_state()
        self.frame = CapturedWindow(TARGET_ONE, "window", (0, 0, 136, 94), (136, 94), "display",
                                    (1., 1.), bytes(136 * 94 * 3), "BGR8", 10.)
        self.calibration = ContentCalibration.manual(layout_from_capture(self.frame), (20, 15, 96, 64))
        self.hits = tuple(AnchorHit(anchor.id, .99, (11, 9, 16, 16)) if anchor.id == "gameplay"
                          else AnchorHit(anchor.id, .01, None) for anchor in self.pack.anchors)
        self.report = PackInspectionReport(StateInspection("known", "gameplay", "stable", 2, "gameplay"),
                                           self.hits, self.frame, 2, 2)
        self.controller._encode_preview_async = lambda *_: None
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.controller.close()
        self.controller._close_stop_done.wait(1)

    def wait_for(self, predicate):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if predicate():
                return
            threading.Event().wait(.005)
        self.fail("Background operation did not finish.")

    def loaded(self, calibrated=True):
        self.assertTrue(self.controller.command("pack_choose", {})["ok"])
        self.wait_for(lambda: not self.controller.get_state()["pack"]["busy"])
        self.assertIs(self.controller._pack, self.pack)
        if calibrated:
            self.controller._content_calibration = self.calibration

    def inspect(self, report=None, error=None):
        outer = self
        class Operation:
            def run(self, guard, wait, **_kwargs):
                guard()
                if error is not None:
                    raise error
                return report or outer.report
            def close(self):
                pass
        self.controller._pack_session_factory = lambda *_: Operation()
        self.assertTrue(self.controller.command("pack_check", {})["ok"])
        self.controller._pack_thread.join(1)
        self.assertFalse(self.controller._pack_thread.is_alive())
        return self.controller.get_state()

    def test_bridge_never_accepts_paths_or_extra_fields(self):
        called = []
        self.controller._pack_picker = lambda: called.append(True)
        for command in ("pack_choose", "pack_check", "pack_clear"):
            self.assertFalse(self.controller.command(command, {"path": "/private/secret"})["ok"])
        self.assertEqual(called, [])

    def test_choose_guards_no_picker_unsupported_cleanup_and_active_input(self):
        for field, value in (("_pack_picker", None), ("_game_id", "blox")):
            before = getattr(self.controller, field)
            setattr(self.controller, field, value)
            self.assertFalse(self.controller.command("pack_choose", {})["ok"])
            setattr(self.controller, field, before)
        self.runner.cleanup_failed = True
        self.assertFalse(self.controller.command("pack_choose", {})["ok"])
        self.runner.cleanup_failed = False
        self.runner.running = True
        self.assertFalse(self.controller.command("pack_choose", {})["ok"])

    def test_stop_during_native_picker_revokes_selection_without_holding_lock(self):
        entered, release = threading.Event(), threading.Event()
        calls = []
        def picker():
            entered.set()
            release.wait(2)
            return self.directory
        self.controller._pack_picker = picker
        self.controller._pack_loader = lambda path: calls.append(path) or self.pack
        thread = threading.Thread(target=lambda: self.controller.command("pack_choose", {}))
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.controller.command("stop", {})["ok"])
            self.assertTrue(self.controller.get_state()["session"]["input_locked"])
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(calls, [])
        self.assertIsNone(self.controller._pack)

    def test_metadata_timeout_and_stop_drop_late_results(self):
        for timeout in (False, True):
            with self.subTest(timeout=timeout):
                entered, release, finished = threading.Event(), threading.Event(), threading.Event()
                def loader(_):
                    entered.set()
                    release.wait(2)
                    finished.set()
                    return self.pack
                self.controller._pack_loader = loader
                self.assertTrue(self.controller.command("pack_choose", {})["ok"])
                try:
                    self.assertTrue(entered.wait(1))
                    if timeout:
                        self.clock.value += 16
                        self.assertEqual(self.controller.get_state()["pack"]["phase"], "error")
                    else:
                        self.controller.command("stop", {})
                finally:
                    release.set()
                self.assertTrue(finished.wait(1))
                for thread in tuple(threading.enumerate()):
                    if thread.name == "pack-metadata":
                        thread.join(1)
                self.assertIsNone(self.controller.get_state()["pack"]["id"])

    def test_canceled_picker_keeps_previous_pack_and_errors_hide_private_text(self):
        self.loaded(False)
        self.controller._pack_picker = lambda: None
        self.assertTrue(self.controller.command("pack_choose", {})["ok"])
        self.assertIs(self.controller._pack, self.pack)
        def failure(_):
            raise ValueError("/private/secret-account/folder")
        self.controller._pack_picker = lambda: self.directory
        self.controller._pack_loader = failure
        self.controller.command("pack_choose", {})
        self.wait_for(lambda: not self.controller.get_state()["pack"]["busy"])
        state = self.controller.get_state()
        self.assertEqual(state["pack"]["phase"], "error")
        self.assertNotIn("/private", json.dumps(state))

    def test_inspection_needs_calibration_and_layout_but_no_input_permission_or_ack(self):
        self.loaded(False)
        self.assertFalse(self.controller.get_state()["pack"]["can_check"])
        self.controller._content_calibration = self.calibration
        self.assertTrue(self.controller.get_state()["pack"]["can_check"])
        self.assertFalse(self.controller.get_state()["session"]["acknowledged"])
        self.assertEqual(self.controller.get_state()["readiness"]["phase"], "blocked")
        self.controller._content_calibration = replace(self.calibration, viewport=(0, 0, 96, 60))
        self.assertFalse(self.controller.get_state()["pack"]["can_check"])
        self.controller._content_calibration = replace(self.calibration, viewport=(0, 0, 48, 32))
        self.assertFalse(self.controller.get_state()["pack"]["can_check"])

    def test_result_is_historical_exact_preview_with_raw_offset_boxes_and_no_input(self):
        self.loaded()
        self.controller._acknowledged = True
        self.controller._popup_state = "bank_reward"
        state = self.inspect()
        result = state["pack"]["inspection"]
        self.assertEqual(state["pack"]["phase"], "result")
        self.assertEqual(result["preview_id"], state["preview"]["id"])
        self.assertEqual((result["width"], result["height"]), (136, 94))
        self.assertEqual(result["anchors"][0]["box"], {"x": 31, "y": 24, "width": 16, "height": 16})
        self.assertTrue(result["historical"])
        self.assertEqual(state["preview"]["phase"], "historical")
        self.assertFalse(state["session"]["acknowledged"])
        self.assertEqual(state["popup"]["state"], "unknown")
        self.assertEqual((self.runner.starts, self.runner.routines), ([], []))
        result["anchors"][0]["id"] = "tampered"
        self.assertEqual(self.controller.get_state()["pack"]["inspection"]["anchors"][0]["id"], "gameplay")
        self.assertNotIn("pixels", json.dumps(state))

    def test_stop_close_and_target_change_revoke_inflight_result(self):
        for action in ("stop", "close", "target"):
            with self.subTest(action=action):
                self.loaded()
                entered, release = threading.Event(), threading.Event()
                outer = self
                class Operation:
                    def run(self, *_args, **_kwargs):
                        entered.set()
                        release.wait(2)
                        return outer.report  # Even a non-cooperative late callback is revoked.
                    def close(self):
                        pass
                self.controller._pack_session_factory = lambda *_: Operation()
                self.controller.command("pack_check", {})
                try:
                    self.assertTrue(entered.wait(1))
                    self.assertFalse(self.controller.command("start", {})["ok"])
                    if action == "close":
                        self.assertFalse(self.controller.close())
                    elif action == "target":
                        self.backend.targets = (TARGET_TWO,)
                        self.controller.command("refresh_targets", {})
                        self.controller._scan_thread.join(1)
                        self.controller.get_state()
                    else:
                        self.controller.command("stop", {})
                finally:
                    release.set()
                    self.controller._pack_thread.join(1)
                self.assertIsNone(self.controller.get_state()["pack"]["inspection"])
                if action == "close":
                    self.controller._closing = False  # Reuse only this fake controller for next case.

    def test_stale_or_changed_layout_clears_calibration_and_never_publishes(self):
        for code in ("stale", "layout_changed", "capture_failed"):
            self.loaded()
            state = self.inspect(error=PackInspectionError(code))
            self.assertIsNone(self.controller._content_calibration)
            self.assertIsNone(state["pack"]["inspection"])
            self.assertEqual(state["pack"]["phase"], "error")

    def test_inconsistent_report_is_rejected_before_preview_publication(self):
        self.loaded()
        for report in (replace(self.report, observed_frames=0), replace(self.report, required_frames=1),
                       replace(self.report, state=replace(self.report.state, state_id="foreign")),
                       replace(self.report, state=replace(self.report.state, kind="transaction"))):
            state = self.inspect(report=report)
            self.assertEqual(state["pack"]["phase"], "error")
            self.assertIsNone(state["pack"]["inspection"])

    def test_reference_clear_start_and_game_change_invalidate_results_preserve_cleanup_latch(self):
        self.loaded()
        for command in ("reset_area", "clear_preview", "pack_clear", "start"):
            self.controller._content_calibration = self.calibration
            self.controller._pack = self.pack
            self.controller._pack_phase = "ready"
            self.inspect()
            self.assertTrue(self.controller.command(command, {})["ok"])
            self.assertIsNone(self.controller.get_state()["pack"]["inspection"])
            self.runner.running = False
        self.runner.cleanup_failed = True
        state = self.controller.command("select_game", {"game_id": "blox"})
        # Unsupported profile selection still preserves the engine cleanup latch.
        self.assertTrue(state["ok"])
        self.assertTrue(self.runner.cleanup_failed)
        self.assertIsNone(state["state"]["pack"]["id"])
        self.assertIsNone(self.controller.get_state()["pack"]["inspection"])


if __name__ == "__main__":
    unittest.main()
