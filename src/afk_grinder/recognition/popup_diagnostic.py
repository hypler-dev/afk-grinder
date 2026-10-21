"""Safe, finite popup-failure metadata for the desktop boundary.

This contract carries only allowlisted lifecycle metadata.  It never contains
exception text, paths, pixels, OCR output, or action authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from afk_grinder.capture import CaptureDiagnostic


POPUP_DIAGNOSTIC_STAGES = frozenset({
    "initialization",
    "model_validation",
    "worker_start",
    "warmup",
    "capture_start",
    "capture",
    "content_calibration",
    "capture_freshness",
    "recognition_submit",
    "recognition",
    "recognition_freshness",
    "classification",
    "reporting",
    "recording",
    "response_geometry",
    "response",
    "verification",
    "idle",
    "cleanup",
})
"""Allowlisted popup lifecycle stages exported to UI and IPC consumers."""

POPUP_DIAGNOSTIC_CODES = frozenset({
    "failed",
    "unavailable",
    "worker_failed",
    "worker_timeout",
    "stale",
    "layout_changed",
    "timeout",
    "closed",
    "clock_invalid",
    "interrupted",
    "phase_changed",
})
"""Allowlisted popup failure codes exported to UI and IPC consumers."""

POPUP_CAPTURE_DIAGNOSTIC_STAGES = frozenset({
    "capture_start",
    "capture",
    "capture_freshness",
})
"""Popup stages that may safely include nested capture metadata."""

__all__ = [
    "POPUP_CAPTURE_DIAGNOSTIC_STAGES",
    "POPUP_DIAGNOSTIC_CODES",
    "POPUP_DIAGNOSTIC_STAGES",
    "PopupDiagnostic",
]


def _require_allowlisted_string(value: object, allowed: frozenset[str], field: str) -> str:
    if type(value) is not str:
        raise TypeError(f"Popup diagnostic {field} must be a string.")
    if value not in allowed:
        raise ValueError(f"Unknown popup diagnostic {field}.")
    return value


def _validated_capture(value: CaptureDiagnostic) -> CaptureDiagnostic:
    """Copy an exact validated capture diagnostic without trusting frozen state."""
    if type(value) is not CaptureDiagnostic:
        raise TypeError("Popup diagnostic capture must be a CaptureDiagnostic.")
    code = value.code
    stage = value.stage
    error_type = value.error_type
    if type(code) is not str or type(stage) is not str or type(error_type) is not str:
        raise TypeError("Capture diagnostic fields must be strings.")
    return CaptureDiagnostic(code=code, stage=stage, error_type=error_type)


@dataclass(frozen=True)
class PopupDiagnostic:
    """Strict, sanitized popup failure metadata.

    The optional capture diagnostic is permitted only around capture lifecycle
    stages.  It is copied during construction and reconstructed before every
    IPC export so externally mutated frozen instances cannot bypass validation.
    """

    stage: str
    code: str
    capture: CaptureDiagnostic | None = None

    def __post_init__(self) -> None:
        stage = _require_allowlisted_string(self.stage, POPUP_DIAGNOSTIC_STAGES, "stage")
        _require_allowlisted_string(self.code, POPUP_DIAGNOSTIC_CODES, "code")
        if self.capture is None:
            return
        if stage not in POPUP_CAPTURE_DIAGNOSTIC_STAGES:
            raise ValueError("Capture diagnostic is not allowed for this popup stage.")
        object.__setattr__(self, "capture", _validated_capture(self.capture))

    def as_ipc(self) -> dict[str, str | dict[str, str] | None]:
        """Return a fresh primitive-only IPC value after repeat validation."""
        stage = _require_allowlisted_string(self.stage, POPUP_DIAGNOSTIC_STAGES, "stage")
        code = _require_allowlisted_string(self.code, POPUP_DIAGNOSTIC_CODES, "code")
        if self.capture is None:
            return {"stage": stage, "code": code, "capture": None}
        if stage not in POPUP_CAPTURE_DIAGNOSTIC_STAGES:
            raise ValueError("Capture diagnostic is not allowed for this popup stage.")
        capture = _validated_capture(self.capture)
        return {"stage": stage, "code": code, "capture": capture.as_ipc()}
