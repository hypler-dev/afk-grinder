"""Exercise real PyObjC worker initialization and synthetic pixels, never capture."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest


@unittest.skipUnless(sys.platform == "darwin" and importlib.util.find_spec("Quartz"), "Requires macOS Quartz")
class MacOSPixelBridgeTests(unittest.TestCase):
    def test_capture_worker_display_bootstrap_without_capture_or_activation(self) -> None:
        program = """
import AppKit
from afk_grinder.capture.macos import MacOSCapture
assert AppKit.NSApp() is None
adapter = MacOSCapture()
application = AppKit.NSApp()
assert application is not None
assert application.activationPolicy() == AppKit.NSApplicationActivationPolicyProhibited
assert not application.isActive()
assert len(application.windows()) == 0
assert len(AppKit.NSScreen.screens()) > 0
print('background display initialization passed')
"""
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", program],
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "background display initialization passed")

    def test_synthetic_conversion_and_bridge_cleanup_in_child(self) -> None:
        # A child contains a bridge ownership regression: an explicit release
        # previously crashed during garbage collection rather than conversion.
        program = """
import gc
import Quartz
from afk_grinder.capture.macos import MacOSCapture
adapter = object.__new__(MacOSCapture)
adapter._Quartz = Quartz
for red, green, blue, bgr in ((1, 0, 0, b'\\x00\\x00\\xff'), (0, 0, 1, b'\\xff\\x00\\x00')):
    for _ in range(20):
        space = Quartz.CGColorSpaceCreateDeviceRGB()
        context = Quartz.CGBitmapContextCreate(None, 2, 2, 8, 8, space,
            Quartz.kCGImageAlphaNoneSkipFirst | Quartz.kCGBitmapByteOrder32Little)
        Quartz.CGContextSetRGBFillColor(context, red, green, blue, 1)
        Quartz.CGContextFillRect(context, Quartz.CGRectMake(0, 0, 2, 2))
        image = Quartz.CGBitmapContextCreateImage(context)
        assert adapter._bgr8_pixels(image) == (2, 2, bgr * 4)
        del image, context, space
        gc.collect()
print('synthetic conversion and bridge cleanup passed')
"""
        result = subprocess.run(
            [sys.executable, "-X", "faulthandler", "-c", program],
            capture_output=True, text=True, timeout=15, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "synthetic conversion and bridge cleanup passed")


if __name__ == "__main__":
    unittest.main()
