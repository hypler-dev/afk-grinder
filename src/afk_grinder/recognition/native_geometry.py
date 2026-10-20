"""Read-only geometry revalidation immediately before a positioned click."""

import sys

from .observation import Layout


def require_unchanged(source: Layout) -> None:
    """Never activate a window or infer content from window decoration metrics."""
    try:
        if sys.platform == "win32":
            from afk_grinder.capture.windows import WindowsCapture
            binding = WindowsCapture().discover(source.target)
            bounds = source.native_content
            if (binding.window_id != source.window_id
                    or binding.native_rect != (bounds.x, bounds.y, bounds.width, bounds.height)
                    or binding.monitor_id != source.monitor_id or binding.scale != source.display_scale):
                raise ValueError()
        elif sys.platform == "darwin":
            import AppKit
            import Quartz
            import objc
            with objc.autorelease_pool():
                options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
                windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
                matches = [item for item in windows
                           if str(item.get(Quartz.kCGWindowNumber)) == source.window_id
                           and item.get(Quartz.kCGWindowOwnerPID) == source.target.pid
                           and item.get(Quartz.kCGWindowLayer) == 0]
                if len(matches) != 1 or source.region_kind != "window-unverified":
                    raise ValueError()
                bounds = matches[0][Quartz.kCGWindowBounds]
                expected = source.native_content
                if tuple(float(bounds[key]) for key in ("X", "Y", "Width", "Height")) != (
                        expected.x, expected.y, expected.width, expected.height):
                    raise ValueError()
                screens = AppKit.NSScreen.screens()
                contained = []
                for screen in screens:
                    display_id = int(screen.deviceDescription()["NSScreenNumber"])
                    # Quartz display/window bounds share top-left global units;
                    # do not mix them with AppKit's bottom-left frame origin.
                    frame = Quartz.CGDisplayBounds(display_id)
                    x, y = float(frame.origin.x), float(frame.origin.y)
                    if (expected.x >= x and expected.y >= y
                            and expected.x + expected.width <= x + frame.size.width
                            and expected.y + expected.height <= y + frame.size.height):
                        contained.append(screen)
                if len(contained) != 1:
                    raise ValueError()
                screen = contained[0]
                scale = float(screen.backingScaleFactor())
                if (str(screen.deviceDescription()["NSScreenNumber"]) != source.monitor_id
                        or source.display_scale != (scale, scale)):
                    raise ValueError()
        else:
            raise ValueError()
    except Exception:
        raise RuntimeError("Window geometry changed or cannot be verified; recalibrate content.") from None
