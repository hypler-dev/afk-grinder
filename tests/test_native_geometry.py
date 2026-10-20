"""Synthetic public geometry metadata; no real windows or native input."""

from contextlib import nullcontext
from dataclasses import replace
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from afk_grinder.recognition.native_geometry import require_unchanged
from tests.test_popup_session import RAW


class NativeGeometryTests(unittest.TestCase):
    def test_mac_top_left_negative_origin_and_scale_revalidate_without_titles(self):
        bounds = {"X": -900., "Y": 40., "Width": 800., "Height": 600.}
        windows = [{"number": 456, "pid": RAW.target.pid, "layer": 0, "bounds": bounds}]
        screen = SimpleNamespace(deviceDescription=lambda: {"NSScreenNumber": 7}, backingScaleFactor=lambda: 1.)
        quartz = SimpleNamespace(kCGWindowListOptionOnScreenOnly=1, kCGWindowListExcludeDesktopElements=2,
                                 kCGNullWindowID=0, kCGWindowNumber="number", kCGWindowOwnerPID="pid",
                                 kCGWindowLayer="layer", kCGWindowBounds="bounds",
                                 CGWindowListCopyWindowInfo=lambda *_: windows,
                                 CGDisplayBounds=lambda *_: SimpleNamespace(origin=SimpleNamespace(x=-1000, y=0),
                                                                            size=SimpleNamespace(width=1200, height=900)))
        appkit = SimpleNamespace(NSScreen=SimpleNamespace(screens=lambda: [screen]))
        with patch("afk_grinder.recognition.native_geometry.sys.platform", "darwin"), patch.dict(
                "sys.modules", {"Quartz": quartz, "AppKit": appkit,
                                "objc": SimpleNamespace(autorelease_pool=nullcontext)}):
            layout = replace(RAW, monitor_id="7")
            require_unchanged(layout)
            for invalid in (replace(layout, monitor_id="8"), replace(layout, display_scale=(2., 2.)),
                            replace(layout, window_id="457")):
                with self.assertRaisesRegex(RuntimeError, "geometry changed"):
                    require_unchanged(invalid)
            bounds["X"] += 1
            with self.assertRaises(RuntimeError):
                require_unchanged(layout)


if __name__ == "__main__":
    unittest.main()
