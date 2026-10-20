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

    def test_expired_match_keeps_editable_image_but_invalidates_observation(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        preview_id = self.capture_reference(controller)
        controller.command("check_area", {"preview_id": preview_id})
        self.jobs.jobs[-1][2].result = JobResult(frame=frame())
        self.assertEqual(controller.get_state()["preview"]["geometry"], "matched")
        self.clock.value = 10.6
        state = controller.get_state()
        self.assertEqual(state["preview"]["phase"], "historical")
        self.assertEqual(state["preview"]["geometry"], "historical")
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
        controller.command("check_area", {"preview_id": preview_id})
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

    def test_roi_is_16_by_9_and_exact_fresh_layout_calibrates(self) -> None:
        controller = self.make_controller((TARGET_ONE,))
        self.assertTrue(controller.command("capture", {})["ok"])
        self.jobs.jobs[-1][2].result = JobResult(frame=frame())
        state = controller.get_state()
        preview_id = state["preview"]["id"]
        self.assertFalse(controller.command("set_area", {
            "preview_id": preview_id, "rect": {"x": 0, "y": 0, "width": 10, "height": 9},
        })["ok"])
        self.assertTrue(controller.command("set_area", {
            "preview_id": preview_id, "rect": {"x": 0, "y": 0, "width": 16, "height": 9},
        })["ok"])
        self.assertTrue(controller.command("check_area", {"preview_id": preview_id})["ok"])
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
