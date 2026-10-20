"""Capture-to-observation geometry preserves measured and display scale separately."""

from dataclasses import replace
import unittest

from afk_grinder.capture import CapturedWindow
from afk_grinder.models import Target
from afk_grinder.recognition.frame_geometry import layout_from_capture
from afk_grinder.recognition.observation import Rect


TARGET = Target(10, "app", "RobloxPlayer", "com.roblox.RobloxPlayer")


def capture(
    *,
    native_rect: tuple[int, int, int, int] = (1920, 0, 20, 10),
    physical_size: tuple[int, int] = (20, 10),
    scale: tuple[float, float] = (1.0, 1.0),
    monitor_id: str = "monitor-A",
    window_id: str = "window-1",
    region_kind: str = "client",
    content_verified: bool = True,
) -> CapturedWindow:
    return CapturedWindow(
        target=TARGET,
        window_id=window_id,
        native_rect=native_rect,
        physical_size=physical_size,
        monitor_id=monitor_id,
        scale=scale,
        pixels=bytes(physical_size[0] * physical_size[1] * 3),
        format="BGR8",
        captured_at=1.0,
        region_kind=region_kind,
        content_verified=content_verified,
    )


class FrameGeometryTests(unittest.TestCase):
    def test_windows_150_percent_dpi_keeps_physical_native_one_to_one(self):
        layout = layout_from_capture(capture(scale=(1.5, 1.5)))

        self.assertEqual(layout.scale, (1.0, 1.0))
        self.assertEqual(layout.display_scale, (1.5, 1.5))
        self.assertEqual(layout.native_content, Rect(1920, 0, 20, 10))

    def test_mac_retina_uses_measured_two_to_one_and_keeps_raw_preview_uncertainty(self):
        layout = layout_from_capture(capture(
            native_rect=(-50, 40, 20, 10),
            physical_size=(40, 20),
            scale=(2.0, 2.0),
            region_kind="window-unverified",
            content_verified=False,
        ))

        self.assertEqual(layout.scale, (2.0, 2.0))
        self.assertEqual(layout.display_scale, (2.0, 2.0))
        self.assertEqual(layout.native_content, Rect(-50, 40, 20, 10))
        self.assertEqual(layout.region_kind, "window-unverified")
        self.assertFalse(layout.content_verified)

    def test_display_metadata_and_geometry_changes_make_distinct_layouts(self):
        layout = layout_from_capture(capture(scale=(1.5, 1.5)))
        dpi_only = layout_from_capture(capture(scale=(2.0, 2.0)))
        self.assertNotEqual(layout, dpi_only)

        for changed in (
            replace(layout, region_kind="window-unverified", content_verified=False),
            replace(layout, window_id="window-2"),
            replace(layout, monitor_id="monitor-B"),
            replace(layout, native_content=Rect(1921, 0, 20, 10)),
        ):
            with self.subTest(changed=changed):
                self.assertNotEqual(layout, changed)

    def test_layout_rejects_invalid_new_metadata(self):
        layout = layout_from_capture(capture())
        for changed in (
            dict(display_scale=(float("nan"), 1.0)),
            dict(display_scale=(True, 1.0)),
            dict(region_kind="unknown"),
            dict(region_kind="client", content_verified=False),
            dict(region_kind="window-unverified", content_verified=True),
        ):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                replace(layout, **changed)


if __name__ == "__main__":
    unittest.main()
