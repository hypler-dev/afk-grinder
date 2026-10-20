"""Synthetic-only checks for manually attested in-memory content calibration."""

from __future__ import annotations

from dataclasses import replace
import unittest

from afk_grinder.models import Target
from afk_grinder.recognition.content_calibration import ContentCalibration
from afk_grinder.recognition.observation import Layout, Observation, Rect


TARGET = Target(7, "window", "RobloxPlayer", "com.roblox.RobloxPlayer")


def raw_layout() -> Layout:
    return Layout(
        TARGET,
        "window-7",
        Rect(-50, 10, 4, 3),
        (8, 6),
        "monitor-A",
        (2, 2),
        display_scale=(2, 2),
        region_kind="window-unverified",
        content_verified=False,
    )


def pixels(width: int, height: int) -> bytes:
    return bytes(component for y in range(height) for x in range(width) for component in (x, y, x + y))


def observation(layout: Layout | None = None, *, captured_at: float = 12.5, generation: int = 3, sequence: int = 9) -> Observation:
    active = raw_layout() if layout is None else layout
    width, height = active.physical_size
    return Observation(active, captured_at, generation, sequence, pixels(width, height))


class ContentCalibrationTests(unittest.TestCase):
    def test_manual_crop_preserves_identity_and_transforms_negative_native_coordinates(self):
        source = raw_layout()
        calibration = ContentCalibration.manual(source, (2, 1, 4, 3))
        raw = observation(source)

        cropped = calibration.crop(raw)

        self.assertEqual(calibration.method, "manual")
        self.assertEqual((cropped.captured_at, cropped.generation, cropped.sequence), (12.5, 3, 9))
        self.assertEqual(cropped.layout.physical_size, (4, 3))
        self.assertEqual(cropped.layout.native_content, Rect(-49, 10.5, 2, 1.5))
        self.assertEqual(cropped.layout.scale, (2, 2))
        self.assertEqual(cropped.layout.display_scale, (2, 2))
        self.assertEqual((cropped.layout.region_kind, cropped.layout.content_verified), ("client", True))
        self.assertEqual(cropped.pixels, b"".join(
            raw.pixels[(row * 8 + 2) * 3:(row * 8 + 6) * 3] for row in range(1, 4)
        ))

    def test_arbitrary_aspect_crop_never_stretches_pixels(self):
        raw = observation()
        cropped = ContentCalibration.manual(raw.layout, (1, 0, 5, 2)).crop(raw)

        self.assertEqual(cropped.layout.physical_size, (5, 2))
        self.assertEqual(cropped.layout.native_content, Rect(-49.5, 10, 2.5, 1))
        self.assertEqual(cropped.pixels, b"".join(
            raw.pixels[(row * 8 + 1) * 3:(row * 8 + 6) * 3] for row in range(2)
        ))

    def test_source_layout_mismatch_invalidates_crop_for_identity_geometry_and_dpi_changes(self):
        source = raw_layout()
        calibration = ContentCalibration.manual(source, (0, 0, 4, 3))
        changes = (
            dict(window_id="replacement"),
            dict(target=replace(TARGET, pid=8)),
            dict(monitor_id="monitor-B"),
            dict(native_content=Rect(-49, 10, 4, 3)),
            dict(display_scale=(1.5, 1.5)),
            dict(physical_size=(4, 3), native_content=Rect(-50, 10, 2, 1.5), scale=(2, 2)),
        )
        for fields in changes:
            with self.subTest(fields=fields):
                changed = replace(source, **fields)
                with self.assertRaisesRegex(ValueError, "layout changed"):
                    calibration.crop(observation(changed))

    def test_rejects_invalid_manual_attestation_and_viewport_bounds(self):
        source = raw_layout()
        invalid_viewports = (
            [0, 0, 1, 1], (True, 0, 1, 1), (-1, 0, 1, 1), (0, -1, 1, 1),
            (0, 0, 0, 1), (0, 0, 1, 0), (7, 0, 2, 1), (0, 5, 1, 2),
        )
        for viewport in invalid_viewports:
            with self.subTest(viewport=viewport), self.assertRaises(ValueError):
                ContentCalibration.manual(source, viewport)

        native = replace(source, region_kind="client", content_verified=True)
        self.assertEqual(ContentCalibration.manual(native, (0, 0, 1, 1)).crop(observation(native)).layout.physical_size, (1, 1))
        with self.assertRaisesRegex(ValueError, "manual attestation"):
            ContentCalibration(source, (0, 0, 1, 1), "automatic")
        with self.assertRaises(TypeError):
            ContentCalibration.manual(object(), (0, 0, 1, 1))

    def test_crop_rejects_wrong_observation_type_and_cannot_change_freshness_identity(self):
        calibration = ContentCalibration.manual(raw_layout(), (0, 0, 1, 1))
        with self.assertRaises(TypeError):
            calibration.crop(object())

        raw = observation(captured_at=0.0, generation=1, sequence=1)
        cropped = calibration.crop(raw)
        self.assertEqual((cropped.captured_at, cropped.generation, cropped.sequence), (0.0, 1, 1))
        self.assertNotEqual(cropped.layout, raw.layout)


if __name__ == "__main__":
    unittest.main()
