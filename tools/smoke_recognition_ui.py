"""Recognition setup Tk smoke with fake jobs only; requires a desktop session."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
import sys
from time import monotonic
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afk_grinder.capture import CapturedWindow
from afk_grinder.capture.service import JobResult
from afk_grinder.models import Target
from afk_grinder.recognition.observation import Rect
from afk_grinder.tk_runtime import configure_tk

configure_tk()

import tkinter as tk

from afk_grinder.ui_recognition import RecognitionSetup


TARGET = Target(1, "window", "RobloxPlayerBeta.exe", "win32")
OTHER_TARGET = Target(2, "other", "RobloxPlayerBeta.exe", "win32")


class StubJob:
    def __init__(self):
        self.result = None
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


def frame(target=TARGET, *, physical_size=(160, 90), native_rect=(0, 0, 160, 90),
          captured_at=None, region_kind="client", content_verified=True):
    return CapturedWindow(
        target=target,
        window_id="stable-window",
        native_rect=native_rect,
        physical_size=physical_size,
        monitor_id="screen",
        scale=(physical_size[0] / native_rect[2], physical_size[1] / native_rect[3]),
        pixels=bytes([1, 2, 3]) * (physical_size[0] * physical_size[1]),
        format="BGR8",
        captured_at=monotonic() if captured_at is None else captured_at,
        region_kind=region_kind,
        content_verified=content_verified,
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

    def complete_capture(self, captured=None):
        self.setup.capture_preview()
        self.jobs.jobs[-1].result = JobResult(frame=captured or frame())
        self.setup._poll_job(self.setup._job_token)
        self.root.update()

    def select_area(self, roi=Rect(16, 9, 128, 72)):
        self.setup._selection = roi
        self.setup._selection_var.set(self.setup._selection_text(roi))
        self.setup._draw_selection()
        self.setup._refresh()

    def test_preview_bgr_conversion_and_aspect_selection(self):
        self.complete_capture()
        self.assertEqual(self.setup._preview_pixels[:3], bytearray((3, 2, 1)))
        selection = self.setup._drag_selection((80, 45), (140, 75))
        self.assertAlmostEqual(selection.width / selection.height, 16 / 9)
        self.assertGreaterEqual(selection.x, 0)
        self.assertLessEqual(selection.x + selection.width, 160)

    def test_displayed_image_conversion_rejects_letterbox(self):
        self.complete_capture()
        self.setup._display_box = (20, 30, 80, 45)
        self.assertIsNone(self.setup._canvas_to_pixel(19, 30))
        self.assertEqual(self.setup._canvas_to_pixel(60, 52), (80.0, 44.0))

    def test_keyboard_moves_and_resizes_selection(self):
        self.complete_capture()
        self.select_area()
        before = self.setup._selection
        self.setup._on_arrow((1, 0), False)
        self.assertGreater(self.setup._selection.x, before.x)
        self.setup._on_arrow((1, 0), True)
        self.assertGreater(self.setup._selection.width, before.width)
        self.assertAlmostEqual(self.setup._selection.width / self.setup._selection.height, 16 / 9)

    def test_check_recaptures_then_calibrates_same_fresh_layout(self):
        self.complete_capture()
        self.select_area()
        self.setup.refresh_and_check_area()
        self.assertIsNone(self.setup._snapshot)
        job = self.jobs.jobs[-1]
        self.assertEqual(job.operation, "capture")
        job.result = JobResult(frame=frame())
        self.setup._poll_job(self.setup._job_token)
        self.assertIsNotNone(self.setup._calibration)
        self.assertIn("matches reference", self.setup._geometry_var.get())
        self.assertNotIn("ready", self.setup._geometry_var.get().casefold())

    def test_check_rejects_layout_change_and_stale_frame(self):
        self.complete_capture()
        self.select_area()
        self.setup.refresh_and_check_area()
        self.jobs.jobs[-1].result = JobResult(frame=frame(physical_size=(320, 180), native_rect=(0, 0, 320, 180)))
        self.setup._poll_job(self.setup._job_token)
        self.assertIsNone(self.setup._selection)
        self.assertIn("layout changed", self.setup._status_var.get())
        self.complete_capture()
        self.select_area()
        self.setup.refresh_and_check_area()
        self.jobs.jobs[-1].result = JobResult(frame=frame(captured_at=monotonic() - 1))
        self.setup._poll_job(self.setup._job_token)
        self.assertIsNone(self.setup._selection)
        self.assertIn("failed", self.setup._status_var.get())

    def test_historical_source_stays_editable_then_fresh_recapture_calibrates(self):
        self.complete_capture(frame(captured_at=monotonic() - 1))
        self.assertIsNotNone(self.setup._snapshot)
        self.assertIsNotNone(self.setup._layout)
        self.assertIn("historical", self.setup._status_var.get())
        left, top, width, height = self.setup._display_box
        self.setup._on_preview_press(SimpleNamespace(x=left + width // 8, y=top + height // 8))
        self.setup._on_preview_drag(SimpleNamespace(x=left + width * 3 // 4, y=top + height * 3 // 4))
        self.setup._on_preview_release(SimpleNamespace())
        self.assertIsNotNone(self.setup._selection)
        before = self.setup._selection
        self.setup._on_arrow((1, 0), False)
        self.assertGreater(self.setup._selection.x, before.x)
        self.setup.refresh_and_check_area()
        self.jobs.jobs[-1].result = JobResult(frame=frame())
        self.setup._poll_job(self.setup._job_token)
        self.assertIsNotNone(self.setup._calibration)
        self.assertIn("matching-frame", self.setup._status_var.get())

    def test_keyboard_initializes_and_resets_area_without_mouse(self):
        self.complete_capture(frame(region_kind="window-unverified", content_verified=False))
        self.assertIsNone(self.setup._selection)
        self.setup._on_canvas_activate()
        self.assertIsNotNone(self.setup._selection)
        self.assertAlmostEqual(self.setup._selection.width / self.setup._selection.height, 16 / 9)
        self.setup._on_canvas_reset()
        self.assertIsNone(self.setup._selection)
        self.assertEqual(self.setup._status_var.get(), "Area reset.")

    def test_raw_mac_frame_cannot_establish_calibration(self):
        self.complete_capture(frame(region_kind="window-unverified", content_verified=False))
        self.assertIn("includes window frame", self.setup._frame_note_var.get())
        self.assertTrue(self.setup.full_button.instate(["disabled"]))
        self.select_area()
        self.setup.refresh_and_check_area()
        self.jobs.jobs[-1].result = JobResult(frame=frame(region_kind="window-unverified", content_verified=False))
        self.setup._poll_job(self.setup._job_token)
        self.assertIsNone(self.setup._calibration)
        self.assertIsNone(self.setup._snapshot)
        self.assertIsNone(self.setup._selection)
        self.assertIn("Fresh area check failed", self.setup._status_var.get())
        self.assertTrue(self.setup.full_button.instate(["disabled"]))

    def test_cancel_target_change_and_late_result_clear_geometry(self):
        self.complete_capture()
        self.select_area()
        self.setup.refresh_and_check_area()
        job = self.jobs.jobs[-1]
        token = self.setup._job_token
        self.setup.cancel_work()
        job.result = JobResult(frame=frame())
        self.setup._poll_job(token)
        self.assertIsNone(self.setup._selection)
        self.assertIsNone(self.setup._calibration)
        self.complete_capture()
        self.target = OTHER_TARGET
        self.setup._poll_target()
        self.assertIsNone(self.setup._snapshot)

    def test_failed_capture_and_close_clear_pixels_and_geometry(self):
        self.complete_capture()
        self.select_area()
        self.setup.capture_preview()
        self.jobs.jobs[-1].result = JobResult(error="capture unavailable")
        self.setup._poll_job(self.setup._job_token)
        self.assertIsNone(self.setup._snapshot)
        self.assertIsNone(self.setup._preview_pixels)
        self.assertIsNone(self.setup._selection)
        self.assertIsNone(self.setup._calibration)
        self.complete_capture()
        self.select_area()
        self.setup.close()
        self.assertIsNone(self.setup._snapshot)
        self.assertIsNone(self.setup._preview_pixels)
        self.assertIsNone(self.setup._selection)
        self.assertIsNone(self.setup._calibration)

    def test_minimum_window_keeps_controls_labels_and_usable_raw_preview_inside(self):
        self.complete_capture(frame(
            region_kind="window-unverified",
            content_verified=False,
            captured_at=monotonic() - 1,
        ))
        self.setup._status_var.set(self.setup._capture_error("Screen Recording permission missing"))
        self.setup.window.geometry("440x560")
        self.root.update()
        top = self.setup.window.winfo_rooty()
        bottom = top + self.setup.window.winfo_height()
        controls = (
            self.setup.bind_button, self.setup.capture_button, self.setup.check_button,
            self.setup.full_button, self.setup.reset_button, self.setup.sdk_button,
            self.setup.close_button,
        )
        for widget in (*controls, *self.setup._wrap_labels):
            with self.subTest(widget=widget):
                self.assertGreaterEqual(widget.winfo_rooty(), top)
                self.assertLessEqual(widget.winfo_rooty() + widget.winfo_height(), bottom)
        self.assertGreaterEqual(self.setup.preview_canvas.winfo_height(), 96)
        self.assertIn("includes window frame", self.setup._frame_note_var.get())
        self.assertIn("historical", self.setup._frame_note_var.get().casefold())

    def test_escape_close_sdk_and_stdio(self):
        self.setup.capture_preview()
        job = self.jobs.jobs[-1]
        self.setup._on_escape()
        self.assertTrue(job.cancelled)
        self.binding = True
        self.setup._on_escape()
        self.assertFalse(self.binding)
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.setup.run_sdk_check()
            self.jobs.jobs[-1].result = JobResult(report={"native_input": False})
            self.setup._poll_job(self.setup._job_token)
        self.assertIn("compatible", self.setup._sdk_var.get())
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(errors.getvalue(), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
