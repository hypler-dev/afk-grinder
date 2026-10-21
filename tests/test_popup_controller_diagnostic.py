"""Synthetic controller coverage for strict popup diagnostic IPC."""

from __future__ import annotations

import threading
import unittest
from unittest.mock import patch

from afk_grinder.capture import CaptureDiagnostic
from afk_grinder.recognition.content_calibration import ContentCalibration
from afk_grinder.recognition.frame_geometry import layout_from_capture
from afk_grinder.recognition.popup_diagnostic import PopupDiagnostic
from tests import test_desktop_controller as _controller_tests


_PRIVATE_FAILURE = "/private/secret/chat OCR=account pixels=hidden"


class _SyntheticPopupSession:
    """Controller-only popup stand-in; it never opens capture or input APIs."""

    def __init__(self, calibration, *, report, record, clock, entered, release,
                 failure: PopupDiagnostic | None, fail: bool) -> None:
        self.calibration = calibration
        self.report = report
        self.record = record
        self.clock = clock
        self.entered = entered
        self.release = release
        self.failure = failure
        self.fail = fail
        self.closed = False

    def check(self, guard, wait) -> None:
        self.report("checking", _PRIVATE_FAILURE)
        self.entered.set()
        self.release.wait(1)
        if self.fail:
            raise RuntimeError(_PRIVATE_FAILURE)
        self.report("unknown", "Synthetic read-only popup check complete.")

    def close(self) -> None:
        self.closed = True


class _ForgedPopupDiagnostic(PopupDiagnostic):
    pass


