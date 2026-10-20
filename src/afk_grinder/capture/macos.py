"""ScreenCaptureKit adapter for a single pinned macOS window.

ScreenCaptureKit exposes a window frame but no documented public client-content
rectangle for another process. It returns an explicitly labelled raw window
preview; calibration must establish content bounds before coordinates may act.
It uses SCScreenshotManager, not CGWindowListCreateImage.
"""

from __future__ import annotations

import importlib
import sys
import threading
from math import isfinite
from time import monotonic
from typing import Any

from afk_grinder.capture import (
    CaptureError,
    CapturedWindow,
    WindowBinding,
    bgrx_to_bgr,
    build_frame,
    capture_error_type,
)
from afk_grinder.models import Target


class MacOSCapture:
    """macOS 14+ capture adapter; it never triggers the Screen Recording prompt."""

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("macOS capture requires macOS (sys.platform == 'darwin').")
        if threading.current_thread() is not threading.main_thread():
            raise CaptureError("macOS capture must initialize on the worker's main thread.",
                               code="unavailable", stage="initialization")
        try:
            self._AppKit = importlib.import_module("AppKit")
            self._Quartz = importlib.import_module("Quartz")
            self._ScreenCaptureKit = importlib.import_module("ScreenCaptureKit")
            self._objc = importlib.import_module("objc")
        except ImportError as error:
            raise RuntimeError(
                "macOS capture requires PyObjC AppKit, Quartz, objc, and ScreenCaptureKit."
            ) from error
        self._at_stage("initialization", self._initialize_display_environment)

    def _initialize_display_environment(self) -> None:
        # Spawned capture workers do not inherit the launcher's NSApplication.
        # Apple's sharedApplication initializes the display/WindowServer
        # connection required by ScreenCaptureKit's window content filter.
        # Never run/finish launching or activate this background application.
        if self._AppKit.NSApp() is not None:
            return
        application = self._AppKit.NSApplication.sharedApplication()
        policy = self._AppKit.NSApplicationActivationPolicyProhibited
        if application is not None and application.activationPolicy() != policy:
            application.setActivationPolicy_(policy)
        if application is None or application.activationPolicy() != policy:
            raise CaptureError("macOS capture worker could not initialize without activation.",
                               code="unavailable", stage="initialization")

    def discover(self, target: Target) -> WindowBinding:
        self._at_stage("initialization", self._require_roblox, target)
        self._at_stage("preflight", self._preflight_screen_recording)
        content = self._at_stage("discovery", self._shareable_content)
        window = self._at_stage("window_selection", self._single_window_for_pid, content, target.pid)
        return self._binding_for_window(content, window, target)

    def capture(self, binding: WindowBinding) -> CapturedWindow:
        started_at = monotonic()
        self._at_stage("initialization", self._require_roblox, binding.target)
        self._at_stage("preflight", self._preflight_screen_recording)
        content = self._at_stage("discovery", self._shareable_content)
        window = self._at_stage(
            "window_selection", self._window_by_id_and_pid, content, binding.window_id, binding.target.pid
        )
        current = self._binding_for_window(content, window, binding.target)
        if current != binding:
            raise CaptureError("macOS window content geometry changed before capture.",
                               code="geometry", stage="frame_validation")
        image = self._at_stage("screenshot", self._capture_window_image, window, binding)
        width, height, pixels = self._at_stage("pixel_conversion", self._bgr8_pixels, image)
        if (width, height) != self._expected_pixels(binding):
            raise CaptureError("macOS capture dimensions differ from the verified window geometry.",
                               code="geometry", stage="frame_validation")
        if not any(pixels):
            raise CaptureError("macOS window capture was all black; refusing an invalid frame.",
                               code="black_frame", stage="frame_validation")
        after_content = self._at_stage("discovery", self._shareable_content)
        after_window = self._at_stage("window_selection", self._window_by_id_and_pid,
            after_content, binding.window_id, binding.target.pid
        )
        after = self._binding_for_window(after_content, after_window, binding.target)
        if after != binding:
            raise CaptureError("macOS window content geometry changed during capture.",
                               code="geometry", stage="frame_validation")
        return self._at_stage(
            "frame_validation", build_frame, binding,
            physical_size=(width, height), pixels=pixels, captured_at=started_at,
        )

    def snapshot(self, target: Target) -> CapturedWindow:
        return self.capture(self.discover(target))

    @staticmethod
    def _at_stage(stage: str, call: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return call(*args, **kwargs)
        except CaptureError:
            raise
        except Exception as error:
            raise CaptureError("macOS capture failed.", code="unexpected", stage=stage,
                               error_type=capture_error_type(error)) from error

    @staticmethod
    def _require_roblox(target: Target) -> None:
        if not target.is_roblox:
            raise CaptureError("macOS capture accepts only a verified Roblox target.",
                               code="unavailable", stage="initialization")

    def _preflight_screen_recording(self) -> None:
        preflight = getattr(self._Quartz, "CGPreflightScreenCaptureAccess", None)
        if not callable(preflight):
            raise CaptureError("macOS Screen Recording preflight is unavailable; permission cannot be verified.",
                               code="unavailable", stage="preflight")
        try:
            if not bool(preflight()):
                raise CaptureError("macOS Screen Recording permission is required; no permission prompt was requested.",
                                   code="permission", stage="preflight")
        except CaptureError:
            raise
        except Exception as error:
            raise CaptureError(f"macOS Screen Recording preflight failed: {error}", code="unexpected",
                               stage="preflight", error_type=capture_error_type(error)) from error

    def _single_window_for_pid(self, content: Any, pid: int) -> Any:
        windows = [window for window in content.windows() if self._qualified_window(window, pid)]
        if not windows:
            raise CaptureError(
                f"macOS expected exactly one capturable window for PID {pid}; found 0.",
                code="window_missing", stage="window_selection",
            )
        if len(windows) > 1:
            raise CaptureError(
                f"macOS expected exactly one capturable window for PID {pid}; found {len(windows)}.",
                code="window_count", stage="window_selection",
            )
        return windows[0]

    def _window_by_id_and_pid(self, content: Any, window_id: str, pid: int) -> Any:
        for window in content.windows():
            if str(window.windowID()) == window_id and self._qualified_window(window, pid):
                return window
        raise CaptureError("macOS bound window was replaced or is no longer capturable.",
                           code="window_missing", stage="window_selection")

    def _shareable_content(self) -> Any:
        # PyObjC exports the Objective-C completion API.  This wait happens on
        # the observation worker, never the UI thread.
        result: dict[str, Any] = {}
        event = __import__("threading").Event()
        def complete(content: Any, error: Any) -> None:
            result.update(content=content, error=error)
            event.set()
        getter = getattr(self._ScreenCaptureKit.SCShareableContent,
                         "getShareableContentWithCompletionHandler_", None)
        if not callable(getter):
            raise CaptureError("macOS ScreenCaptureKit shareable-content API is unavailable.",
                               code="unavailable", stage="discovery")
        getter(complete)
        if not event.wait(5):
            raise CaptureError("macOS ScreenCaptureKit content discovery timed out.",
                               code="timeout", stage="discovery")
        if result.get("error") is not None or result.get("content") is None:
            raise CaptureError(f"macOS ScreenCaptureKit content discovery failed: {result.get('error')}.",
                               code="unavailable", stage="discovery")
        return result["content"]

    @staticmethod
    def _window_pid(window: Any) -> int:
        application = window.owningApplication()
        return int(application.processID()) if application is not None else -1

    @staticmethod
    def _verified_roblox_window(window: Any) -> bool:
        application = window.owningApplication()
        return application is not None and application.bundleIdentifier() == "com.roblox.RobloxPlayer"

    @staticmethod
    def _on_screen(window: Any) -> bool:
        state = getattr(window, "isOnScreen", None)
        if not callable(state):
            raise CaptureError("macOS window visibility is unavailable; refusing capture.",
                               code="unavailable", stage="window_selection")
        return bool(state())

    def _qualified_window(self, window: Any, pid: int) -> bool:
        if (self._window_pid(window) != pid or not self._verified_roblox_window(window)
                or not self._on_screen(window)):
            return False
        layer = float(window.windowLayer())
        frame = window.frame()
        x, y, width, height = (float(frame.origin.x), float(frame.origin.y),
                               float(frame.size.width), float(frame.size.height))
        return (isfinite(layer) and layer == 0 and all(isfinite(value) for value in (x, y, width, height))
                and width >= 320 and height >= 240)

    def _binding_for_window(self, content: Any, window: Any, target: Target) -> WindowBinding:
        content_filter = self._at_stage("filter_geometry", self._content_filter, window)
        frame, point_scale = self._at_stage("filter_geometry", self._filter_geometry, content_filter)
        x, y, width, height = frame
        displays = self._at_stage("display_selection", lambda: content.displays())
        display = self._at_stage("display_selection", self._display_for_rect, displays, frame)
        monitor_id = self._at_stage("display_selection", lambda: int(display.displayID()))
        if monitor_id <= 0:
            raise CaptureError("macOS ScreenCaptureKit display identity is unavailable.",
                               code="unavailable", stage="display_selection")
        return WindowBinding(target, str(window.windowID()), (x, y, width, height), str(monitor_id),
                             (point_scale, point_scale), "window-unverified", False)

    def _filter_geometry(self, content_filter: Any) -> tuple[tuple[int, int, int, int], float]:
        frame = content_filter.contentRect()
        values = (float(frame.origin.x), float(frame.origin.y),
                  float(frame.size.width), float(frame.size.height))
        rect = tuple(round(value) for value in values)
        if any(abs(value - integer) > 0.001 for value, integer in zip(values, rect)):
            raise CaptureError("macOS window bounds are not stable native input units.",
                               code="geometry", stage="filter_geometry")
        x, y, width, height = rect
        if width <= 0 or height <= 0 or width * height > 16_000_000:
            raise CaptureError("macOS window preview bounds are empty, unknown, or too large.",
                               code="geometry", stage="filter_geometry")
        scale = float(content_filter.pointPixelScale())
        if not isfinite(scale) or scale <= 0:
            raise CaptureError("macOS ScreenCaptureKit point-to-pixel scale is unavailable.",
                               code="geometry", stage="filter_geometry")
        if round(width * scale) * round(height * scale) > 16_000_000:
            raise CaptureError("macOS physical window preview exceeds the 16,000,000-pixel safety limit.",
                               code="geometry", stage="filter_geometry")
        return (x, y, width, height), scale

    @staticmethod
    def _display_for_rect(displays: Any, rect: tuple[int, int, int, int]) -> Any:
        x, y, width, height = rect
        matches: list[Any] = []
        for display in displays:
            frame = display.frame()
            if (x >= frame.origin.x and y >= frame.origin.y and
                    x + width <= frame.origin.x + frame.size.width and
                    y + height <= frame.origin.y + frame.size.height):
                matches.append(display)
        if len(matches) != 1:
            raise CaptureError("macOS bound window spans or lacks a uniquely identified monitor.",
                               code="geometry", stage="display_selection")
        return matches[0]

    def _content_filter(self, window: Any) -> Any:
        return self._ScreenCaptureKit.SCContentFilter.alloc().initWithDesktopIndependentWindow_(window)

    def _capture_window_image(self, window: Any, binding: WindowBinding) -> Any:
        configuration = self._ScreenCaptureKit.SCStreamConfiguration.alloc().init()
        configuration.setShowsCursor_(False)
        configuration.setIgnoreShadowsSingleWindow_(True)
        content_filter = self._content_filter(window)
        frame, point_scale = self._filter_geometry(content_filter)
        if frame != binding.native_rect or (point_scale, point_scale) != binding.scale:
            raise CaptureError("macOS ScreenCaptureKit filter geometry changed before capture.",
                               code="geometry", stage="screenshot")
        output_width, output_height = self._expected_pixels(binding)
        configuration.setWidth_(output_width)
        configuration.setHeight_(output_height)
        result: dict[str, Any] = {}
        event = __import__("threading").Event()
        def complete(image: Any, error: Any) -> None:
            result.update(image=image, error=error)
            event.set()
        self._ScreenCaptureKit.SCScreenshotManager.captureImageWithFilter_configuration_completionHandler_(
            content_filter, configuration, complete
        )
        if not event.wait(5):
            raise CaptureError("macOS ScreenCaptureKit image capture timed out.",
                               code="timeout", stage="screenshot")
        if result.get("error") is not None or result.get("image") is None:
            raise CaptureError(f"macOS ScreenCaptureKit image capture failed: {result.get('error')}.",
                               code="unavailable", stage="screenshot")
        return result["image"]

    def _bgr8_pixels(self, image: Any) -> tuple[int, int, bytes]:
        width = int(self._Quartz.CGImageGetWidth(image))
        height = int(self._Quartz.CGImageGetHeight(image))
        if width <= 0 or height <= 0 or width * height > 16_000_000:
            raise CaptureError("macOS capture dimensions are empty, unknown, or too large.",
                               code="conversion", stage="pixel_conversion")
        color_space = self._Quartz.CGColorSpaceCreateDeviceRGB()
        bitmap_info = self._Quartz.kCGImageAlphaNoneSkipFirst | self._Quartz.kCGBitmapByteOrder32Little
        context = self._Quartz.CGBitmapContextCreate(None, width, height, 8, width * 4, color_space, bitmap_info)
        if context is None:
            raise CaptureError("macOS could not create a BGR8 capture conversion context.",
                               code="conversion", stage="pixel_conversion")
        # PyObjC owns the CGContext reference. Calling CGContextRelease here
        # releases it twice when the bridge later destroys its Python proxy.
        self._Quartz.CGContextDrawImage(context, self._Quartz.CGRectMake(0, 0, width, height), image)
        address = self._Quartz.CGBitmapContextGetData(context)
        as_buffer = getattr(address, "as_buffer", None)
        if not callable(as_buffer):
            raise CaptureError("macOS BGR8 capture conversion returned no readable pixel data.",
                               code="conversion", stage="pixel_conversion")
        byte_count = width * height * 4
        try:
            # A Quartz void pointer is an objc.varlist, not a ctypes address or
            # Python buffer. Copy its documented, allocation-bounded view while
            # the owning context is still alive.
            raw = bytes(as_buffer(byte_count))
        except (TypeError, ValueError, BufferError) as error:
            raise CaptureError("macOS BGR8 capture conversion could not read its pixel buffer.",
                               code="conversion", stage="pixel_conversion",
                               error_type=capture_error_type(error)) from error
        if len(raw) != byte_count:
            raise CaptureError("macOS BGR8 capture conversion returned a short pixel buffer.",
                               code="conversion", stage="pixel_conversion")
        try:
            pixels = bgrx_to_bgr(raw, width * height)
        except (TypeError, ValueError, BufferError) as error:
            raise CaptureError("macOS BGR8 capture conversion could not validate its pixel buffer.",
                               code="conversion", stage="pixel_conversion",
                               error_type=capture_error_type(error)) from error
        return width, height, pixels

    @staticmethod
    def _expected_pixels(binding: WindowBinding) -> tuple[int, int]:
        return (round(binding.native_rect[2] * binding.scale[0]), round(binding.native_rect[3] * binding.scale[1]))
