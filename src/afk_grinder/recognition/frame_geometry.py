"""Bridge validated in-memory capture metadata into observation geometry.

This module does not load native capture SDKs, retain frame pixels, identify
content, or authorize input.  ``Layout.scale`` is measured physical-pixels per
native-input-unit; ``Layout.display_scale`` retains platform display metadata.
"""

from afk_grinder.capture import CapturedWindow
from afk_grinder.recognition.observation import Layout, Rect


def layout_from_capture(frame: CapturedWindow) -> Layout:
    """Build geometry from one validated capture without inferring DPI conversions."""
    if not isinstance(frame, CapturedWindow):
        raise TypeError("layout_from_capture requires a CapturedWindow.")
    x, y, native_width, native_height = frame.native_rect
    physical_width, physical_height = frame.physical_size
    return Layout(
        target=frame.target,
        window_id=frame.window_id,
        native_content=Rect(x, y, native_width, native_height),
        physical_size=frame.physical_size,
        monitor_id=frame.monitor_id,
        scale=(physical_width / native_width, physical_height / native_height),
        display_scale=frame.scale,
        region_kind=frame.region_kind,
        content_verified=frame.content_verified,
    )
