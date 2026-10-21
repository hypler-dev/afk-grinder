"""Strict IPC contract checks for popup failure diagnostics."""

from __future__ import annotations

import unittest

from afk_grinder.capture import CaptureDiagnostic
from afk_grinder.recognition.popup_diagnostic import (
    POPUP_CAPTURE_DIAGNOSTIC_STAGES,
    POPUP_DIAGNOSTIC_CODES,
    POPUP_DIAGNOSTIC_STAGES,
    PopupDiagnostic,
)


class StringSubclass(str):
    pass


class CaptureDiagnosticSubclass(CaptureDiagnostic):
    pass


class PopupDiagnosticTests(unittest.TestCase):
    def test_constants_and_legitimate_capture_metadata_are_allowlisted(self):
        self.assertEqual(POPUP_DIAGNOSTIC_STAGES, {
            "initialization", "model_validation", "worker_start", "warmup", "capture_start",
            "capture", "content_calibration", "capture_freshness", "recognition_submit",
            "recognition", "recognition_freshness", "classification", "reporting", "recording",
            "response_geometry", "response", "verification", "idle", "cleanup",
        })
        self.assertEqual(POPUP_DIAGNOSTIC_CODES, {
            "failed", "unavailable", "worker_failed", "worker_timeout", "stale", "layout_changed",
            "timeout", "closed", "clock_invalid", "interrupted", "phase_changed",
        })
        self.assertEqual(POPUP_CAPTURE_DIAGNOSTIC_STAGES,
                         {"capture_start", "capture", "capture_freshness"})

        capture = CaptureDiagnostic(code="timeout", stage="screenshot", error_type="timeout_error")
        diagnostic = PopupDiagnostic(stage="capture", code="worker_timeout", capture=capture)
        self.assertEqual(diagnostic.as_ipc(), {
            "stage": "capture",
            "code": "worker_timeout",
            "capture": {"code": "timeout", "stage": "screenshot", "error_type": "timeout_error"},
        })

    def test_stage_and_code_require_exact_allowlisted_strings(self):
        for field, value in (
            ("stage", True), ("stage", []), ("stage", StringSubclass("capture")),
            ("code", True), ("code", []), ("code", StringSubclass("failed")),
        ):
            with self.subTest(field=field, value=type(value).__name__):
                values = {"stage": "capture", "code": "failed"}
                values[field] = value
                with self.assertRaises(TypeError):
                    PopupDiagnostic(**values)
        for field, value in (("stage", "other"), ("code", "other")):
            with self.subTest(field=field):
                values = {"stage": "capture", "code": "failed"}
                values[field] = value
                with self.assertRaises(ValueError):
                    PopupDiagnostic(**values)

    def test_capture_requires_exact_type_fixed_fields_and_capture_stage(self):
        capture = CaptureDiagnostic(code="timeout", stage="screenshot", error_type="timeout_error")
        with self.assertRaises(TypeError):
            PopupDiagnostic(stage="capture", code="failed", capture=CaptureDiagnosticSubclass(
                code="timeout", stage="screenshot", error_type="timeout_error",
            ))
        with self.assertRaises(ValueError):
            PopupDiagnostic(stage="recognition", code="failed", capture=capture)

        object.__setattr__(capture, "code", StringSubclass("timeout"))
        with self.assertRaises(TypeError):
            PopupDiagnostic(stage="capture", code="failed", capture=capture)

    def test_ipc_revalidates_mutated_nested_data_and_returns_fresh_dicts(self):
        diagnostic = PopupDiagnostic(
            stage="capture_freshness",
            code="stale",
            capture=CaptureDiagnostic(code="stale", stage="capture_freshness", error_type="value_error"),
        )
        first = diagnostic.as_ipc()
        second = diagnostic.as_ipc()
        self.assertIsNot(first, second)
        self.assertIsNot(first["capture"], second["capture"])
        first["capture"]["code"] = "mutated"  # type: ignore[index]
        self.assertEqual(second["capture"]["code"], "stale")  # type: ignore[index]
        self.assertEqual(diagnostic.as_ipc()["capture"]["code"], "stale")  # type: ignore[index]

        object.__setattr__(diagnostic.capture, "stage", "unexpected")
        with self.assertRaises(ValueError):
            diagnostic.as_ipc()

    def test_ipc_revalidates_mutated_outer_fields(self):
        diagnostic = PopupDiagnostic(stage="idle", code="closed")
        object.__setattr__(diagnostic, "code", "unexpected")
        with self.assertRaises(ValueError):
            diagnostic.as_ipc()


if __name__ == "__main__":
    unittest.main()
