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

class PopupLifecycleTests(unittest.TestCase):
    def make_operation(self, *, warm_hook=lambda: None, capture_hook=lambda: None,
                       result_hook=lambda: None, report_hook=lambda *_: None,
                       recognition_factory_hook=lambda: None, capture_factory_hook=lambda: None):
        clock = SimpleNamespace(value=100.)
        events, reports, records, submitted = [], [], [], []
        current = {}
        def capture_factory(*args, **kwargs):
            events.append("capture_create")
            capture_factory_hook()
            _, hits = synthetic(captured_at=clock.value)
            current["hits"] = hits
            raw = CapturedWindow(TARGET, RAW.window_id, (-900, 40, 800, 600), (800, 600), "display",
                                 (1., 1.), bytes((55, 55, 55)) * 800 * 600, "BGR8", clock.value,
                                 "window-unverified", False)
            def poll():
                events.append("capture_poll")
                capture_hook()
                return SimpleNamespace(frame=raw, error="")
            return SimpleNamespace(poll=poll, cancel=lambda: events.append("capture_cancel"))
        class Recognition:
            @property
            def ready(self):
                warm_hook()
                return True
            def start(self): events.append("start")
            def submit(self, *args, **kwargs): submitted.append(kwargs["timeout"])
            def poll(self):
                result_hook()
                return SimpleNamespace(hits=current["hits"], error="")
            def close(self): events.append("close")
        def recognition_factory(*args):
            events.append("recognition_create")
            recognition_factory_hook()
            return Recognition()
        def report(*args):
            reports.append(args)
            report_hook(*args)
        operation = PopupSession(CAL, report=report, record=lambda *args: records.append(args),
                                 clock=lambda: clock.value, capture_factory=capture_factory,
                                 recognition_factory=recognition_factory, models=lambda: Path("unused"))
        wait = lambda seconds: setattr(clock, "value", clock.value + seconds)
        return operation, clock, wait, events, reports, records, submitted

    def test_closed_operations_never_restart_workers(self):
        operation, _, wait, events, reports, _, _ = self.make_operation()
        operation.close()
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, "closed"):
                operation.check(lambda: None, wait)
        self.assertEqual(events, [])
        self.assertEqual(reports, [])

    def test_late_warm_and_factory_close_cannot_reach_capture(self):
        holder = {}
        operation, clock, wait, events, _, _, _ = self.make_operation(
            warm_hook=lambda: setattr(holder["clock"], "value", 116.))
        holder["clock"] = clock
        with self.assertRaisesRegex(RuntimeError, "timeout"):
            operation.check(lambda: None, wait)
        self.assertEqual(events, ["recognition_create", "start", "close"])
        operation, _, wait, events, _, _, _ = self.make_operation(
            recognition_factory_hook=lambda: holder["operation"].close())
        holder["operation"] = operation
        with self.assertRaisesRegex(RuntimeError, "closed"):
            operation.check(lambda: None, wait)
        self.assertEqual(events, ["recognition_create", "close"])

    def test_capture_close_and_expired_capture_drop_pixels(self):
        holder = {}
        operation, clock, wait, events, _, records, submitted = self.make_operation(
            capture_hook=lambda: setattr(holder["clock"], "value", 108.1))
        holder["clock"] = clock
        with self.assertRaisesRegex(RuntimeError, "timeout"):
            operation.check(lambda: None, wait)
        self.assertEqual(records, [])
        self.assertEqual(submitted, [])
        self.assertEqual(events.count("capture_cancel"), 1)
        self.assertEqual(events.count("close"), 1)
        operation, _, wait, events, _, _, submitted = self.make_operation(
            capture_factory_hook=lambda: holder["operation"].close())
        holder["operation"] = operation
        with self.assertRaisesRegex(RuntimeError, "closed"):
            operation.check(lambda: None, wait)
        self.assertNotIn("capture_poll", events)
        self.assertEqual(events.count("capture_cancel"), 1)
        self.assertEqual(submitted, [])

    def test_late_recognition_and_report_cancellation_never_record(self):
        holder = {}
        operation, clock, wait, _, reports, records, submitted = self.make_operation(
            result_hook=lambda: setattr(holder["clock"], "value", 100.51))
        holder["clock"] = clock
        with self.assertRaisesRegex(RuntimeError, "expired"):
            operation.check(lambda: None, wait)
        self.assertEqual(records, [])
        self.assertEqual([report[0] for report in reports], ["checking"])
        self.assertTrue(all(0 < timeout <= .5 for timeout in submitted))
        operation, _, wait, _, reports, records, _ = self.make_operation(
            report_hook=lambda state, _: holder["operation"].close() if state != "checking" else None)
        holder["operation"] = operation
        with self.assertRaisesRegex(RuntimeError, "closed"):
            operation.check(lambda: None, wait)
        self.assertEqual(records, [])

    def test_completed_match_budget_does_not_cover_recording_interval(self):
        operation, _, wait, events, _, records, _ = self.make_operation()
        try:
            operation._warm(lambda: None, wait)
            operation._observe(lambda: None, wait)
            wait(2)
            operation._observe(lambda: None, wait)
            self.assertEqual(len(records), 2)
        finally:
            operation.close()
        self.assertEqual(events.count("close"), 1)

