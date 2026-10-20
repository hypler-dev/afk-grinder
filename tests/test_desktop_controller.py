"""Controller checks with fakes only; no native input, capture, or UI imports."""

from __future__ import annotations

from pathlib import Path
import queue
import sys
import threading
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afk_grinder.capture import CapturedWindow
from afk_grinder.capture.service import JobResult
from afk_grinder.desktop_controller import DesktopController
from afk_grinder.engine import Status
from afk_grinder.models import Target
from afk_grinder.recognition.content_calibration import ContentCalibration
from afk_grinder.recognition.frame_geometry import layout_from_capture


TARGET_ONE = Target(11, "101", "RobloxPlayerBeta.exe", "win32")
TARGET_TWO = Target(12, "202", "RobloxPlayer.exe", "win32")


class FakeBackend:
    def __init__(self, targets=(), readiness=()) -> None:
        self.targets = tuple(targets)
        self.readiness_problems = tuple(readiness)

    def discover_targets(self):
        return self.targets

    def readiness(self):
        return list(self.readiness_problems)


class FakeRunner:
    def __init__(self) -> None:
        self.events = queue.Queue()
        self.running = False
        self.cleanup_failed = False
        self.starts = []
        self.stops = 0
        self.routines = []

    def start(self, workflow, *, target=None, dry_run=True, armed=False, cancel_event=None) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Start was canceled.")
        if self.running:
            raise RuntimeError("already running")
        self.starts.append((workflow, target, dry_run, armed))
        self.running = True

    def stop(self) -> None:
        self.stops += 1
        self.running = False

    def start_routine(self, routine, **kwargs):
        self.routines.append((routine, kwargs))
        self.running = True


class FakeJob:
    def __init__(self, result=None) -> None:
        self.result = result
        self.cancelled = False

    def poll(self):
        result, self.result = self.result, None
        return result

    def cancel(self) -> None:
        self.cancelled = True


class FakeJobs:
    def __init__(self) -> None:
        self.jobs = []

    def __call__(self, operation, target=None):
        job = FakeJob()
        self.jobs.append((operation, target, job))
        return job


class Clock:
    def __init__(self) -> None:
        self.value = 10.0

    def __call__(self) -> float:
        return self.value


def frame(target=TARGET_ONE, *, captured_at=10.0, native_rect=(0, 0, 16, 9)) -> CapturedWindow:
    return CapturedWindow(
        target=target,
        window_id="window",
        native_rect=native_rect,
        physical_size=(16, 9),
        monitor_id="display",
        scale=(1.0, 1.0),
        pixels=bytes([1, 2, 3]) * (16 * 9),
        format="BGR8",
        captured_at=captured_at,
    )


