from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afk_grinder.engine import Runner
from afk_grinder.models import Step, Target, Workflow

TARGET = Target(100, "100", "RobloxPlayerBeta.exe", "win32")
OTHER = Target(200, "200", "other.exe", "win32")


class FakeBackend:
    def __init__(self):
        self.focus = TARGET
        self.escape = False
        self.problems = []
        self.calls = []
        self.on_down = lambda: None
        self.raise_down = False
        self.fail_key_up = False
        self.press = threading.Event()

    def foreground(self):
        return self.focus

    def readiness(self):
        return self.problems

    def escape_pressed(self):
        return self.escape

    def key_down(self, key):
        self.calls.append(("down", key))
        self.press.set()
        self.on_down()
        if self.raise_down:
            raise RuntimeError("Injection failed")

    def key_up(self, key):
        self.calls.append(("up", key))
        if self.fail_key_up:
            raise RuntimeError("Release failed")

    def mouse_down(self, button):
        self.calls.append(("mouse_down", button))
        self.press.set()
        self.on_down()

    def mouse_down_at(self, button, x, y):
        self.calls.append(("mouse_down_at", button, x, y))
        self.on_down()
        if self.raise_down:
            raise RuntimeError("Injection failed")

    def mouse_up(self, button):
        self.calls.append(("mouse_up", button))


