"""Immutable frame metadata and explicit reference/pixel/native coordinates.

This module has no capture or input APIs. Calibration is geometry evidence only;
it does not authorize actions or establish that gameplay is visible.
"""

from dataclasses import dataclass
import math

from afk_grinder.models import Target

MAX_PIXELS = 16_000_000


def _finite(*values: float) -> bool:
    try:
        return all(type(value) in (int, float) and math.isfinite(value) for value in values)
    except OverflowError:
        return False


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self):
        if not _finite(self.x, self.y, self.width, self.height) or min(self.width, self.height) <= 0:
            raise ValueError("Rectangle coordinates must be finite with positive dimensions.")


@dataclass(frozen=True)
class Layout:
    target: Target
    window_id: str
    native_content: Rect
    physical_size: tuple[int, int]
    monitor_id: str
    scale: tuple[float, float]

    def __post_init__(self):
        if not self.target.is_roblox or not self.window_id or not self.monitor_id:
            raise ValueError("A Roblox target, stable window ID, and monitor ID are required.")
        if (len(self.physical_size) != 2 or any(type(v) is not int or v <= 0 for v in self.physical_size)
                or math.prod(self.physical_size) > MAX_PIXELS):
            raise ValueError("Capture size is invalid or exceeds the pixel limit.")
        if len(self.scale) != 2 or not _finite(*self.scale) or min(self.scale) <= 0:
            raise ValueError("Both display scales must be finite and positive.")
        # Permit only rounding at a physical pixel boundary, never inferred DPI.
        for actual, logical, scale in zip(self.physical_size,
                                           (self.native_content.width, self.native_content.height), self.scale):
            if abs(actual - logical * scale) > 1:
                raise ValueError("Capture dimensions disagree with measured native bounds/scale.")


@dataclass(frozen=True)
class Observation:
    layout: Layout
    captured_at: float
    generation: int
    sequence: int
    pixels: bytes

    def __post_init__(self):
        if (not _finite(self.captured_at) or self.captured_at < 0
                or type(self.generation) is not int or self.generation < 1
                or type(self.sequence) is not int or self.sequence < 1):
            raise ValueError("Invalid monotonic observation identity.")
        if type(self.pixels) is not bytes or len(self.pixels) != math.prod(self.layout.physical_size) * 3:
            raise ValueError("Observation must contain exactly one packed BGR8 frame.")


@dataclass(frozen=True)
class Calibration:
    layout: Layout
    generation: int
    reference_size: tuple[int, int]
    viewport: Rect

    @classmethod
    def create(cls, observation: Observation, reference_size: tuple[int, int],
               viewport: Rect | None = None) -> "Calibration":
        if len(reference_size) != 2 or any(type(v) is not int or v <= 0 for v in reference_size):
            raise ValueError("Reference size must contain two positive integer dimensions.")
        width, height = observation.layout.physical_size
        viewport = viewport or Rect(0, 0, width, height)
        if (min(viewport.x, viewport.y) < 0 or viewport.x + viewport.width > width
                or viewport.y + viewport.height > height):
            raise ValueError("Viewport must be wholly inside the captured content.")
        ratio = (viewport.width / viewport.height) / (reference_size[0] / reference_size[1])
        if abs(ratio - 1) > 0.01:
            raise ValueError("Unsupported aspect ratio; select the actual viewport instead of stretching.")
        return cls(observation.layout, observation.generation, reference_size, viewport)

    def reference_to_pixel(self, x: float, y: float) -> tuple[float, float]:
        width, height = self.reference_size
        if not _finite(x, y) or not 0 <= x < width or not 0 <= y < height:
            raise ValueError("Reference point lies outside the calibrated viewport.")
        return (self.viewport.x + x * self.viewport.width / width,
                self.viewport.y + y * self.viewport.height / height)

    def pixel_to_native(self, x: float, y: float) -> tuple[float, float]:
        if (not _finite(x, y) or not self.viewport.x <= x < self.viewport.x + self.viewport.width
                or not self.viewport.y <= y < self.viewport.y + self.viewport.height):
            raise ValueError("Pixel point lies outside the calibrated viewport.")
        bounds = self.layout.native_content
        # Use the measured capture/native extents; declared scale was checked
        # against them when Layout was constructed. Never use monitor resolution.
        width, height = self.layout.physical_size
        return bounds.x + x * bounds.width / width, bounds.y + y * bounds.height / height


class ObservationTracker:
    """Invalidate old coordinates whenever capture layout changes or is lost."""

    def __init__(self):
        self.generation = 0
        self.sequence = 0
        self.layout: Layout | None = None
        self.latest: Observation | None = None
        self.calibration: Calibration | None = None

    def invalidate(self) -> None:
        self.generation += 1
        self.layout = None
        self.latest = None
        self.calibration = None

    def accept(self, layout: Layout, pixels: bytes, captured_at: float, now: float,
               max_age: float = 0.5) -> Observation:
        if (not _finite(now, captured_at, max_age) or not 0 < max_age <= 2
                or captured_at > now or now - captured_at > max_age
                or (self.latest and captured_at <= self.latest.captured_at)):
            self.invalidate()
            raise ValueError("Stale, out-of-order, or invalid observation; calibration was cleared.")
        if self.layout != layout:
            self.invalidate()
        try:
            observation = Observation(layout, captured_at, self.generation, self.sequence + 1, pixels)
        except ValueError:
            self.invalidate()
            raise
        self.layout = layout
        self.sequence += 1
        self.latest = observation
        return observation

    def calibrate(self, reference_size: tuple[int, int], viewport: Rect | None = None,
                  *, now: float) -> Calibration:
        self.calibration = None
        if (self.latest is None or not _finite(now) or now < self.latest.captured_at
                or now - self.latest.captured_at > 0.5):
            self.invalidate()
            raise ValueError("A fresh valid observation is required before calibration.")
        self.calibration = Calibration.create(self.latest, reference_size, viewport)
        return self.calibration

    def require_current(self, observation: Observation, current_layout: Layout, now: float,
                        max_age: float = 0.5) -> Calibration:
        if (not _finite(now, max_age) or not 0 < max_age <= 2 or self.calibration is None
                or self.layout != current_layout or observation is not self.latest
                or observation.generation != self.generation
                or now < observation.captured_at or now - observation.captured_at > max_age):
            self.invalidate()
            raise ValueError("Observation/calibration is no longer current.")
        return self.calibration