class DesktopControllerTests(unittest.TestCase):
    def test_recorder_starts_only_for_live_enabled_calibrated_session_and_ticket_is_scoped(self):
        for mode, enabled, calibrated in (("dry", True, True), ("live", False, True),
                                          ("live", True, False), ("live", True, True)):
            with self.subTest(mode=mode, enabled=enabled, calibrated=calibrated):
                controller = self.make_controller((TARGET_ONE,))
                created = []
                class Recorder:
                    def __init__(self, **kwargs):
                        created.append(kwargs)
                    def start(self): pass
                controller._recorder_factory = Recorder
                controller._replay_service = SimpleNamespace(
                    poll=lambda: {"settings": {"enabled": enabled}, "frame": None}, close=lambda: None)
                controller.command("set_mode", {"mode": mode})
                if calibrated:
                    controller._content_calibration = ContentCalibration.manual(layout_from_capture(frame()), (0, 0, 16, 9))
                controller.command("set_ack", {"acknowledged": True})
                result = controller.command("start", {})
                if mode == "live" and enabled and not calibrated:
                    self.assertFalse(result["ok"])
                    self.assertEqual(created, [])
                    continue
                self.assertTrue(result["ok"])
                self.assertEqual(len(created), int(mode == "live" and enabled))
                if created:
                    ticket = created[0]["cancel"]
                    self.assertIs(ticket, controller._start_cancel)
                    self.assertTrue(created[0]["active"]())
                    controller._start_cancel = threading.Event()
                    self.assertFalse(created[0]["active"]())
                    controller._start_cancel = ticket
                    controller.command("stop", {})
                    self.assertTrue(ticket.is_set())

    def test_popup_bridge_live_gates_and_stop_ticket(self):
        controller = self.make_controller((TARGET_ONE,))
        controller._content_calibration = ContentCalibration.manual(layout_from_capture(frame()), (0, 0, 16, 9))
        controller._popup_state = "bank_reward"
        self.assertFalse(controller.command("popup_resolve", {})["ok"])
        self.assertTrue(controller.command("set_mode", {"mode": "live"})["ok"])
        for state in ("protected", "unknown", "error"):
            controller._popup_state = state
            self.assertFalse(controller.command("popup_resolve", {})["ok"])
        controller._popup_state = "disconnected"
        self.assertFalse(controller.command("popup_resolve", {})["ok"])
        self.assertTrue(controller.command("set_reconnect", {"enabled": True})["ok"])
        self.runner.cleanup_failed = True
        self.assertFalse(controller.command("popup_resolve", {})["ok"])
        self.runner.cleanup_failed = False
        controller._readiness_phase = "blocked"
        self.assertFalse(controller.command("popup_resolve", {})["ok"])
        controller._readiness_phase = "ready"
        self.assertTrue(controller.command("popup_resolve", {})["ok"])
        self.assertEqual(len(self.runner.routines), 1)
        _, kwargs = self.runner.routines[0]
        self.assertEqual(kwargs["target"], TARGET_ONE)
        self.assertTrue(kwargs["armed"])
        self.assertFalse(kwargs["cancel_event"].is_set())
        self.assertTrue(controller.command("stop", {})["ok"])
        self.assertTrue(kwargs["cancel_event"].is_set())
        self.assertEqual(controller.get_state()["popup"]["state"], "unknown")

    def test_stop_revokes_popup_start_while_native_readiness_is_blocked(self):
        controller = self.make_controller((TARGET_ONE,))
        controller._content_calibration = ContentCalibration.manual(layout_from_capture(frame()), (0, 0, 16, 9))
        controller._popup_state = "bank_reward"
        controller.command("set_mode", {"mode": "live"})
        entered, release = threading.Event(), threading.Event()
        def blocked(routine, **kwargs):
            entered.set()
            release.wait(1)
            if kwargs["cancel_event"].is_set():
                raise RuntimeError("Canceled")
            self.runner.routines.append((routine, kwargs))
        self.runner.start_routine = blocked
        response = []
        thread = threading.Thread(target=lambda: response.append(controller.command("popup_resolve", {})))
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertTrue(controller.command("stop", {})["ok"])
            self.assertTrue(controller._start_cancel.is_set())
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertFalse(response[0]["ok"])
        self.assertEqual(self.runner.routines, [])

    def test_replay_bridge_keeps_images_out_of_state_and_rejects_paths(self):
        controller = self.make_controller((TARGET_ONE,))
        fid = "a" * 32
        commands = []
        controller._replay_service = SimpleNamespace(poll=lambda: {
            "settings": {}, "frame": {"frame_id": fid, "data_url": "data:image/webp;base64,ZmFrZQ=="}},
            command=lambda *args: commands.append(args) or True, close=lambda: None)
        self.assertNotIn("data_url", repr(controller.get_state()))
        self.assertIn("data_url", controller.get_preview({"replay_frame_id": fid}))
        self.assertIsNone(controller.get_preview({"replay_frame_id": "../private"}))
        self.assertFalse(controller.command("replay_select", {"session_id": "../private"})["ok"])
        self.assertFalse(controller.command("replay_settings", {"settings": {"enabled": True}})["ok"])
        self.assertEqual(commands, [])
        self.assertTrue(controller.command("replay_older", {"session_id": fid})["ok"])
        self.assertTrue(controller.command("replay_sessions", {"older": True})["ok"])
        self.assertEqual(commands, [("older", fid), ("sessions", True)])
    def test_background_refresh_keeps_ambiguous_choices_visible(self) -> None:
        controller = self.make_controller((TARGET_ONE, TARGET_TWO))
        before = controller.get_state()["binding"]
        entered, release = threading.Event(), threading.Event()
        original = self.backend.discover_targets
        def delayed():
            entered.set()
            release.wait(1)
            return original()
        self.backend.discover_targets = delayed
        try:
            state = controller.command("refresh_targets", {})["state"]
            self.assertTrue(entered.wait(1))
            self.assertEqual(state["binding"], before)
        finally:
            release.set()
            controller._scan_thread.join(1)

    def capture_reference(self, controller, captured_at=10.0):
        controller.command("capture", {})
        self.jobs.jobs[-1][2].result = JobResult(frame=frame(captured_at=captured_at))
        state = controller.get_state()
        preview_id = state["preview"]["id"]
        self.assertTrue(controller.command("set_area", {
            "preview_id": preview_id, "rect": {"x": 0, "y": 0, "width": 16, "height": 9},
        })["ok"])
        return preview_id

    def test_slow_capture_is_editable_history_without_current_geometry(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        preview_id = self.capture_reference(controller, captured_at=9.0)
        state = controller.get_state()
        self.assertEqual(state["preview"]["phase"], "historical")
        self.assertIsNone(state["preview"]["error"])
        self.assertEqual(state["preview"]["id"], preview_id)
        self.assertIsNotNone(state["preview"]["area"])
        self.assertIsNotNone(controller._preview_frame)
        self.assertIsNone(controller._tracker.latest)
        self.assertIsNone(controller._tracker.calibration)

    def test_preview_preparation_errors_have_safe_stage_and_drop_pixels(self) -> None:
        for operation, stage in (("layout_from_capture", "preview_geometry"),
                                 ("_encode_preview_async", "preview_encoding")):
            with self.subTest(operation=operation):
                controller = self.make_controller((TARGET_ONE,))
                controller.command("capture", {})
                self.jobs.jobs[-1][2].result = JobResult(frame=frame())
                target = ("afk_grinder.desktop_controller.layout_from_capture" if operation == "layout_from_capture"
                          else "afk_grinder.desktop_controller.DesktopController._encode_preview_async")
                with patch(target, side_effect=ValueError("/private/person/window-title")):
                    preview = controller.get_state()["preview"]
                self.assertEqual(preview["phase"], "error")
                self.assertEqual(preview["error"]["stage"], stage)
                self.assertEqual(preview["error"]["error_type"], "value_error")
                self.assertNotIn("/private", str(preview))
                self.assertIsNone(controller._preview_frame)
                self.assertIsNone(controller._preview_layout)
                self.assertIsNone(controller._tracker.latest)

    def test_async_encoder_failure_drops_preview_and_geometry(self) -> None:
        class ImmediateThread:
            def __init__(self, *, target, **kwargs):
                self.target = target

            def start(self):
                self.target()

        controller = self.make_controller((TARGET_ONE,))
        controller.command("capture", {})
        self.jobs.jobs[-1][2].result = JobResult(frame=frame())
        with patch("afk_grinder.desktop_controller.threading.Thread", ImmediateThread), \
             patch("afk_grinder.desktop_controller._png_data_url", side_effect=ValueError("/private/person/window")):
            controller.get_state()
            preview = controller.get_state()["preview"]
        self.assertEqual(preview["phase"], "error")
        self.assertEqual(preview["error"]["code"], "conversion")
        self.assertEqual(preview["error"]["stage"], "preview_encoding")
        self.assertNotIn("/private", str(preview))
        self.assertIsNone(controller._preview_frame)
        self.assertIsNone(controller._preview_layout)
        self.assertIsNone(controller._preview_png)
        self.assertIsNone(controller._tracker.latest)

    def test_expired_match_keeps_editable_image_but_invalidates_observation(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        preview_id = self.capture_reference(controller)
        controller.command("check_area", {"preview_id": preview_id, "attested": True})
        self.jobs.jobs[-1][2].result = JobResult(frame=frame())
        self.assertEqual(controller.get_state()["preview"]["geometry"], "matched")
        self.clock.value = 10.6
        state = controller.get_state()
        self.assertEqual(state["preview"]["phase"], "historical")
        self.assertEqual(state["preview"]["geometry"], "matched")
        self.assertIsNotNone(controller._content_calibration)
        self.assertIsNotNone(controller._preview_frame)
        self.assertIsNone(controller._tracker.latest)
        self.assertIsNone(controller._tracker.calibration)
        self.assertTrue(controller.command("set_area", {
            "preview_id": state["preview"]["id"], "rect": state["preview"]["area"],
        })["ok"])

    def test_stale_reference_check_and_future_frame_fail_closed(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        preview_id = self.capture_reference(controller)
        self.clock.value = 10.6
        controller.command("check_area", {"preview_id": preview_id, "attested": True})
        self.assertIsNone(controller._preview_frame)
        self.assertIsNone(controller._preview_layout)
        self.jobs.jobs[-1][2].result = JobResult(frame=frame())
        state = controller.get_state()
        self.assertEqual(state["preview"]["phase"], "error")
        self.assertIsNone(state["preview"]["area"])
        controller.command("capture", {})
        self.jobs.jobs[-1][2].result = JobResult(frame=frame(captured_at=11.0))
        self.assertEqual(controller.get_state()["preview"]["phase"], "error")
        self.assertIsNone(controller._tracker.latest)

    def test_native_scan_failure_stops_live_but_does_not_cancel_dry_run(self) -> None:
        for mode in ("dry", "live"):
            with self.subTest(mode=mode):
                controller = self.make_controller((TARGET_ONE,))
                controller.command("set_mode", {"mode": mode})
                if mode == "live":
                    controller.command("set_ack", {"acknowledged": True})
                self.assertTrue(controller.command("start", {})["ok"])
                controller._scan_queue.put_nowait(SimpleNamespace(
                    generation=controller._scan_generation, targets=(), readiness=(), error=True))
                controller.get_state()
                self.assertEqual(self.runner.running, mode == "dry")
                self.assertEqual(controller._start_cancel.is_set(), mode == "live")

    def test_current_preview_replaces_queued_stale_png(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        controller._preview_id = 2
        controller._png_queue.put_nowait((1, "old"))
        def immediate_thread(*, target, **kwargs):
            return SimpleNamespace(start=target)
        with patch("afk_grinder.desktop_controller.threading.Thread", side_effect=immediate_thread), \
                patch("afk_grinder.desktop_controller._png_data_url", return_value="current"):
            controller._encode_preview_async(2, frame())
            controller._encode_preview_async(1, frame())
        controller.get_state()
        self.assertEqual(controller.get_preview(2), {"id": 2, "data_url": "current"})

    def test_stop_and_close_cancel_a_pending_start(self) -> None:
        for action in ("stop", "close"):
            with self.subTest(action=action):
                controller = self.make_controller((TARGET_ONE,))
                entered, release = threading.Event(), threading.Event()
                original = self.runner.start
                def delayed_start(*args, **kwargs):
                    entered.set()
                    release.wait(1)
                    return original(*args, **kwargs)
                self.runner.start = delayed_start
                thread = threading.Thread(target=lambda: controller.command("start", {}))
                thread.start()
                self.assertTrue(entered.wait(1))
                if action == "stop":
                    self.assertTrue(controller.command("stop", {})["ok"])
                else:
                    self.assertFalse(controller.close())
                release.set()
                thread.join(1)
                self.assertFalse(thread.is_alive())
                self.assertEqual(self.runner.starts, [])
                self.assertFalse(self.runner.running)

    def test_live_rejected_attempt_consumes_ack_and_uncheck_revokes(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        controller.command("set_mode", {"mode": "live"})
        controller.command("set_ack", {"acknowledged": True})
        self.assertTrue(controller.command("set_ack", {"acknowledged": False})["ok"])
        self.assertFalse(controller.get_state()["session"]["acknowledged"])
        controller.command("set_ack", {"acknowledged": True})
        self.assertFalse(controller.command("start", {"unexpected": 1})["ok"])
        self.assertFalse(controller.get_state()["session"]["acknowledged"])
        controller.command("set_ack", {"acknowledged": True})
        self.runner.cleanup_failed = True
        self.assertFalse(controller.command("start", {})["ok"])
        self.assertFalse(controller.get_state()["session"]["acknowledged"])

    def test_candidate_ids_do_not_retarget_and_explicit_choice_survives_scan(self) -> None:
        controller = self.make_controller((TARGET_ONE, TARGET_TWO))
        choice = next(key for key, target in controller._targets.items() if target == TARGET_ONE)
        controller.command("select_target", {"target_id": choice})
        self.assertEqual(self.refresh(controller)["binding"]["selected_id"], choice)
        self.backend.targets = (TARGET_TWO,)
        self.refresh(controller)
        self.assertFalse(controller.command("select_target", {"target_id": choice})["ok"])

    def test_reference_mutations_block_during_input_and_unsupported_sdk_blocks(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        self.runner.running = True
        self.assertFalse(controller.command("reset_area", {})["ok"])
        self.assertFalse(controller.command("clear_preview", {})["ok"])
        self.assertFalse(controller.command("set_area", {"preview_id": 1, "rect": {}})["ok"])
        self.runner.running = False
        controller.command("select_game", {"game_id": "bee"})
        self.assertFalse(controller.command("sdk_check", {})["ok"])
        self.assertEqual(controller.get_state()["binding"]["phase"], "unsupported")

    def make_controller(self, targets=(), readiness=()):
        self.backend = FakeBackend(targets, readiness)
        self.runner = FakeRunner()
        self.jobs = FakeJobs()
        self.clock = Clock()
        controller = DesktopController(
            backend=self.backend,
            runner=self.runner,
            job_factory=self.jobs,
            clock=self.clock,
            buildmetadata={"version": "test", "commit": "abc", "platform": "test"},
        )
        controller._scan_thread.join(1)
        controller.get_state()
        return controller

    def refresh(self, controller) -> dict:
        controller.command("refresh_targets", {})
        controller._scan_thread.join(1)
        return controller.get_state()

    def test_zero_one_multiple_and_target_change(self) -> None:
        controller = self.make_controller()
        self.assertEqual(controller.get_state()["binding"]["phase"], "missing")

        self.backend.targets = (TARGET_ONE,)
        state = self.refresh(controller)
        self.assertEqual(state["binding"]["phase"], "bound")
        self.assertEqual(len(state["binding"]["candidates"]), 1)

        self.backend.targets = (TARGET_ONE, TARGET_TWO)
        state = self.refresh(controller)
        self.assertEqual(state["binding"]["phase"], "multiple")
        self.assertIsNone(state["binding"]["selected_id"])
        choice = state["binding"]["candidates"][1]["id"]
        self.assertTrue(controller.command("select_target", {"target_id": choice})["ok"])
        self.assertEqual(controller.get_state()["binding"]["selected_id"], choice)

    def test_live_ack_is_consumed_before_start_and_dry_needs_no_target(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        self.assertTrue(controller.command("start", {})["ok"])
        self.assertEqual(self.runner.starts[0][2], True)
        self.runner.stop()

        self.assertTrue(controller.command("set_mode", {"mode": "live"})["ok"])
        self.assertTrue(controller.command("set_ack", {"acknowledged": True})["ok"])
        response = controller.command("start", {})
        self.assertTrue(response["ok"])
        self.assertFalse(response["state"]["session"]["acknowledged"])
        self.assertEqual(self.runner.starts[-1][2:], (False, True))

    def test_unsupported_cleanup_latch_double_start_and_stop_priority(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        self.assertTrue(controller.command("select_game", {"game_id": "bee"})["ok"])
        self.assertFalse(controller.command("capture", {})["ok"])
        self.assertFalse(controller.command("start", {})["ok"])
        self.assertTrue(controller.command("select_game", {"game_id": "adopt"})["ok"])
        self.runner.cleanup_failed = True
        self.assertFalse(controller.command("start", {})["ok"])
        self.runner.cleanup_failed = False
        self.assertTrue(controller.command("start", {})["ok"])
        self.assertFalse(controller.command("start", {})["ok"])
        self.assertTrue(controller.command("stop", {})["ok"])
        self.assertGreaterEqual(self.runner.stops, 1)

    def test_strict_payloads_reject_bool_numbers_and_unknown_fields(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        self.assertFalse(controller.command("set_mode", {"mode": "dry", "extra": 1})["ok"])
        self.assertFalse(controller.command("set_ack", {"acknowledged": 1})["ok"])
        self.assertFalse(controller.command("set_area", {"preview_id": True, "rect": {}})["ok"])
        self.assertFalse(controller.command("unknown", {})["ok"])

    def test_capture_result_has_no_pixels_in_state_and_safe_diagnostics(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        self.assertTrue(controller.command("capture", {})["ok"])
        self.jobs.jobs[-1][2].result = JobResult(frame=frame())
        state = controller.get_state()
        self.assertEqual(state["preview"]["phase"], "available")
        self.assertNotIn("pixels", repr(state))
        self.assertIsNone(controller.get_preview(state["preview"]["id"] + 1))

        self.assertTrue(controller.command("capture", {})["ok"])
        self.jobs.jobs[-1][2].result = JobResult(error="private path /secret")
        state = controller.get_state()
        self.assertEqual(state["preview"]["error"]["message"], "Preview failed. No input was sent.")
        self.assertNotIn("secret", repr(state))

    def test_late_capture_for_changed_target_is_rejected(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        self.assertTrue(controller.command("capture", {})["ok"])
        self.backend.targets = (TARGET_TWO,)
        self.refresh(controller)
        self.jobs.jobs[-1][2].result = JobResult(frame=frame(TARGET_ONE))
        state = controller.get_state()
        self.assertEqual(state["preview"]["phase"], "error")

    def test_arbitrary_aspect_requires_attestation_and_fresh_exact_layout(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        self.assertTrue(controller.command("capture", {})["ok"])
        self.jobs.jobs[-1][2].result = JobResult(frame=frame())
        state = controller.get_state()
        preview_id = state["preview"]["id"]
        self.assertFalse(controller.command("set_area", {
            "preview_id": preview_id, "rect": {"x": 0, "y": 0, "width": 0, "height": 9},
        })["ok"])
        self.assertTrue(controller.command("set_area", {
            "preview_id": preview_id, "rect": {"x": 0, "y": 0, "width": 16, "height": 9},
        })["ok"])
        self.assertFalse(controller.command("check_area", {"preview_id": preview_id, "attested": False})["ok"])
        self.assertTrue(controller.command("check_area", {"preview_id": preview_id, "attested": True})["ok"])
        self.jobs.jobs[-1][2].result = JobResult(frame=frame())
        self.assertEqual(controller.get_state()["preview"]["geometry"], "matched")

    def test_runner_events_consume_ack_and_close_is_nonblocking(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        controller.command("set_ack", {"acknowledged": True})
        self.runner.events.put(Status("completed", "ignored raw event"))
        self.assertFalse(controller.get_state()["session"]["acknowledged"])
        controller.close()
        self.assertTrue(controller._close_stop_done.wait(1))
        self.assertTrue(controller.close())
        self.assertFalse(controller.command("set_mode", {"mode": "dry"})["ok"])
