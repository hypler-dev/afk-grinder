"""Synthetic popup evidence and guarded coordination; no game captures/input."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest

from afk_grinder.capture import CapturedWindow
from afk_grinder.models import Target
from afk_grinder.popup_session import PopupSession
from afk_grinder.recognition.adopt_me import Stability, inspect
from afk_grinder.recognition.content_calibration import ContentCalibration
from afk_grinder.recognition.matcher import LabelHit
from afk_grinder.recognition.observation import Layout, Observation, Rect

TARGET = Target(123, "123", "RobloxPlayer", "com.roblox.RobloxPlayer")
RAW = Layout(TARGET, "456", Rect(-900, 40, 800, 600), (800, 600), "display", (1., 1.),
             region_kind="window-unverified", content_verified=False)
CAL = ContentCalibration.manual(RAW, (0, 0, 800, 600))


def synthetic(state="disconnected", sequence=1, captured_at=100.):
    pixels = bytearray(bytes((55, 55, 55)) * 800 * 600)
    style = (245, 245, 245) if state == "disconnected" else (50, 180, 60)
    for y in range(390, 438):
        for x in range(400, 580):
            pixels[(y * 800 + x) * 3:(y * 800 + x) * 3 + 3] = bytes(style)
    frame = CAL.crop(Observation(RAW, captured_at, 1, sequence, bytes(pixels)))
    if state == "disconnected":
        labels = [("disconnected", (320, 180, 150, 28)), ("leave", (220, 405, 55, 17)),
                  ("reconnect", (440, 405, 90, 17)), ("idle_reason", (240, 290, 320, 20)),
                  ("idle_code", (340, 320, 120, 20))]
    else:
        labels = [("bank", (350, 180, 80, 28)), ("bank_reason", (290, 290, 220, 20)),
                  ("cash_out", (440, 405, 90, 17))]
    return frame, tuple(LabelHit(label, .99, box) for label, box in labels)


class PopupPolicyTests(unittest.TestCase):
    def test_two_complete_allowlisted_profiles_and_stability(self):
        for state in ("disconnected", "bank_reward"):
            frame, hits = synthetic(state)
            evidence = inspect(frame, hits, now=100.1)
            self.assertEqual(evidence.state, state)
            self.assertEqual(evidence.point, (490., 414.))
            stability = Stability()
            self.assertFalse(stability.accept(evidence))
            self.assertFalse(stability.accept(evidence))
            next_evidence = inspect(replace(frame, sequence=2, captured_at=100.2), hits, now=100.3)
            self.assertTrue(stability.accept(next_evidence))

    def test_protected_low_confidence_overrides_complete_popup(self):
        frame, hits = synthetic()
        result = inspect(frame, hits + (LabelHit("protected", .3, (1, 1, 20, 10)),), now=100.)
        self.assertEqual(result.state, "protected")
        self.assertIsNone(result.button)
        result = inspect(frame, hits + (LabelHit("protected_trade", .99, (1, 1, 20, 10)),
                                       LabelHit("protected_login", .9, (30, 1, 20, 10))), now=100.)
        self.assertEqual(result.privacy, "login")

    def test_stale_raw_ambiguous_missing_reason_bad_button_and_invalid_metadata_block(self):
        frame, hits = synthetic()
        variants = [
            (frame, hits, 100.51),
            (replace(frame, layout=RAW), hits, 100.),
            (frame, hits + (hits[0],), 100.),
            (frame, tuple(hit for hit in hits if hit.label_id != "idle_code"), 100.),
            (replace(frame, pixels=bytes((55, 55, 55)) * 800 * 600), hits, 100.),
            (frame, (LabelHit("reconnect", float("nan"), (1, 1, 20, 10)),), 100.),
            (frame, (LabelHit("reconnect", .99, (-1, 1, 20, 10)),), 100.),
        ]
        for observation, labels, now in variants:
            self.assertIsNone(inspect(observation, labels, now=now).button)


class PopupCoordinatorTests(unittest.TestCase):
    def run_operation(self, states, *, allow=True, geometry_error=False, stop_before_click=False):
        clock = SimpleNamespace(value=100.)
        reports, clicks, records = [], [], []
        labels = []
        jobs = []
        captures = list(states)
        def capture_factory(*args, **kwargs):
            state = captures.pop(0)
            frame, hits = synthetic(state if state in {"bank_reward", "disconnected"} else "disconnected",
                                    captured_at=clock.value)
            labels.append(hits if state in {"bank_reward", "disconnected"} else
                          ((LabelHit("protected", .99, (1, 1, 20, 10)),) if state == "protected" else ()))
            raw = CapturedWindow(TARGET, RAW.window_id, (-900, 40, 800, 600), (800, 600), "display",
                                 (1., 1.), frame.pixels, "BGR8", clock.value,
                                 "window-unverified", False)
            job = SimpleNamespace(poll=lambda: SimpleNamespace(frame=raw, error=""),
                                  cancel=lambda: None)
            jobs.append(job)
            return job
        class Recognition:
            ready = True
            def start(self): pass
            def submit(self, *args, **kwargs): pass
            def poll(self): return SimpleNamespace(hits=labels.pop(0), error="")
            def close(self): pass
        class Capability:
            def guard(self): pass
            def wait(self, seconds): clock.value += seconds
            def click(self, point, authorize):
                if stop_before_click:
                    raise RuntimeError("Stopped")
                authorize()
                clicks.append(point)
        def geometry(layout):
            self.assertEqual(layout, RAW)
            if geometry_error:
                raise RuntimeError("Layout changed")
        operation = PopupSession(CAL, report=lambda *args: reports.append(args),
                                 record=lambda *args: records.append(args), capture_factory=capture_factory,
                                 recognition_factory=lambda *_: Recognition(), clock=lambda: clock.value,
                                 geometry_check=geometry, models=lambda: Path("unused"))
        if geometry_error or stop_before_click:
            with self.assertRaises(RuntimeError):
                operation.resolve(Capability(), allow_reconnect=allow)
        else:
            operation.resolve(Capability(), allow_reconnect=allow)
        self.assertIsNone(operation._recognition)
        self.assertIsNone(operation._capture)
        return reports, clicks, records, jobs

    def test_one_click_then_fresh_checks_never_resume_actions(self):
        reports, clicks, records, jobs = self.run_operation(["disconnected", "disconnected", "unknown", "unknown"])
        self.assertEqual(clicks, [(-410., 454.)])
        self.assertEqual(reports[-1][0], "reconnect_requested")
        self.assertEqual([item[1] for item in records],
                         ["disconnected", "disconnected", "redacted_unknown", "redacted_unknown"])
        self.assertEqual(len(jobs), 4)

    def test_reconnect_off_protected_unknown_and_remained_popup_block(self):
        for states, allow in [(["disconnected"], False), (["protected"], True), (["unknown"], True)]:
            self.assertEqual(self.run_operation(states, allow=allow)[1], [])
        reports, clicks, _, jobs = self.run_operation(["bank_reward", "bank_reward", "bank_reward"])
        self.assertEqual(len(clicks), 1)
        self.assertEqual(reports[-1][0], "blocked")
        self.assertEqual(len(jobs), 3)

    def test_geometry_change_or_cancellation_prevents_click(self):
        for kwargs in ({"geometry_error": True}, {"stop_before_click": True}):
            self.assertEqual(self.run_operation(["disconnected", "disconnected"], **kwargs)[1], [])


if __name__ == "__main__":
    unittest.main()
