"""Coordinate and freshness regressions require no native capture or input."""

from dataclasses import replace
import unittest

from afk_grinder.models import Target
from afk_grinder.recognition.observation import Calibration, Layout, ObservationTracker, Rect


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.layout = Layout(Target(10, "app", "RobloxPlayer", "com.roblox.RobloxPlayer"),
                             "window-1", Rect(-100, 50, 16, 9), (32, 18), "monitor-A", (2, 2))
        self.pixels = bytes(32 * 18 * 3)
        self.tracker = ObservationTracker()

    def frame(self, layout=None, timestamp=10):
        layout = layout or self.layout
        return self.tracker.accept(layout, bytes(layout.physical_size[0] * layout.physical_size[1] * 3),
                                   timestamp, timestamp + 0.1)

    def test_reference_pixel_and_native_units_with_retina_and_negative_origin(self):
        observation = self.frame()
        calibration = self.tracker.calibrate((1600, 900), now=10.1)
        self.assertEqual(calibration.reference_to_pixel(800, 450), (16, 9))
        self.assertEqual(calibration.pixel_to_native(16, 9), (-92, 54.5))
        self.assertIs(self.tracker.require_current(observation, self.layout, 10.2), calibration)

    def test_windows_physical_units_and_fractional_scale(self):
        layout = replace(self.layout, native_content=Rect(1920, 0, 32, 18), scale=(1, 1))
        calibration = Calibration.create(self.frame(layout), (1600, 900))
        self.assertEqual(calibration.pixel_to_native(16, 9), (1936, 9))
        layout = replace(layout, native_content=Rect(1920, 0, 25.6, 14.4), scale=(1.25, 1.25))
        calibration = Calibration.create(self.frame(layout, 11), (1600, 900))
        actual = calibration.pixel_to_native(16, 9)
        self.assertAlmostEqual(actual[0], 1932.8)
        self.assertAlmostEqual(actual[1], 7.2)

    def test_each_layout_change_clears_calibration_and_old_targets(self):
        changes = [dict(native_content=Rect(-99, 50, 16, 9)), dict(monitor_id="monitor-B"),
                   dict(window_id="window-2"), dict(target=replace(self.layout.target, pid=11)),
                   dict(physical_size=(16, 9), scale=(1, 1)),
                   dict(native_content=Rect(-100, 50, 32, 18), scale=(1, 1))]
        for fields in changes:
            with self.subTest(fields=fields):
                self.tracker = ObservationTracker()
                old = self.frame()
                self.tracker.calibrate((1600, 900), now=10.1)
                new = self.frame(replace(self.layout, **fields), 11)
                self.assertIsNone(self.tracker.calibration)
                self.assertGreater(new.generation, old.generation)
                with self.assertRaisesRegex(ValueError, "no longer current"):
                    self.tracker.require_current(old, new.layout, 11.2)

    def test_fresh_frame_reuses_calibration_but_late_callback_does_not(self):
        old = self.frame()
        calibration = self.tracker.calibrate((1600, 900), now=10.1)
        new = self.frame(timestamp=10.2)
        self.assertEqual(old.generation, new.generation)
        self.assertIs(self.tracker.require_current(new, self.layout, 10.3), calibration)
        with self.assertRaises(ValueError):
            self.tracker.require_current(old, self.layout, 10.3)
        self.assertIsNone(self.tracker.calibration)

    def test_stale_future_duplicate_or_failed_capture_invalidates(self):
        for captured, now in ((9, 10), (11, 10), (10, 10.1), (float("nan"), 10)):
            with self.subTest(captured=captured):
                self.tracker = ObservationTracker()
                self.frame()
                self.tracker.calibrate((1600, 900), now=10.1)
                with self.assertRaises(ValueError):
                    self.tracker.accept(self.layout, self.pixels, captured, now)
                self.assertIsNone(self.tracker.calibration)

    def test_aspect_ratio_and_outside_points_rejected_without_stretch(self):
        observation = self.frame()
        with self.assertRaisesRegex(ValueError, "aspect ratio"):
            Calibration.create(observation, (4, 3))
        calibration = Calibration.create(observation, (16, 9))
        for point in ((16, 0), (-1, 0), (0, 9), (float("nan"), 1)):
            with self.subTest(point=point), self.assertRaises(ValueError):
                calibration.reference_to_pixel(*point)
        with self.assertRaises(ValueError):
            calibration.pixel_to_native(32, 9)
        with self.assertRaises(ValueError):
            Calibration.create(observation, (16, 9), Rect(1, 0, 32, 18))

    def test_bad_metadata_and_frame_buffers_rejected(self):
        for change in (dict(scale=(float("nan"), 2)), dict(physical_size=(100000, 100000)),
                       dict(scale=(1, 1)), dict(monitor_id="")):
            with self.subTest(change=change), self.assertRaises(ValueError):
                replace(self.layout, **change)
        with self.assertRaises(ValueError):
            self.tracker.accept(self.layout, b"truncated", 10, 10.1)

    def test_failed_capture_and_expired_calibration_clear_previous_coordinates(self):
        self.frame()
        self.tracker.calibrate((1600, 900), now=10.1)
        with self.assertRaises(ValueError):
            self.tracker.accept(self.layout, b"truncated", 10.2, 10.3)
        self.assertIsNone(self.tracker.calibration)
        self.frame(timestamp=11)
        with self.assertRaises(ValueError):
            self.tracker.calibrate((1600, 900), now=12)
        self.assertIsNone(self.tracker.latest)


if __name__ == "__main__":
    unittest.main()