class PopupFailureDiagnosticTests(unittest.TestCase):
    def make_operation(self, **kwargs):
        return PopupLifecycleTests.make_operation(self, **kwargs)

    def assert_failure(self, operation, wait, *, guard=lambda: None, expected=None):
        with self.assertRaises(BaseException) as raised:
            operation.check(guard, wait)
        if expected is not None:
            self.assertIs(raised.exception, expected)
        payload = operation.failure.as_ipc()
        self.assertNotIn("/private", repr(payload))
        self.assertIsNone(operation._capture)
        self.assertIsNone(operation._recognition)
        return payload

    def test_model_worker_start_and_warmup_failures_have_distinct_stages(self):
        from afk_grinder.recognition.service import TIMEOUT_ERROR
        for location in ("models", "factory", "start", "warmup"):
            operation, _, wait, _, _, _, _ = self.make_operation()
            error = RuntimeError("/private/secret/chat")
            def reject(*_args, **_kwargs): raise error
            if location == "models":
                operation.models = reject
            elif location == "factory":
                operation.recognition_factory = reject
            else:
                original = operation.recognition_factory
                def factory(*args):
                    service = original(*args)
                    if location == "start": service.start = reject
                    else:
                        service = SimpleNamespace(ready=False, start=lambda: None,
                                                  poll=lambda: SimpleNamespace(error=TIMEOUT_ERROR),
                                                  close=lambda: None)
                    return service
                operation.recognition_factory = factory
            payload = self.assert_failure(operation, wait, expected=error if location != "warmup" else None)
            self.assertEqual(payload["stage"], {"models": "model_validation", "factory": "worker_start",
                                               "start": "worker_start", "warmup": "warmup"}[location])
            self.assertEqual(payload["code"], "worker_timeout" if location == "warmup" else "failed")

    def test_capture_failure_keeps_only_revalidated_capture_metadata(self):
        from afk_grinder.capture import CaptureDiagnostic
        for corrupt in (False, True):
            operation, _, wait, _, _, _, _ = self.make_operation()
            diagnostic = CaptureDiagnostic("permission", "preflight", "capture_error")
            if corrupt: object.__setattr__(diagnostic, "stage", "/private/secret/chat")
            operation.capture_factory = lambda *_args, **_kwargs: SimpleNamespace(
                poll=lambda: SimpleNamespace(error="/private/secret/chat", frame=None, diagnostic=diagnostic),
                cancel=lambda: None)
            payload = self.assert_failure(operation, wait)
            self.assertEqual((payload["stage"], payload["code"]), ("capture", "failed"))
            self.assertEqual(payload["capture"], None if corrupt else {
                "code": "permission", "stage": "preflight", "error_type": "capture_error"})

    def test_capture_and_recognition_staleness_are_distinct(self):
        for phase in ("capture", "recognition"):
            holder = {}
            hook = lambda: setattr(holder["clock"], "value", 100.51)
            operation, clock, wait, _, reports, records, _ = self.make_operation(
                **({"capture_hook": hook} if phase == "capture" else {"result_hook": hook}))
            holder["clock"] = clock
            payload = self.assert_failure(operation, wait)
            self.assertEqual((payload["stage"], payload["code"]), (phase + "_freshness", "stale"))
            self.assertEqual(records, [])
            self.assertEqual([value[0] for value in reports], ["checking"])

    def test_changed_layout_and_submit_error_do_not_authorize_results(self):
        for phase in ("layout", "submit"):
            operation, _, wait, _, reports, records, _ = self.make_operation()
            error = RuntimeError("/private/secret/chat")
            if phase == "layout":
                original = operation.capture_factory
                def factory(*args, **kwargs):
                    capture = original(*args, **kwargs)
                    poll = capture.poll
                    def moved():
                        result = poll()
                        result.frame = replace(result.frame, native_rect=(-800, 40, 800, 600))
                        return result
                    capture.poll = moved
                    return capture
                operation.capture_factory = factory
            else:
                original = operation.recognition_factory
                def factory(*args):
                    service = original(*args)
                    def reject(*_args, **_kwargs): raise error
                    service.submit = reject
                    return service
                operation.recognition_factory = factory
            payload = self.assert_failure(operation, wait, expected=error if phase == "submit" else None)
            self.assertEqual((payload["stage"], payload["code"]),
                             ("content_calibration", "layout_changed") if phase == "layout" else
                             ("recognition_submit", "failed"))
            self.assertEqual(records, [])
            self.assertEqual([value[0] for value in reports], ["checking"])

    def test_worker_result_error_and_deadlines_do_not_expose_messages(self):
        from afk_grinder.recognition.service import TIMEOUT_ERROR, WORKER_ERROR
        for error, expected in ((TIMEOUT_ERROR, "worker_timeout"), (WORKER_ERROR, "worker_failed"),
                                ("/private/secret/chat", "worker_failed")):
            operation, _, wait, _, _, records, _ = self.make_operation()
            original = operation.recognition_factory
            def factory(*args):
                service = original(*args)
                service.poll = lambda: SimpleNamespace(error=error)
                return service
            operation.recognition_factory = factory
            payload = self.assert_failure(operation, wait)
            self.assertEqual((payload["stage"], payload["code"]), ("recognition", expected))
            self.assertEqual(records, [])
        holder = {}
        operation, clock, wait, _, _, _, _ = self.make_operation(
            warm_hook=lambda: setattr(holder["clock"], "value", 116.))
        holder["clock"] = clock
        payload = self.assert_failure(operation, wait)
        self.assertEqual((payload["stage"], payload["code"]), ("warmup", "timeout"))

    def test_caller_exception_identity_survives_diagnostic_capture(self):
        from afk_grinder.session import SessionError
        for error in (RuntimeError("/private/secret/chat"), SessionError("phase_changed")):
            operation, _, wait, _, _, _, _ = self.make_operation()
            def guard(): raise error
            payload = self.assert_failure(operation, wait, guard=guard, expected=error)
            self.assertEqual(payload["code"], "phase_changed" if isinstance(error, SessionError) else "interrupted")

    def test_resolve_failures_preserve_exceptions_and_safe_response_stages(self):
        for kind in ("geometry", "stale", "input", "verification"):
            with self.subTest(kind=kind):
                operation, clock, wait, events, _, _, _ = self.make_operation()
                original_factory = operation.capture_factory
                def capture_factory(*args, **kwargs):
                    capture = original_factory(*args, **kwargs)
                    poll = capture.poll
                    def known_popup():
                        result = poll()
                        positive, _ = synthetic(captured_at=result.frame.captured_at)
                        result.frame = replace(result.frame, pixels=positive.pixels)
                        return result
                    capture.poll = known_popup
                    return capture
                operation.capture_factory = capture_factory
                error = RuntimeError("/private/secret/chat")
                clicks, caught = [], []
                def geometry(_layout):
                    if kind == "geometry": raise error
                    if kind == "stale": clock.value += .51
                operation.geometry_check = geometry
                class Capability:
                    def guard(self): pass
                    def wait(self, seconds):
                        if kind == "verification" and clicks: raise error
                        wait(seconds)
                    def click(self, point, authorize):
                        try:
                            authorize()
                            if kind == "input": raise error
                        except BaseException as failure:
                            caught.append(failure)
                            raise
                        clicks.append(point)
                with self.assertRaises(RuntimeError) as raised:
                    operation.resolve(Capability(), allow_reconnect=True)
                if kind == "stale": self.assertIs(raised.exception, caught[0])
                else: self.assertIs(raised.exception, error)
                diagnostic = operation.failure.as_ipc()
                expected = {"geometry": ("response_geometry", "failed"),
                            "stale": ("response_geometry", "stale"),
                            "input": ("response", "failed"),
                            "verification": ("verification", "interrupted")}[kind]
                self.assertEqual((diagnostic["stage"], diagnostic["code"]), expected)
                self.assertNotIn("/private", repr(diagnostic))
                self.assertEqual(len(clicks), 1 if kind == "verification" else 0)
                self.assertEqual(events.count("capture_create"), 2)
                self.assertIsNone(operation._capture)
                self.assertIsNone(operation._recognition)

    def test_successful_read_only_result_has_no_failure_metadata(self):
        operation, _, wait, _, _, _, _ = self.make_operation()
        operation.check(lambda: None, wait)
        self.assertIsNone(operation.failure)


if __name__ == "__main__":
    unittest.main()
