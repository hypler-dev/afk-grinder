"""Recognition setup Tk smoke with fake jobs only; requires a desktop session."""

from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afk_grinder.capture import CapturedWindow
from afk_grinder.capture.service import JobResult
from afk_grinder.models import Target
from afk_grinder.tk_runtime import configure_tk

configure_tk()

import tkinter as tk

from afk_grinder.ui_recognition import RecognitionSetup


TARGET = Target(1, "window", "RobloxPlayerBeta.exe", "win32")
OTHER_TARGET = Target(2, "other", "RobloxPlayerBeta.exe", "win32")


class StubJob:
    def __init__(self, result=None):
        self.result = result
        self.cancelled = False

    @property
    def done(self):
        return self.cancelled or self.result is not None

    def poll(self):
        result, self.result = self.result, None
        return result

    def cancel(self):
        self.cancelled = True


class StubJobs:
    def __init__(self):
        self.jobs = []

    def __call__(self, operation, target=None):
        job = StubJob()
        job.operation = operation
        job.target = target
        self.jobs.append(job)
        return job


def frame(target=TARGET):
    return CapturedWindow(
        target=target,
        window_id="stable-window",
        native_rect=(0, 0, 2, 1),
        physical_size=(2, 1),
        monitor_id="screen",
        scale=(1, 1),
        pixels=bytes((1, 2, 3, 4, 5, 6)),
        format="BGR8",
        captured_at=1.0,
    )


class RecognitionSetupSmoke(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.target = TARGET
        self.binding = False
        self.input_running = False
        self.cancel_calls = 0
        self.jobs = StubJobs()
        self.setup = RecognitionSetup(
            self.root,
            get_target=lambda: self.target,
            begin_binding=self.begin_binding,
            cancel_binding=self.cancel_binding,
            binding_pending=lambda: self.binding,
            input_busy=lambda: self.input_running,
            job_factory=self.jobs,
        )
        self.root.update()

    def tearDown(self):
        self.setup.close()
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def begin_binding(self):
        self.binding = True

    def cancel_binding(self):
        self.cancel_calls += 1
        self.binding = False

    def poll_job(self):
        self.setup._poll_job(self.setup._job_token)
        self.root.update()

    def test_capture_and_bgr_preview_stay_in_memory(self):
        self.setup.capture_preview()
        job = self.jobs.jobs[-1]
        job.result = JobResult(frame=frame())
        self.poll_job()
        self.assertIsNotNone(self.setup._snapshot)
        self.assertEqual(self.setup._preview_pixels, bytearray((3, 2, 1, 6, 5, 4)))
        self.assertIn("Snapshot ready", self.setup._status_var.get())

    def test_close_cancels_job_binding_and_clears_preview(self):
        self.setup.capture_preview()
        job = self.jobs.jobs[-1]
        self.setup.close()
        self.assertTrue(job.cancelled)
        self.assertIsNone(self.setup._snapshot)
        self.assertIsNone(self.setup._photo)
        self.assertIsNone(self.setup._preview_pixels)
        self.assertEqual(self.cancel_calls, 1)

    def test_cancelled_late_result_cannot_restore_preview(self):
        self.setup.capture_preview()
        job = self.jobs.jobs[-1]
        token = self.setup._job_token
        self.setup.cancel_work()
        job.result = JobResult(frame=frame())
        self.setup._poll_job(token)
        self.assertIsNone(self.setup._snapshot)

    def test_target_change_clears_snapshot_and_late_frame(self):
        self.setup.capture_preview()
        job = self.jobs.jobs[-1]
        self.target = OTHER_TARGET
        self.setup._poll_target()
        job.result = JobResult(frame=frame())
        self.setup._poll_job(self.setup._job_token)
        self.assertIsNone(self.setup._snapshot)
        self.assertIn("changed", self.setup._status_var.get())

    def test_failed_capture_clears_snapshot(self):
        self.setup.capture_preview()
        job = self.jobs.jobs[-1]
        job.result = JobResult(error="capture unavailable")
        self.poll_job()
        self.assertIsNone(self.setup._snapshot)
        self.assertEqual(self.setup._status_var.get(), "Could not take preview. No input was sent.")

    def test_sdk_check_never_creates_backend_or_enables_input(self):
        self.setup.run_sdk_check()
        job = self.jobs.jobs[-1]
        self.assertEqual(job.operation, "sdk")
        self.assertIsNone(job.target)
        job.result = JobResult(report={"native_input": False})
        self.poll_job()
        self.assertIn("compatibility passed", self.setup._sdk_var.get())
        self.assertFalse(self.setup.capture_button.instate(["disabled"]))

    def test_escape_cancels_job_then_binding(self):
        self.setup.capture_preview()
        job = self.jobs.jobs[-1]
        self.setup._on_escape()
        self.assertTrue(job.cancelled)
        self.assertIn("cancelled", self.setup._status_var.get())
        self.binding = True
        self.setup._on_escape()
        self.assertFalse(self.binding)
        self.assertIn("Binding cancelled", self.setup._status_var.get())

    def test_fake_flow_writes_no_standard_output(self):
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.setup.capture_preview()
            self.jobs.jobs[-1].result = JobResult(frame=frame())
            self.poll_job()
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(errors.getvalue(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
