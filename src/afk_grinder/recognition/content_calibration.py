"""Human-attested, in-memory content crops for raw window observations.

This module has no UI, capture, input, or persistence API.  A calibration is
valid only for the exact raw ``Layout`` it was attested against.  It turns one
raw BGR observation into a verified client observation without stretching or
retaining the source frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from afk_grinder.recognition.observation import Layout, Observation, Rect


PhysicalViewport = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class ContentCalibration:
    """One manually attested physical-pixel viewport for one raw window layout."""

    source_layout: Layout
    viewport: PhysicalViewport
    method: str

    def __post_init__(self) -> None:
        if type(self.source_layout) is not Layout:
            raise TypeError("Content calibration requires a raw Layout.")
        if self.method != "manual":
            raise ValueError("Content calibration requires explicit manual attestation.")
        _validate_viewport(self.viewport, self.source_layout.physical_size)

    @classmethod
    def manual(cls, source_layout: Layout, viewport: PhysicalViewport) -> "ContentCalibration":
        """Record a human-attested raw physical viewport; no automatic detection exists here."""
        return cls(source_layout, viewport, "manual")

    def crop(self, observation: Observation) -> Observation:
        """Crop one matching raw BGR observation and preserve its identity metadata."""
        if type(observation) is not Observation:
            raise TypeError("Content calibration requires an Observation.")
        if observation.layout != self.source_layout:
            raise ValueError("Raw source layout changed; content calibration is invalid.")
        x, y, width, height = self.viewport
        source_width, source_height = self.source_layout.physical_size
        pixels = _crop_bgr(observation.pixels, source_width, source_height, x, y, width, height)
        return Observation(
            _client_layout(self.source_layout, self.viewport),
            observation.captured_at,
            observation.generation,
            observation.sequence,
            pixels,
        )


def _validate_viewport(viewport: Any, source_size: tuple[int, int]) -> None:
    if (
        type(viewport) is not tuple
        or len(viewport) != 4
        or any(type(value) is not int for value in viewport)
    ):
        raise ValueError("Content viewport must contain four integer physical-pixel values.")
    x, y, width, height = viewport
    source_width, source_height = source_size
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > source_width or y + height > source_height:
        raise ValueError("Content viewport must lie inside the raw physical frame.")


def _client_layout(source: Layout, viewport: PhysicalViewport) -> Layout:
    x, y, width, height = viewport
    source_width, source_height = source.physical_size
    native = source.native_content
    native_x = native.x + native.width * x / source_width
    native_y = native.y + native.height * y / source_height
    native_width = native.width * width / source_width
    native_height = native.height * height / source_height
    return Layout(
        target=source.target,
        window_id=source.window_id,
        native_content=Rect(native_x, native_y, native_width, native_height),
        physical_size=(width, height),
        monitor_id=source.monitor_id,
        scale=(width / native_width, height / native_height),
        display_scale=source.display_scale,
        region_kind="client",
        content_verified=True,
    )


def _crop_bgr(
    pixels: bytes,
    source_width: int,
    source_height: int,
    x: int,
    y: int,
    width: int,
    height: int,
) -> bytes:
    """Copy selected packed-BGR rows exactly; no scaling or source retention."""
    if len(pixels) != source_width * source_height * 3:
        raise ValueError("Raw observation pixel buffer is invalid.")
    stride = source_width * 3
    row_bytes = width * 3
    offset = x * 3
    return b"".join(
        pixels[(y + row) * stride + offset:(y + row) * stride + offset + row_bytes]
        for row in range(height)
    )
