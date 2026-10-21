"""Synthetic, read-only PackInspectionSession coverage."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest

from afk_grinder import __version__
from afk_grinder.capture import CapturedWindow
from afk_grinder.models import Target
from afk_grinder.pack_inspection import PackInspectionError, PackInspectionSession
from afk_grinder.recognition.content_calibration import ContentCalibration
from afk_grinder.recognition.frame_geometry import layout_from_capture
from afk_grinder.recognition.pack_results import AnchorHit
from afk_grinder.recognition.packs import State, load_pack
from tools.make_fixture_demo import generate


TARGET = Target(81, "81", "RobloxPlayer", "com.roblox.RobloxPlayer")


class Clock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value

    def wait(self, seconds):
        self.value += seconds


class Job:
    def __init__(self, frame=None, error="", clock=None, after=None):
        self.frame, self.error, self.clock, self.after = frame, error, clock, after
        self.cancelled = False

    def poll(self):
        if self.after is not None and self.clock is not None and self.clock.value < self.after:
            return None
        return type("Result", (), {"frame": self.frame, "error": self.error})()

    def cancel(self):
        self.cancelled = True


class Recognition:
    def __init__(self, results, *, ready=True):
        self.results = list(results)
        self.ready = ready
        self.started = self.closed = False
        self.submissions = []

    def start(self):
        self.started = True

    def submit(self, width, height, pixels, *, timeout):
        self.submissions.append((width, height, pixels, timeout))

    def poll(self):
        if not self.ready:
            return None
        if not self.results:
            return None
        item = self.results.pop(0)
        if item is None:
            return None
        return item

    def close(self):
        self.closed = True


def _result(hits=(), error=""):
    return type("Result", (), {"hits": tuple(hits), "error": error})()


class PackInspectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        directory, _, _ = generate(Path(temporary.name) / "demo", "a" * 40)
        self.pack = load_pack(directory, app_version=__version__)
        self.clock = Clock()
        self.frame = self._frame(self.clock.value)
        self.calibration = ContentCalibration.manual(layout_from_capture(self.frame), (0, 0, *self.pack.reference_size))

    def _frame(self, captured_at, *, window_id="window", size=None):
        width, height = size or self.pack.reference_size
        return CapturedWindow(TARGET, window_id, (0, 0, width, height), (width, height), "display", (1.0, 1.0),
                              bytes(width * height * 3), "BGR8", captured_at)

    def _hits(self, active="gameplay"):
        active_ids = {active} if type(active) is str else set(active)
        hits = []
        for anchor in self.pack.anchors:
            if anchor.id in active_ids:
                hits.append(AnchorHit(anchor.id, .99, (8, 8, 8, 8)))
            else:
                hits.append(AnchorHit(anchor.id, .01, None))
        return tuple(hits)

    def _stable_pack(self):
        return replace(self.pack, states=(State("ready", ("gameplay",), (), 2, "gameplay"),))

    def _session(self, frames, results, *, pack=None, ready=True):
        jobs = []
        recognition = Recognition(results, ready=ready)
        def capture_factory(*_args, **_kwargs):
            job = Job(frames.pop(0), clock=self.clock)
            jobs.append(job)
            return job
        session = PackInspectionSession(pack or self.pack, self.calibration, capture_factory=capture_factory,
                                        recognition_factory=lambda *_: recognition, clock=self.clock)
        return session, jobs, recognition

    def test_two_distinct_fresh_frames_return_stable_terminal_report(self):
        second = self._frame(100.05)
        session, jobs, recognition = self._session(
            [self.frame, second], [_result(self._hits()), _result(self._hits())], pack=self._stable_pack(),
        )
        report = session.run(lambda: None, self.clock.wait)
        self.assertEqual((report.state.status, report.state.reason), ("known", "stable"))
        self.assertEqual((report.required_frames, report.observed_frames), (2, 2))
        self.assertIs(report.frame, second)
        self.assertEqual(len(report.anchors), len(self.pack.anchors))
        self.assertTrue(all(job.cancelled for job in jobs))
        self.assertTrue(recognition.closed)

    def test_popup_transaction_unknown_ambiguous_and_exclusion_never_return_known(self):
        states = (
            State("popup", (self.pack.anchors[0].id,), (), 1, "popup"),
        )
        popup_pack = replace(self.pack, states=states)
        session, _, _ = self._session([self.frame], [_result(self._hits())], pack=popup_pack)
        self.assertEqual(session.run(lambda: None, self.clock.wait).state.status, "blocked")

        unknown_pack = replace(self.pack, states=(State("unknown", (self.pack.anchors[0].id,), (), 1, "unknown"),))
        session, _, _ = self._session([self.frame], [_result(self._hits())], pack=unknown_pack)
        self.assertEqual(session.run(lambda: None, self.clock.wait).state.status, "unknown")

        ids = (self.pack.anchors[0].id, self.pack.anchors[1].id)
        ambiguous_pack = replace(self.pack, states=(State("one", (ids[0],), (), 1), State("two", (ids[1],), (), 1)))
        session, _, _ = self._session([self.frame], [_result(self._hits(ids))], pack=ambiguous_pack)
        self.assertEqual(session.run(lambda: None, self.clock.wait).state.reason, "ambiguous")

        excluded_pack = replace(self.pack, states=(State("unsafe", (ids[0],), (ids[1],), 1), State("other", (ids[1],), (), 1)))
        session, _, _ = self._session([self.frame], [_result(self._hits(ids))], pack=excluded_pack)
        self.assertEqual(session.run(lambda: None, self.clock.wait).state.status, "blocked")

    def test_stale_out_of_order_layout_and_invalid_metadata_fail_closed(self):
        cases = [
            (self._frame(99.49), self._stable_pack(), _result(self._hits()), "stale"),
            (self._frame(100.0, window_id="other"), self._stable_pack(), _result(self._hits()), "layout_changed"),
            (self.frame, self.pack, _result((AnchorHit("wrong", .9, (8, 8, 8, 8)),)), "invalid_result"),
        ]
        for frame, pack, result, code in cases:
            with self.subTest(code=code):
                session, _, _ = self._session([frame], [result], pack=pack)
                with self.assertRaisesRegex(PackInspectionError, f"^{code}$"):
                    session.run(lambda: None, self.clock.wait)

        session, _, _ = self._session(
            [self.frame, self.frame], [_result(self._hits()), _result(self._hits())], pack=self._stable_pack(),
        )
        with self.assertRaisesRegex(PackInspectionError, "^stale$"):
            session.run(lambda: None, self.clock.wait)

    def test_capture_and_recognition_failures_use_fixed_codes(self):
        def failed_capture(*_args, **_kwargs):
            return Job(error="native detail must not escape")
        session = PackInspectionSession(self._stable_pack(), self.calibration, capture_factory=failed_capture,
                                        recognition_factory=lambda *_: Recognition([]), clock=self.clock)
        with self.assertRaisesRegex(PackInspectionError, "^capture_failed$"):
            session.run(lambda: None, self.clock.wait)

        session, _, recognition = self._session([self.frame], [_result(error="worker failure")], pack=self._stable_pack())
        with self.assertRaisesRegex(PackInspectionError, "^recognition_failed$"):
            session.run(lambda: None, self.clock.wait)
        self.assertTrue(recognition.closed)

    def test_budget_only_retries_real_unstable_captures(self):
        frames = [self._frame(100 + index * .01) for index in range(5)]
        session, jobs, recognition = self._session(
            frames, [_result(self._hits()) for _ in range(5)], pack=self._stable_pack(),
        )
        report = session.run(lambda: None, self.clock.wait)
        self.assertEqual((report.state.status, report.state.reason, report.observed_frames), ("known", "stable", 2))
        self.assertEqual(len(jobs), 2)
        self.assertEqual(len(recognition.submissions), 2)

    def test_cancel_before_start_during_warm_and_close_do_not_publish_progress(self):
        session, jobs, recognition = self._session([self.frame], [_result(self._hits())])
        session.close()
        with self.assertRaisesRegex(PackInspectionError, "^timeout$"):
            session.run(lambda: None, self.clock.wait)
        self.assertEqual((jobs, recognition.submissions), ([], []))

        session, jobs, recognition = self._session([self.frame], [_result(self._hits())], ready=False)
        progress = []
        def guard():
            if recognition.started:
                session.close()
        with self.assertRaisesRegex(PackInspectionError, "^timeout$"):
            session.run(guard, self.clock.wait, progress=progress.append)
        self.assertEqual(progress, ["warming"])
        self.assertTrue(recognition.closed)

    def test_no_input_path_or_recording_imports(self):
        import afk_grinder.pack_inspection as module
        source = Path(module.__file__).read_text(encoding="utf-8")
        for forbidden in ("engine", "GuardedInput", "click(", "record", "open(", "socket", "requests"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