class RunnerTests(unittest.TestCase):
    def test_guarded_positioned_click_tracks_before_post_and_releases_on_error(self):
        self.backend.raise_down = True
        self.runner.start_routine(lambda capability: capability.click((10., 20.), lambda: None),
                                  target=TARGET, armed=True, cancel_event=threading.Event())
        self.runner.join(1)
        self.assertEqual(self.backend.calls, [("mouse_down_at", "left", 10., 20.), ("mouse_up", "left")])
        self.assertFalse(self.runner.running)

    def test_guarded_click_cannot_run_after_focus_loss_or_cancel_and_capability_cannot_escape(self):
        for mode in ("focus", "cancel"):
            with self.subTest(mode=mode):
                ticket = threading.Event()
                saved = []
                def routine(capability):
                    saved.append(capability)
                    if mode == "focus":
                        self.backend.focus = OTHER
                    else:
                        ticket.set()
                    capability.click((10., 20.), lambda: None)
                self.backend.focus = TARGET
                self.runner.start_routine(routine, target=TARGET, armed=True, cancel_event=ticket)
                self.runner.join(1)
                self.assertEqual(self.backend.calls, [])
                with self.assertRaisesRegex(RuntimeError, "no longer active"):
                    saved[0].click((10., 20.), lambda: None)
    def test_start_ticket_canceled_during_readiness_cannot_send_input(self):
        entered, release, canceled = threading.Event(), threading.Event(), threading.Event()
        def readiness():
            entered.set()
            release.wait(1)
            return []
        self.backend.readiness = readiness
        errors = []
        def start():
            try:
                self.runner.start(self.workflow, target=TARGET, dry_run=False, armed=True,
                                  cancel_event=canceled)
            except RuntimeError as error:
                errors.append(str(error))
        thread = threading.Thread(target=start)
        thread.start()
        self.assertTrue(entered.wait(1))
        canceled.set()
        release.set()
        thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, ["Start was canceled."])
        self.assertFalse(self.runner.running)
        self.assertEqual(self.backend.calls, [])

    def test_external_stop_ticket_releases_held_key(self):
        canceled = threading.Event()
        self.backend.on_down = canceled.set
        self.runner.start(self.workflow, target=TARGET, dry_run=False, armed=True,
                          cancel_event=canceled)
        self.runner.join(1)
        self.assertFalse(self.runner.running)
        self.assertEqual(self.backend.calls, [("down", "w"), ("up", "w")])

    def setUp(self):
        self.countdown = patch("afk_grinder.engine.COUNTDOWN_SECONDS", 0)
        self.countdown.start()
        self.addCleanup(self.countdown.stop)
        self.backend = FakeBackend()
        self.runner = Runner(self.backend)
        self.addCleanup(self.stop_worker)
        self.workflow = Workflow("Test", (Step("hold_key", 40, "w"), Step("hold_key", 20, "s")))

    def stop_worker(self):
        self.runner.stop()
        self.runner.join(1)

    def run_live(self, workflow=None):
        self.runner.start(workflow or self.workflow, target=TARGET, dry_run=False, armed=True)
        self.runner.join(1)
        self.assertFalse(self.runner.running, "Worker did not finish")
        statuses = []
        while not self.runner.events.empty():
            statuses.append(self.runner.events.get_nowait())
        return statuses[-1]

    def test_completion_releases_each_key(self):
        status = self.run_live()
        self.assertEqual(status.state, "completed")
        self.assertEqual(self.backend.calls, [("down", "w"), ("up", "w"), ("down", "s"), ("up", "s")])

    def test_focus_loss_mid_hold_releases_key_and_stops_next_action(self):
        self.backend.on_down = lambda: setattr(self.backend, "focus", OTHER)
        self.assertEqual(self.run_live().state, "stopped")
        self.assertEqual(self.backend.calls, [("down", "w"), ("up", "w")])

    def test_escape_mid_hold_releases_key(self):
        self.backend.on_down = lambda: setattr(self.backend, "escape", True)
        status = self.run_live()
        self.assertIn("Escape", status.message)
        self.assertEqual(self.backend.calls, [("down", "w"), ("up", "w")])

    def test_permission_loss_mid_hold_releases_key(self):
        self.backend.on_down = lambda: self.backend.problems.append("Permission revoked")
        self.assertEqual(self.run_live().state, "error")
        self.assertEqual(self.backend.calls, [("down", "w"), ("up", "w")])

    def test_partial_injection_error_still_releases(self):
        self.backend.raise_down = True
        self.assertEqual(self.run_live().state, "error")
        self.assertEqual(self.backend.calls, [("down", "w"), ("up", "w")])

    def test_stop_during_hold(self):
        workflow = Workflow("Long", (Step("hold_key", 5000, "w"),))
        self.runner.start(workflow, target=TARGET, dry_run=False, armed=True)
        self.assertTrue(self.backend.press.wait(1))
        self.runner.stop()
        self.runner.join(1)
        self.assertFalse(self.runner.running)
        self.assertEqual(self.backend.calls, [("down", "w"), ("up", "w")])

    def test_mouse_escape_releases_button(self):
        self.backend.on_down = lambda: setattr(self.backend, "escape", True)
        self.run_live(Workflow("Click", (Step("click", 80, button="left"),)))
        self.assertEqual(self.backend.calls, [("mouse_down", "left"), ("mouse_up", "left")])

    def test_cleanup_failure_blocks_later_live_execution(self):
        self.backend.fail_key_up = True
        self.backend.on_down = lambda: setattr(self.backend, "escape", True)
        status = self.run_live()
        self.assertEqual(status.state, "error")
        self.assertTrue(self.runner.cleanup_failed)
        with self.assertRaisesRegex(RuntimeError, "cleanup failed"):
            self.runner.start(self.workflow, target=TARGET, dry_run=False, armed=True)

    def test_dry_run_after_failed_cleanup_does_not_send_releases(self):
        self.backend.fail_key_up = True
        self.backend.on_down = lambda: setattr(self.backend, "escape", True)
        self.run_live()
        calls = list(self.backend.calls)
        self.runner.start(self.workflow)
        self.runner.join(1)
        self.assertEqual(self.backend.calls, calls)

    def test_wrong_process_same_name_different_pid_cannot_receive_input(self):
        self.backend.focus = Target(101, "101", "RobloxPlayerBeta.exe", "win32")
        self.assertEqual(self.run_live().state, "stopped")
        self.assertEqual(self.backend.calls, [])

    def test_requires_arming_bound_roblox_and_permissions(self):
        with self.assertRaises(ValueError):
            self.runner.start(self.workflow, target=TARGET, dry_run=False)
        with self.assertRaises(ValueError):
            self.runner.start(self.workflow, target=OTHER, dry_run=False, armed=True)
        self.backend.problems = ["No permission"]
        with self.assertRaisesRegex(RuntimeError, "No permission"):
            self.runner.start(self.workflow, target=TARGET, dry_run=False, armed=True)
        self.assertEqual(self.backend.calls, [])

    def test_dry_run_never_calls_native_backend(self):
        class Forbidden:
            def __getattr__(self, name):
                raise AssertionError(f"Unexpected native call: {name}")
        self.runner = Runner(Forbidden())
        self.runner.start(self.workflow)
        self.runner.join(1)
        self.assertFalse(self.runner.running)
        self.assertEqual(self.runner.events.queue[-1].state, "completed")

    def test_escape_during_countdown_sends_nothing(self):
        self.backend.escape = True
        with patch("afk_grinder.engine.COUNTDOWN_SECONDS", 3):
            self.assertEqual(self.run_live().state, "stopped")
        self.assertEqual(self.backend.calls, [])

    def test_wait_checks_focus_and_stops_following_key(self):
        self.backend.focus = None
        workflow = Workflow("Wait", (Step("wait", 20), Step("hold_key", 20, "w")))
        self.assertEqual(self.run_live(workflow).state, "stopped")
        self.assertEqual(self.backend.calls, [])

    def test_stop_during_countdown_sends_nothing(self):
        with patch("afk_grinder.engine.COUNTDOWN_SECONDS", 3):
            self.runner.start(self.workflow, target=TARGET, dry_run=False, armed=True)
            self.assertEqual(self.runner.events.get(timeout=1).state, "countdown")
            self.runner.stop()
            self.runner.join(1)
        self.assertFalse(self.runner.running)
        self.assertEqual(self.backend.calls, [])

    def test_wall_clock_deadline_stops_and_releases_held_key(self):
        self.backend.on_down = lambda: setattr(self.runner, "_deadline", 0)
        status = self.run_live()
        self.assertIn("time limit", status.message)
        self.assertEqual(self.backend.calls, [("down", "w"), ("up", "w")])

    def test_guard_error_still_releases_held_key(self):
        def make_guard_fail():
            self.backend.escape_pressed = lambda: (_ for _ in ()).throw(RuntimeError("Monitor failed"))
        self.backend.on_down = make_guard_fail
        self.assertEqual(self.run_live().state, "error")
        self.assertEqual(self.backend.calls, [("down", "w"), ("up", "w")])

    def test_focus_loss_during_wait_stops_next_input(self):
        calls = 0
        def lose_focus():
            nonlocal calls
            calls += 1
            return TARGET if calls < 4 else OTHER
        self.backend.foreground = lose_focus
        workflow = Workflow("Wait", (Step("wait", 100), Step("hold_key", 20, "w")))
        self.assertEqual(self.run_live(workflow).state, "stopped")
        self.assertEqual(self.backend.calls, [])

    def test_cannot_start_second_worker(self):
        workflow = Workflow("Long", (Step("hold_key", 5000, "w"),))
        self.runner.start(workflow, target=TARGET, dry_run=False, armed=True)
        self.assertTrue(self.backend.press.wait(1))
        with self.assertRaisesRegex(RuntimeError, "already active"):
            self.runner.start(self.workflow)

    def test_worker_waiting_for_acquisition_lock_cannot_press_after_stop_returns(self):
        entered = threading.Event()
        allow_guard_return = threading.Event()
        original_guard = self.runner._guard
        guards = 0

        def pause_before_acquisition(target, dry_run, *, focus):
            nonlocal guards
            original_guard(target, dry_run, focus=focus)
            if focus:
                guards += 1
                if guards == 2:
                    entered.set()
                    if not allow_guard_return.wait(1):
                        raise RuntimeError("Test synchronization timed out")

        self.runner._guard = pause_before_acquisition
        self.runner.start(self.workflow, target=TARGET, dry_run=False, armed=True)
        self.assertTrue(entered.wait(1))
        with self.runner._lock:
            allow_guard_return.set()
            self.runner.stop()
            self.assertEqual(self.backend.calls, [])
        self.runner.join(1)
        self.assertFalse(self.runner.running)
        self.assertEqual(self.backend.calls, [])

    def test_invalid_programmatic_workflow_cannot_bypass_parser(self):
        with self.assertRaises(ValueError):
            self.runner.start(Workflow("Bad", (Step("hold_key", 10, "enter"),)),
                              target=TARGET, dry_run=False, armed=True)
        self.assertEqual(self.backend.calls, [])