class PopupControllerDiagnosticTests(unittest.TestCase):
    def make_controller(self, *, readiness=()):
        fixture = _controller_tests.DesktopControllerTests(methodName="runTest")
        controller = fixture.make_controller((_controller_tests.TARGET_ONE,), readiness)
        controller._content_calibration = ContentCalibration.manual(
            layout_from_capture(_controller_tests.frame()), (0, 0, 16, 9)
        )
        self.assertIsNotNone(controller._selected_id)
        return controller, fixture

    @staticmethod
    def _failure() -> PopupDiagnostic:
        return PopupDiagnostic(
            "capture",
            "timeout",
            CaptureDiagnostic("timeout", "screenshot", "timeout_error"),
        )

    @staticmethod
    def _set_failure(controller, diagnostic: object) -> None:
        controller._popup_phase = "result"
        controller._popup_state = "error"
        controller._popup_diagnostic = diagnostic

    def _session_factory(self, entered, release, *, failure=None, fail=False):
        def factory(calibration, *, report, record, clock):
            return _SyntheticPopupSession(
                calibration,
                report=report,
                record=record,
                clock=clock,
                entered=entered,
                release=release,
                failure=failure,
                fail=fail,
            )
        return factory

    def test_read_only_check_ignores_live_input_gates_and_exports_only_safe_failure(self):
        controller, _fixture = self.make_controller(readiness=(
            "Accessibility permission is required for native input control.",
            "Input Monitoring permission is required to read Escape emergency stop.",
        ))
        self.assertEqual(controller.get_state()["readiness"]["phase"], "blocked")
        self.assertEqual(controller.get_state()["session"]["acknowledged"], False)
        self.assertEqual(controller.get_state()["popup"]["can_check"], True)

        first_entered, first_release = threading.Event(), threading.Event()
        second_entered, second_release = threading.Event(), threading.Event()
        factories = iter((
            self._session_factory(first_entered, first_release, failure=self._failure(), fail=True),
            self._session_factory(second_entered, second_release),
        ))
        with patch("afk_grinder.popup_session.PopupSession", side_effect=lambda *args, **kwargs: next(factories)(*args, **kwargs)):
            self.assertTrue(controller.command("popup_check", {})["ok"])
            self.assertTrue(first_entered.wait(1))
            self.assertTrue(controller.get_state()["popup"]["busy"])
            first_release.set()
            controller._popup_thread.join(1)
            self.assertFalse(controller._popup_thread.is_alive())

            popup = controller.get_state()["popup"]
            self.assertEqual(popup["phase"], "result")
            self.assertEqual(popup["state"], "error")
            self.assertEqual(popup["message"], "Popup check stopped. Check capture, content area and local recognition setup.")
            self.assertEqual(popup["diagnostic"], {
                "stage": "capture",
                "code": "timeout",
                "capture": {"code": "timeout", "stage": "screenshot", "error_type": "timeout_error"},
            })
            self.assertNotIn("private", repr(popup))
            self.assertNotIn("OCR", repr(popup))
            self.assertEqual(set(popup["diagnostic"]), {"stage", "code", "capture"})

            self.assertTrue(controller.command("popup_check", {})["ok"])
            self.assertTrue(second_entered.wait(1))
            pending = controller.get_state()["popup"]
            self.assertTrue(pending["busy"])
            self.assertIsNone(pending["diagnostic"])
            second_release.set()
            controller._popup_thread.join(1)
            self.assertFalse(controller._popup_thread.is_alive())

    def test_payload_rejects_untyped_mutated_and_forged_diagnostics_and_does_not_alias(self):
        controller, _fixture = self.make_controller()
        valid = self._failure()
        self._set_failure(controller, valid)
        first = controller.get_state()["popup"]["diagnostic"]
        second = controller.get_state()["popup"]["diagnostic"]
        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first["capture"], second["capture"])
        first["capture"]["code"] = "mutated"
        self.assertEqual(controller.get_state()["popup"]["diagnostic"]["capture"]["code"], "timeout")

        for invalid in (
            {"stage": "capture", "code": "failed", "capture": {"raw": _PRIVATE_FAILURE}},
            _ForgedPopupDiagnostic("capture", "failed"),
        ):
            with self.subTest(kind=type(invalid).__name__):
                self._set_failure(controller, invalid)
                self.assertIsNone(controller.get_state()["popup"]["diagnostic"])

        self._set_failure(controller, valid)
        object.__setattr__(valid, "code", "forged")
        self.assertIsNone(controller.get_state()["popup"]["diagnostic"])

    def test_stop_reset_and_target_change_clear_failure_state(self):
        controller, _fixture = self.make_controller()
        self._set_failure(controller, self._failure())
        self.assertTrue(controller.command("stop", {})["ok"])
        self.assertIsNone(controller.get_state()["popup"]["diagnostic"])

        controller, _fixture = self.make_controller()
        self._set_failure(controller, self._failure())
        self.assertTrue(controller.command("reset_area", {})["ok"])
        self.assertIsNone(controller.get_state()["popup"]["diagnostic"])

        controller, fixture = self.make_controller()
        self._set_failure(controller, self._failure())
        controller._preview_frame = _controller_tests.frame()
        fixture.backend.targets = (_controller_tests.TARGET_TWO,)
        self.assertTrue(controller.command("refresh_targets", {})["ok"])
        controller._scan_thread.join(1)
        self.assertIsNone(controller.get_state()["popup"]["diagnostic"])

    def test_area_mutations_clear_failure_without_losing_the_new_reference(self):
        controller, _fixture = self.make_controller()
        layout = layout_from_capture(_controller_tests.frame())
        controller._preview_id = 7
        controller._preview_layout = layout
        controller._preview_phase = "available"
        self._set_failure(controller, self._failure())
        self.assertTrue(controller.command("set_area", {
            "preview_id": 7,
            "rect": {"x": 0, "y": 0, "width": 16, "height": 9},
        })["ok"])
        state = controller.get_state()
        self.assertEqual(state["preview"]["area"], {"x": 0, "y": 0, "width": 16, "height": 9})
        self.assertIsNone(state["popup"]["diagnostic"])

        self._set_failure(controller, self._failure())
        self.assertTrue(controller.command("check_area", {"preview_id": 7, "attested": True})["ok"])
        state = controller.get_state()
        self.assertEqual(state["preview"]["area"], {"x": 0, "y": 0, "width": 16, "height": 9})
        self.assertIsNone(state["popup"]["diagnostic"])

    def test_stop_before_blocked_resolve_keeps_popup_unknown_without_diagnostic(self):
        controller, fixture = self.make_controller()
        controller._popup_state = "bank_reward"
        self.assertTrue(controller.command("set_mode", {"mode": "live"})["ok"])
        entered, release = threading.Event(), threading.Event()

        def blocked_start(_routine, **kwargs):
            entered.set()
            release.wait(1)
            if kwargs["cancel_event"].is_set():
                raise RuntimeError(_PRIVATE_FAILURE)
            fixture.runner.running = True

        fixture.runner.start_routine = blocked_start
        response = []
        session_entered, session_release = threading.Event(), threading.Event()
        with patch(
            "afk_grinder.popup_session.PopupSession",
            side_effect=self._session_factory(session_entered, session_release),
        ):
            thread = threading.Thread(target=lambda: response.append(controller.command("popup_resolve", {})))
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(controller.command("stop", {})["ok"])
            finally:
                release.set()
                thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertFalse(response[0]["ok"])
        popup = controller.get_state()["popup"]
        self.assertEqual(popup["phase"], "idle")
        self.assertEqual(popup["state"], "unknown")
        self.assertIsNone(popup["diagnostic"])

    def test_late_worker_failure_cannot_restore_after_stop_calibration_or_target_invalidation(self):
        for action in ("stop", "calibration", "target"):
            with self.subTest(action=action):
                controller, fixture = self.make_controller()
                entered, release = threading.Event(), threading.Event()
                with patch(
                    "afk_grinder.popup_session.PopupSession",
                    side_effect=self._session_factory(entered, release, failure=self._failure(), fail=True),
                ):
                    self.assertTrue(controller.command("popup_check", {})["ok"])
                    self.assertTrue(entered.wait(1))
                    if action == "stop":
                        self.assertTrue(controller.command("stop", {})["ok"])
                    elif action == "calibration":
                        self.assertTrue(controller.command("clear_preview", {})["ok"])
                    else:
                        controller._preview_frame = _controller_tests.frame()
                        fixture.backend.targets = (_controller_tests.TARGET_TWO,)
                        self.assertTrue(controller.command("refresh_targets", {})["ok"])
                        controller._scan_thread.join(1)
                        controller.get_state()
                    release.set()
                    controller._popup_thread.join(1)
                    self.assertFalse(controller._popup_thread.is_alive())
                popup = controller.get_state()["popup"]
                self.assertEqual(popup["phase"], "idle")
                self.assertEqual(popup["state"], "unknown")
                self.assertIsNone(popup["diagnostic"])
                self.assertNotIn("private", repr(popup))


if __name__ == "__main__":
    unittest.main()
