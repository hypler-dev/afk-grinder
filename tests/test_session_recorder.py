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
        self.assertEqual(closed, [True])
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


if __name__ == "__main__":
    unittest.main()
