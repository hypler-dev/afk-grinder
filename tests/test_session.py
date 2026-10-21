from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afk_grinder.session import BoundedSession, SessionError


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


def session(clock, *, guard=lambda: None, wait=None, seconds=1.0):
    if wait is None:
        wait = lambda duration: setattr(clock, "value", clock.value + duration)
    return BoundedSession(guard, wait, clock=clock, session_seconds=seconds)


class BoundedSessionTests(unittest.TestCase):
    def assert_code(self, code, callback):
        with self.assertRaises(SessionError) as raised:
            callback()
        self.assertEqual(raised.exception.code, code)

    def test_outer_and_phase_expiry_are_terminal(self):
        clock = FakeClock()
        outer = session(clock, seconds=.05)
        self.assert_code("timeout", lambda: outer.wait(.05))
        self.assert_code("timeout", outer.guard)

        clock = FakeClock()
        phased = session(clock, seconds=1)
        phase = phased.phase("observe", .03)
        self.assert_code("timeout", lambda: phase.wait(.03))
        self.assert_code("timeout", phased.guard)

    def test_new_phase_cannot_bypass_expired_current_phase(self):
        clock = FakeClock()
        bounded = session(clock)
        bounded.phase("observe", .01)
        clock.value = .01
        self.assert_code("timeout", lambda: bounded.phase("act", .5))

    def test_old_phase_revocation_does_not_poison_new_phase(self):
        clock = FakeClock()
        bounded = session(clock)
        old = bounded.phase("observe", .01)
        new = bounded.phase("act", .5)
        clock.value = .1
        self.assert_code("phase_changed", old.guard)
        new.guard()
        bounded.guard()

    def test_strict_types_bounds_and_clock_failures(self):
        clock = FakeClock()
        for callback in (None, 1):
            with self.assertRaises(TypeError):
                BoundedSession(callback, lambda _: None, clock=clock)
            with self.assertRaises(TypeError):
                BoundedSession(lambda: None, callback, clock=clock)
        huge = 10 ** 1000
        for value in (True, 0, -1, 30.1, float("inf"), float("nan"), huge, "1"):
            with self.assertRaises((TypeError, ValueError)):
                session(clock, seconds=value)
        bounded = session(clock)
        for name in ("", "has\nnewline", "snowman-☃", 1):
            with self.assertRaises((TypeError, ValueError)):
                bounded.phase(name, 1)
        for value in (True, -1, 30.1, float("inf"), huge, "1"):
            with self.assertRaises((TypeError, ValueError)):
                bounded.wait(value)
            with self.assertRaises((TypeError, ValueError)):
                bounded.phase("observe", value)
        with self.assertRaises(SessionError) as raised:
            BoundedSession(lambda: None, lambda _: None, clock=lambda: float("nan"))
        self.assertEqual(raised.exception.code, "clock_invalid")
        with self.assertRaises(SessionError) as raised:
            BoundedSession(lambda: None, lambda _: None, clock=lambda: huge)
        self.assertEqual(raised.exception.code, "clock_invalid")
        clock = FakeClock(2)
        backwards = session(clock)
        clock.value = 1
        self.assert_code("clock_invalid", backwards.guard)

        clock = FakeClock()
        after_guard = session(clock, guard=lambda: setattr(clock, "value", -1))
        self.assert_code("clock_invalid", after_guard.guard)

        clock = FakeClock()
        huge_later = session(clock)
        clock.value = huge
        self.assert_code("clock_invalid", huge_later.guard)

    def test_wait_chunks_caps_and_rechecks_deadlines(self):
        clock, chunks = FakeClock(), []
        def wait(duration):
            chunks.append(duration)
            clock.value += duration
        bounded = session(clock, wait=wait, seconds=.07)
        with self.assertRaises(SessionError) as raised:
            bounded.wait(.07)
        self.assertEqual(raised.exception.code, "timeout")
        self.assertTrue(chunks)
        self.assertTrue(all(0 < item <= .02 for item in chunks))
        self.assertAlmostEqual(sum(chunks), .07)

    def test_wait_runs_external_guard_before_and_after_each_quantum(self):
        for reason in ("cancel", "focus"):
            with self.subTest(reason=reason):
                clock, waits = FakeClock(), []
                stopped = RuntimeError(reason)
                state = {"stopped": False}
                def guard():
                    if state["stopped"]:
                        raise stopped
                def wait(duration):
                    waits.append(duration)
                    clock.value += duration
                    state["stopped"] = True
                bounded = session(clock, guard=guard, wait=wait)
                with self.assertRaises(RuntimeError) as raised:
                    bounded.wait(.04)
                self.assertIs(raised.exception, stopped)
                self.assertEqual(len(waits), 1)
                self.assert_code("interrupted", bounded.guard)

        clock, calls = FakeClock(), []
        zero = session(clock, guard=lambda: calls.append("guard"))
        zero.wait(0)
        self.assertEqual(calls, ["guard"])

    def test_stalled_positive_wait_is_clock_invalid_not_an_unbounded_loop(self):
        clock, calls = FakeClock(), []
        bounded = session(clock, wait=lambda duration: calls.append(duration))
        self.assert_code("clock_invalid", lambda: bounded.wait(.1))
        self.assertEqual(len(calls), 1)

        clock, calls = FakeClock(), []
        def barely_advance(duration):
            calls.append(duration)
            clock.value += duration / 1000
        bounded = session(clock, wait=barely_advance)
        self.assert_code("clock_invalid", lambda: bounded.wait(.04))
        self.assertLessEqual(len(calls), 7)

    def test_close_and_interruption_are_irreversible(self):
        clock = FakeClock()
        bounded = session(clock)
        bounded.close()
        self.assert_code("closed", bounded.guard)
        self.assert_code("closed", lambda: bounded.wait(.1))

        stopped = RuntimeError("stop")
        interrupted = session(FakeClock(), guard=lambda: (_ for _ in ()).throw(stopped))
        with self.assertRaises(RuntimeError) as raised:
            interrupted.guard()
        self.assertIs(raised.exception, stopped)
        self.assert_code("interrupted", interrupted.guard)

        failed_wait = session(FakeClock(), wait=lambda _: (_ for _ in ()).throw(stopped))
        with self.assertRaises(RuntimeError) as raised:
            failed_wait.wait(.01)
        self.assertIs(raised.exception, stopped)
        self.assert_code("interrupted", failed_wait.guard)

    def test_callback_close_and_close_race_keep_first_reason(self):
        clock = FakeClock()
        holder = {}
        def guard():
            holder["session"].close()
        bounded = session(clock, guard=guard)
        holder["session"] = bounded
        self.assert_code("closed", bounded.guard)

        clock, holder = FakeClock(), {}
        def close_after_wait(_):
            clock.value += .01
            holder["session"].close()
        closed_after_wait = session(clock, wait=close_after_wait)
        holder["session"] = closed_after_wait
        self.assert_code("closed", lambda: closed_after_wait.wait(.01))

        entered, release = threading.Event(), threading.Event()
        clock = FakeClock()
        def wait(_):
            entered.set()
            release.wait(1)
            clock.value += .01
        raced = session(clock, wait=wait)
        errors = []
        worker = threading.Thread(target=lambda: errors.append(self._raised_code(lambda: raced.wait(.01))))
        worker.start()
        self.assertTrue(entered.wait(1))
        raced.close()
        release.set()
        worker.join(1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, ["closed"])

    def _raised_code(self, callback):
        try:
            callback()
        except SessionError as error:
            return error.code
        return "returned"

    def test_no_external_wait_after_closed(self):
        clock, calls = FakeClock(), []
        bounded = session(clock, wait=lambda duration: calls.append(duration))
        bounded.close()
        self.assert_code("closed", lambda: bounded.wait(.1))
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
