"""Capture adapters are exercised with fakes; these tests never read the desktop."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import sys
import tracemalloc
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afk_grinder.capture import CaptureError, WindowBinding, bgrx_to_bgr, build_frame
from afk_grinder.capture.macos import MacOSCapture
from afk_grinder.capture.windows import WindowsCapture
from afk_grinder.models import Target


TARGET = Target(42, "700", "RobloxPlayerBeta.exe", "win32")
BINDING = WindowBinding(
    target=TARGET,
    window_id="700",
    native_rect=(20, 30, 2, 1),
    monitor_id="monitor-1",
    scale=(1.5, 1.5),
)
MAC_BINDING = WindowBinding(
    target=TARGET,
    window_id="700",
    native_rect=(20, 30, 2, 1),
    monitor_id="monitor-1",
    scale=(1.0, 1.0),
    region_kind="window-unverified",
    content_verified=False,
)


class FakeWindowsCapture(WindowsCapture):
    def __init__(self, bindings: list[WindowBinding], pixels: bytes) -> None:
        self.bindings = iter(bindings)
        self.pixels = pixels

    def _per_monitor_v2(self):
        return nullcontext()

    def _read_binding(self, target: Target) -> WindowBinding:
        self.last_target = target
        return next(self.bindings)

    def _print_client_bgr(self, binding: WindowBinding) -> bytes:
        self.printed = binding
        return self.pixels


class FakeWindowApplication:
    def __init__(self, pid: int, bundle: str = "com.roblox.RobloxPlayer") -> None:
        self.pid = pid
        self.bundle = bundle

    def processID(self) -> int:
        return self.pid

    def bundleIdentifier(self) -> str:
        return self.bundle


class FakeWindow:
    def __init__(self, window_id: int, pid: int) -> None:
        self.window_id = window_id
        self.application = FakeWindowApplication(pid)

    def windowID(self) -> int:
        return self.window_id

    def owningApplication(self) -> FakeWindowApplication:
        return self.application

    def isOnScreen(self) -> bool:
        return True


class FakeContent:
    def __init__(self, windows: list[FakeWindow]) -> None:
        self._windows = windows

    def windows(self) -> list[FakeWindow]:
        return self._windows


class FakeQuartz:
    def __init__(self, allowed: bool) -> None:
        self.allowed = allowed
        self.calls = 0

    def CGPreflightScreenCaptureAccess(self) -> bool:
        self.calls += 1
        return self.allowed


class FakeFrame:
    def __init__(self, x: int, y: int, width: int, height: int) -> None:
        self.origin = type("Origin", (), {"x": x, "y": y})()
        self.size = type("Size", (), {"width": width, "height": height})()


class FakeFilter:
    def __init__(self, frame: FakeFrame, scale: float) -> None:
        self.frame, self.scale = frame, scale

    def contentRect(self) -> FakeFrame:
        return self.frame

    def pointPixelScale(self) -> float:
        return self.scale


class FakeConfiguration:
    def __init__(self) -> None:
        self.cursor = self.shadows = None
        self.width = self.height = None

    def setShowsCursor_(self, value: bool) -> None:
        self.cursor = value

    def setIgnoreShadowsSingleWindow_(self, value: bool) -> None:
        self.shadows = value

    def setWidth_(self, value: int) -> None:
        self.width = value

    def setHeight_(self, value: int) -> None:
        self.height = value


class FakeAllocator:
    def __init__(self, value: object) -> None:
        self.value = value

    def alloc(self):
        return self

    def init(self):
        return self.value


class FakeScreenshotManager:
    def __init__(self, configuration: FakeConfiguration) -> None:
        self.configuration = configuration

    def captureImageWithFilter_configuration_completionHandler_(self, content_filter, configuration, complete) -> None:
        if configuration is not self.configuration:
            raise AssertionError("unexpected configuration")
        complete("non-1080p-image", None)


class CaptureContractTests(unittest.TestCase):
    def test_bgr8_frame_keeps_only_client_content_dimensions(self) -> None:
        # The adapter passes the verified client rectangle, never a title-bar-sized
        # window rectangle, into the frame contract.
        frame = build_frame(BINDING, physical_size=(2, 1), pixels=b"\x01\x02\x03\x04\x05\x06", captured_at=2.5)

        self.assertEqual(frame.native_rect, (20, 30, 2, 1))
        self.assertEqual(frame.physical_size, (2, 1))
        self.assertEqual(frame.pixels, b"\x01\x02\x03\x04\x05\x06")
        self.assertEqual(frame.format, "BGR8")

    def test_invalid_pixel_length_and_large_frame_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "does not match"):
            build_frame(BINDING, physical_size=(2, 1), pixels=b"\x01", captured_at=1)
        huge = WindowBinding(TARGET, "700", (0, 0, 4001, 4000), "m", (1, 1))
        with self.assertRaisesRegex(ValueError, "16,000,000"):
            build_frame(huge, physical_size=(4001, 4000), pixels=b"", captured_at=1)

    def test_nan_timestamp_scale_and_mutable_pixels_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite"):
            build_frame(BINDING, physical_size=(2, 1), pixels=b"\x01" * 6, captured_at=float("nan"))
        bad_scale = WindowBinding(TARGET, "700", (0, 0, 2, 1), "m", (float("nan"), 1))
        with self.assertRaisesRegex(ValueError, "finite"):
            build_frame(bad_scale, physical_size=(2, 1), pixels=b"\x01" * 6, captured_at=1)
        with self.assertRaisesRegex(ValueError, "immutable"):
            build_frame(BINDING, physical_size=(2, 1), pixels=bytearray(6), captured_at=1)
        dishonest_preview = WindowBinding(
            TARGET, "700", (0, 0, 2, 1), "m", (1, 1), "window-unverified", True
        )
        with self.assertRaisesRegex(ValueError, "cannot claim"):
            build_frame(dishonest_preview, physical_size=(2, 1), pixels=b"\x01" * 6, captured_at=1)

    def test_bgrx_conversion_has_bounded_linear_memory(self) -> None:
        pixels = 1_000_000
        raw = bytearray(pixels * 4)
        raw[0:4] = b"\x01\x02\x03\xff"
        raw[-4:] = b"\x04\x05\x06\xff"
        tracemalloc.start()
        converted = bgrx_to_bgr(raw, pixels)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        self.assertEqual(converted[:3], b"\x01\x02\x03")
        self.assertEqual(converted[-3:], b"\x04\x05\x06")
        self.assertLess(peak, 10_000_000)


class WindowsCaptureTests(unittest.TestCase):
    def test_capture_uses_pinned_client_binding_and_bgr_content(self) -> None:
        adapter = FakeWindowsCapture([BINDING, BINDING], b"\x01\x02\x03\x04\x05\x06")

        frame = adapter.capture(BINDING)

        self.assertEqual(adapter.last_target, TARGET)
        self.assertEqual(adapter.printed, BINDING)
        self.assertEqual(frame.window_id, "700")
        self.assertEqual(frame.physical_size, (2, 1))
        self.assertGreaterEqual(frame.captured_at, 0)

    def test_geometry_or_window_replacement_after_capture_is_rejected(self) -> None:
        replacement = WindowBinding(TARGET, "701", (20, 30, 2, 1), "monitor-1", (1.5, 1.5))
        adapter = FakeWindowsCapture([BINDING, replacement], b"\x01\x02\x03\x04\x05\x06")

        with self.assertRaisesRegex(CaptureError, "changed during capture"):
            adapter.capture(BINDING)

    def test_black_or_failed_client_buffers_are_rejected(self) -> None:
        adapter = FakeWindowsCapture([BINDING], b"\x00" * 6)
        with self.assertRaisesRegex(CaptureError, "all black"):
            adapter.capture(BINDING)

        adapter = FakeWindowsCapture([BINDING], b"\x01")
        with self.assertRaisesRegex(CaptureError, "unexpected pixel buffer"):
            adapter.capture(BINDING)

    def test_non_roblox_target_is_rejected_before_native_capture(self) -> None:
        other = Target(42, "700", "other.exe", "win32")
        adapter = FakeWindowsCapture([], b"")
        with self.assertRaisesRegex(CaptureError, "verified Roblox"):
            adapter.discover(other)


class MacOSCaptureTests(unittest.TestCase):
    @staticmethod
    def _fake_capture(bindings: list[WindowBinding], result: tuple[int, int, bytes]) -> MacOSCapture:
        adapter = object.__new__(MacOSCapture)
        sequence = iter(bindings)
        adapter._preflight_screen_recording = lambda: None
        adapter._shareable_content = lambda: object()
        adapter._window_by_id_and_pid = lambda content, window_id, pid: object()
        adapter._binding_for_window = lambda content, window, target: next(sequence)
        adapter._capture_window_image = lambda window, binding: object()
        adapter._bgr8_pixels = lambda image: result
        return adapter

    def test_permission_preflight_denial_never_requests_or_captures(self) -> None:
        adapter = object.__new__(MacOSCapture)
        quartz = FakeQuartz(allowed=False)
        adapter._Quartz = quartz

        with self.assertRaisesRegex(CaptureError, "permission is required"):
            adapter._preflight_screen_recording()
        self.assertEqual(quartz.calls, 1)

    def test_raw_window_preview_is_explicitly_not_client_content(self) -> None:
        adapter = object.__new__(MacOSCapture)
        adapter._Quartz = FakeQuartz(allowed=True)
        adapter._shareable_content = lambda: FakeContent([FakeWindow(700, 42)])
        preview = WindowBinding(
            TARGET, "700", (0, 0, 2, 1), "screen-1", (2, 2), "window-unverified", False
        )
        adapter._binding_for_window = lambda content, window, target: preview

        self.assertEqual(adapter.discover(TARGET), preview)
        self.assertEqual(preview.region_kind, "window-unverified")
        self.assertFalse(preview.content_verified)

    def test_window_identity_lookup_rejects_replacement(self) -> None:
        adapter = object.__new__(MacOSCapture)
        adapter._shareable_content = lambda: FakeContent([FakeWindow(701, 42)])

        with self.assertRaisesRegex(CaptureError, "replaced"):
            adapter._window_by_id_and_pid(adapter._shareable_content(), "700", 42)

    def test_filter_sets_exact_non_1080p_output_and_window_shadow_selector(self) -> None:
        adapter = object.__new__(MacOSCapture)
        configuration = FakeConfiguration()
        content_filter = FakeFilter(FakeFrame(0, 0, 1500, 900), 2.0)
        adapter._content_filter = lambda window: content_filter
        adapter._ScreenCaptureKit = type(
            "FakeSCK", (), {
                "SCStreamConfiguration": FakeAllocator(configuration),
                "SCScreenshotManager": FakeScreenshotManager(configuration),
            }
        )()
        binding = WindowBinding(
            TARGET, "700", (0, 0, 1500, 900), "1", (2.0, 2.0), "window-unverified", False
        )

        image = adapter._capture_window_image(FakeWindow(700, 42), binding)

        self.assertEqual(image, "non-1080p-image")
        self.assertFalse(configuration.cursor)
        self.assertTrue(configuration.shadows)
        self.assertEqual((configuration.width, configuration.height), (3000, 1800))

    def test_capture_rejects_post_capture_replacement_and_bad_frames(self) -> None:
        pixels = b"\x01\x02\x03\x04\x05\x06"
        replacement = WindowBinding(
            TARGET, "701", (20, 30, 2, 1), "monitor-1", (1, 1), "window-unverified", False
        )
        adapter = self._fake_capture([MAC_BINDING, replacement], (2, 1, pixels))
        with self.assertRaisesRegex(CaptureError, "changed during capture"):
            adapter.capture(MAC_BINDING)

        adapter = self._fake_capture([MAC_BINDING], (3, 1, b"\x01" * 9))
        with self.assertRaisesRegex(CaptureError, "dimensions differ"):
            adapter.capture(MAC_BINDING)

        adapter = self._fake_capture([MAC_BINDING], (2, 1, b"\x00" * 6))
        with self.assertRaisesRegex(CaptureError, "all black"):
            adapter.capture(MAC_BINDING)


if __name__ == "__main__":
    unittest.main()
