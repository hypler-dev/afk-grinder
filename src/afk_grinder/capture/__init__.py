"""Window-only, in-memory capture contracts.

Capture calls are synchronous and may block in native code.  Call them only
from the observation worker, never from Tk's UI thread.  Implementations never
request permission, activate a window, or fall back to desktop capture.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from time import monotonic
from typing import Protocol

from afk_grinder.models import Target

NativeRect = tuple[int, int, int, int]
PhysicalSize = tuple[int, int]
Scale = tuple[float, float]
_MAX_PIXELS = 16_000_000

CAPTURE_DIAGNOSTIC_CODES = frozenset({
    "permission",
    "window_count",
    "window_missing",
    "geometry",
    "black_frame",
    "timeout",
    "conversion",
    "unavailable",
    "unexpected",
})
CAPTURE_DIAGNOSTIC_STAGES = frozenset({
    "initialization",
    "preflight",
    "discovery",
    "window_selection",
    "filter_geometry",
    "display_selection",
    "screenshot",
    "pixel_conversion",
    "frame_validation",
    "worker",
    "ipc_read",
    "worker_exit",
    "worker_deadline",
    "preview_geometry",
    "preview_encoding",
})
CAPTURE_DIAGNOSTIC_ERROR_TYPES = frozenset({
    "capture_error",
    "attribute_error",
    "type_error",
    "value_error",
    "runtime_error",
    "timeout_error",
    "unexpected",
})


@dataclass(frozen=True)
class CaptureDiagnostic:
    """Safe, bounded capture failure metadata for IPC and UI labels."""

    code: str
    stage: str
    error_type: str

    def __post_init__(self) -> None:
        if self.code not in CAPTURE_DIAGNOSTIC_CODES:
            raise ValueError("Unknown capture diagnostic code.")
        if self.stage not in CAPTURE_DIAGNOSTIC_STAGES:
            raise ValueError("Unknown capture diagnostic stage.")
        if self.error_type not in CAPTURE_DIAGNOSTIC_ERROR_TYPES:
            raise ValueError("Unknown capture diagnostic error type.")

    def as_ipc(self) -> dict[str, str]:
        return {"code": self.code, "stage": self.stage, "error_type": self.error_type}


def capture_error_type(error: BaseException) -> str:
    """Map exceptions to an allowlisted diagnostic value without message data."""
    if isinstance(error, CaptureError):
        return "capture_error"
    if isinstance(error, AttributeError):
        return "attribute_error"
    if isinstance(error, TypeError):
        return "type_error"
    if isinstance(error, ValueError):
        return "value_error"
    if isinstance(error, RuntimeError):
        return "runtime_error"
    if isinstance(error, TimeoutError):
        return "timeout_error"
    return "unexpected"


class CaptureError(RuntimeError):
    """A capture precondition or native observation could not be verified."""

    def __init__(self, message: str, *, code: str = "unexpected", stage: str = "initialization",
                 error_type: str = "capture_error") -> None:
        super().__init__(message)
        self.diagnostic = CaptureDiagnostic(code=code, stage=stage, error_type=error_type)


@dataclass(frozen=True)
class WindowBinding:
    """Pinned native window identity and geometry.

    ``native_rect`` uses platform native input units. Windows client bounds are
    already physical pixels under Per-Monitor-V2; its ``scale`` is display DPI
    metadata, not a second pixel conversion. macOS preview bounds use SCK
    points and its ``scale`` is SCK's point-to-pixel value.
    """

    target: Target
    window_id: str
    native_rect: NativeRect
    monitor_id: str
    scale: Scale
    region_kind: str = "client"
    content_verified: bool = True


@dataclass(frozen=True)
class CapturedWindow:
    """One BGR8 client-area frame kept only in memory."""

    target: Target
    window_id: str
    native_rect: NativeRect
    physical_size: PhysicalSize
    monitor_id: str
    scale: Scale
    pixels: bytes
    format: str
    captured_at: float
    region_kind: str = "client"
    content_verified: bool = True

    def __post_init__(self) -> None:
        _validate_geometry(self.native_rect, self.physical_size, self.scale)
        if self.format != "BGR8":
            raise ValueError("CapturedWindow format must be BGR8.")
        if not isinstance(self.pixels, bytes):
            raise ValueError("CapturedWindow pixels must be immutable bytes.")
        expected = self.physical_size[0] * self.physical_size[1] * 3
        if len(self.pixels) != expected:
            raise ValueError(
                f"BGR8 pixels length {len(self.pixels)} does not match {expected} bytes."
            )
        if (not isinstance(self.captured_at, (int, float)) or isinstance(self.captured_at, bool)
                or not isfinite(self.captured_at) or self.captured_at < 0):
            raise ValueError("captured_at must be finite, monotonic, and non-negative.")
        if not isinstance(self.window_id, str) or not self.window_id:
            raise ValueError("capture window_id must be a non-empty stable identifier.")
        if not isinstance(self.monitor_id, str) or not self.monitor_id:
            raise ValueError("capture monitor_id must be a non-empty stable identifier.")
        if self.region_kind not in {"client", "window-unverified"}:
            raise ValueError("capture region_kind must be client or window-unverified.")
        if self.region_kind == "client" and not self.content_verified:
            raise ValueError("a client capture must have verified content bounds.")
        if self.region_kind == "window-unverified" and self.content_verified:
            raise ValueError("an unverified window preview cannot claim verified content bounds.")


class CaptureBackend(Protocol):
    def discover(self, target: Target) -> WindowBinding: ...
    def capture(self, binding: WindowBinding) -> CapturedWindow: ...

    def snapshot(self, target: Target) -> CapturedWindow: ...


def snapshot(backend: CaptureBackend, target: Target) -> CapturedWindow:
    """Discover then capture without ever selecting a replacement window."""
    return backend.capture(backend.discover(target))


def build_frame(
    binding: WindowBinding,
    *,
    physical_size: PhysicalSize,
    pixels: bytes,
    captured_at: float | None = None,
) -> CapturedWindow:
    """Construct a validated in-memory frame for a still-valid binding."""
    return CapturedWindow(
        target=binding.target,
        window_id=binding.window_id,
        native_rect=binding.native_rect,
        physical_size=physical_size,
        monitor_id=binding.monitor_id,
        scale=binding.scale,
        pixels=pixels,
        format="BGR8",
        captured_at=monotonic() if captured_at is None else captured_at,
        region_kind=binding.region_kind,
        content_verified=binding.content_verified,
    )


def _validate_geometry(native_rect: NativeRect, physical_size: PhysicalSize, scale: Scale) -> None:
    x, y, width, height = native_rect
    physical_width, physical_height = physical_size
    scale_x, scale_y = scale
    if not all(type(value) is int for value in (x, y, width, height)):
        raise ValueError("native_rect must use integer native input units.")
    if not all(type(value) is int for value in (physical_width, physical_height)):
        raise ValueError("capture physical size must use integer pixels.")
    if width <= 0 or height <= 0:
        raise ValueError("capture client bounds must be known and non-empty.")
    if physical_width <= 0 or physical_height <= 0:
        raise ValueError("capture physical size must be non-empty.")
    if physical_width * physical_height > _MAX_PIXELS:
        raise ValueError("capture exceeds 16,000,000-pixel in-memory safety limit.")
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool)
               and isfinite(value) and value > 0 for value in (scale_x, scale_y)):
        raise ValueError("capture scale must be finite and positive.")


def bgrx_to_bgr(raw: bytes | bytearray | memoryview, pixel_count: int) -> bytes:
    """Drop BGRX padding with bounded linear allocations, never per-pixel objects."""
    if type(pixel_count) is not int or pixel_count <= 0:
        raise ValueError("pixel_count must be a positive integer.")
    source = memoryview(raw).cast("B")
    if len(source) != pixel_count * 4:
        raise ValueError("BGRX source length does not match pixel_count.")
    output = bytearray(pixel_count * 3)
    destination = memoryview(output)
    destination[0::3] = source[0::4]
    destination[1::3] = source[1::4]
    destination[2::3] = source[2::4]
    return bytes(output)
