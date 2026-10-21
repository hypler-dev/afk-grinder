"""Replay observation lifecycle with fakes only; no native capture/input."""

from types import SimpleNamespace
import unittest

from afk_grinder.session_recorder import SessionRecorder
from tests.test_popup_session import CAL, TARGET


class SessionRecorderTests(unittest.TestCase):
    def simulate(self, *, include=False, lose_focus=False, canceled=False):
        clock = SimpleNamespace(value=100.)
        cancel = SimpleNamespace(flag=canceled)
        cancel.is_set = lambda: cancel.flag
        cancel.set = lambda: setattr(cancel, "flag", True)
        cancel.wait = lambda seconds: setattr(clock, "value", clock.value + seconds)
        backend = SimpleNamespace(focus=TARGET, foreground=lambda: backend.focus,
                                  escape_pressed=lambda: False, readiness=lambda: [])
        queued, statuses, closed, stopped = [], [], [], []
        service = SimpleNamespace(submit=lambda *args: queued.append(args) or True,
                                  poll=lambda: {"settings": {"interval_seconds": 2}},
                                  observer_status=statuses.append, stop_session=stopped.append)
        class Operation:
            def __init__(self, *args, **kwargs): self.states = ["unknown", "protected"]
            def _warm(self, guard, wait): guard()
            def _observe(self, guard, wait):
                if lose_focus: backend.focus = None
                return "synthetic-frame", SimpleNamespace(state=self.states.pop(0))
            def close(self): closed.append(True)
        recorder = SessionRecorder(backend=backend, calibration=CAL, service=service,
                                   active=lambda: True, cancel=cancel, operation_factory=Operation,
                                   clock=lambda: clock.value)
        recorder._run()
        self.assertEqual(closed, [] if canceled else [True])
        self.assertEqual(len(stopped), 1)
        self.assertTrue(cancel.flag)
        return queued, statuses

    def test_unknown_frames_are_privacy_placeholders_and_protected_cancels_input(self):
        queued, statuses = self.simulate()
        self.assertEqual([task[-1] for task in queued], ["redacted_unknown", "redacted_restricted"])
        self.assertIn("skipping_unknown", statuses)
        self.assertEqual(statuses[-1], "blocked")

    def test_focus_loss_or_cancel_drops_late_frame_before_storage(self):
        for kwargs in ({"lose_focus": True}, {"canceled": True}):
            self.assertEqual(self.simulate(include=True, **kwargs)[0], [])

class RecorderDeadlineTests(unittest.TestCase):
    def run_case(self, *, warm_delay=0, observe_delay=0, cancel_on="", factory_error=False,
                 close_error=False):
        clock = SimpleNamespace(value=100.)
        cancel = SimpleNamespace(flag=False)
        cancel.is_set = lambda: cancel.flag
        cancel.set = lambda: setattr(cancel, "flag", True)
        cancel.wait = lambda seconds: setattr(clock, "value", clock.value + seconds)
        backend = SimpleNamespace(foreground=lambda: TARGET, escape_pressed=lambda: False, readiness=lambda: [])
        queued, statuses, closed, stopped, observed = [], [], [], [], []
        def submit(*args):
            queued.append(args)
            if cancel_on == "submit": cancel.set()
            return True
        def poll():
            if cancel_on == "poll": cancel.set()
            return {"settings": {"interval_seconds": 2}}
        service = SimpleNamespace(submit=submit, poll=poll,
                                  observer_status=statuses.append, stop_session=stopped.append)
        class Operation:
            def __init__(self, *args, **kwargs):
                if factory_error: raise RuntimeError("Synthetic startup failure")
            def _warm(self, guard, wait): clock.value += warm_delay
            def _observe(self, guard, wait):
                observed.append(clock.value)
                clock.value += observe_delay
                return "synthetic-frame", SimpleNamespace(state="unknown" if len(observed) == 1 else "protected")
            def close(self):
                closed.append(True)
                if close_error: raise RuntimeError("Synthetic cleanup failure")
        recorder = SessionRecorder(backend=backend, calibration=CAL, service=service,
                                   active=lambda: True, cancel=cancel, operation_factory=Operation,
                                   clock=lambda: clock.value)
        recorder._run()
        self.assertEqual(len(stopped), 1)
        self.assertTrue(cancel.flag)
        self.assertEqual(closed, [] if factory_error else [True])
        return queued, statuses, observed, clock.value

    def test_warm_capture_and_outer_deadlines_drop_late_frames(self):
        for kwargs in ({"warm_delay": 15.1}, {"observe_delay": 11.1}, {"observe_delay": 28}):
            with self.subTest(kwargs=kwargs):
                queued, statuses, _, _ = self.run_case(**kwargs)
                self.assertEqual(queued, [])
                self.assertEqual(statuses[-1], "error")

    def test_cancel_during_service_callbacks_stops_later_admission(self):
        for callback in ("submit", "poll"):
            queued, statuses, observed, _ = self.run_case(cancel_on=callback)
            self.assertEqual(len(queued), 1)
            self.assertEqual(len(observed), 1)
            self.assertEqual(statuses[-1], "stopped")
            if callback == "submit":
                self.assertNotIn("skipping_unknown", statuses)

    def test_factory_and_cleanup_errors_still_end_storage_session(self):
        for kwargs in ({"factory_error": True}, {"close_error": True}):
            queued, statuses, _, _ = self.run_case(**kwargs)
            self.assertEqual(statuses[-1], "error")
            self.assertEqual(statuses.count("error"), 1)

    def test_countdown_and_interval_share_outer_budget(self):
        queued, statuses, observed, ended_at = self.run_case()
        self.assertEqual([item[-1] for item in queued], ["redacted_unknown", "redacted_restricted"])
        self.assertAlmostEqual(observed[0], 103.)
        self.assertAlmostEqual(observed[1] - observed[0], 2.)
        self.assertEqual(statuses[-1], "blocked")
        self.assertLess(ended_at, 130.)


if __name__ == "__main__":
    unittest.main()
