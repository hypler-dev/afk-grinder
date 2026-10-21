"""Frozen fixture-evaluation smoke contract without launching a native app."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from afk_grinder import __version__
from afk_grinder.fixture_evaluation import EVALUATION_TIMEOUT, _validate_report
from tools import check_build


def successful_report() -> dict[str, object]:
    """Metadata-only result from the documented original synthetic demo."""
    rows = [
        ("clear", "gameplay", "gameplay", "gameplay", "candidate", "unstabilized", (96, 64), {"gameplay": [11, 10, 16, 16]}),
        ("large", "gameplay", "gameplay", "gameplay", "candidate", "unstabilized", (144, 96), {"gameplay": [16, 16, 24, 24]}),
        ("purchase", "transaction", "transaction", "transaction", "blocked", "transaction", (96, 64), {"transaction": [11, 12, 16, 16]}),
        ("notice", "popup", "popup", "popup", "blocked", "popup", (96, 64), {"popup": [11, 13, 16, 16]}),
        ("overlay", "transaction", None, None, "blocked", "excluded", (96, 64), {"gameplay": [11, 14, 16, 16], "transaction": [43, 14, 16, 16]}),
        ("conflict", "transaction", None, None, "unknown", "ambiguous", (96, 64), {"transaction": [11, 15, 16, 16], "popup": [43, 15, 16, 16]}),
        ("unclassified", "unknown", None, None, "unknown", "no_match", (96, 64), {}),
        ("known-unknown", "unknown", "unknown", "unknown", "unknown", "unknown_screen", (96, 64), {"unknown": [11, 10, 16, 16]}),
        ("small", "unknown", None, None, "unknown", "unsupported_layout", (48, 32), {}),
    ]
    examples = []
    for example_id, expected_state, predicted_state, predicted_kind, status, reason, size, boxes in rows:
        unsupported = example_id == "small"
        examples.append({
            "example_id": example_id,
            "expected_state": expected_state,
            "expected_kind": expected_state,
            "predicted_state": predicted_state,
            "predicted_kind": predicted_kind,
            "status": status,
            "reason": reason,
            "width": size[0],
            "height": size[1],
            "latency_ms": 0.0,
            "variant_count": 0 if unsupported else 20,
            "anchors": [] if unsupported else [
                {"id": anchor, "score": 1.0 if anchor in boxes else 0.0, "box": boxes.get(anchor)}
                for anchor in ("gameplay", "transaction", "popup", "unknown")
            ],
        })
    return {
        "ok": True,
        "report": {
            "format": "afk-grinder-fixture-evaluation",
            "schema_version": 1,
            "app_version": __version__,
            "pack": {"id": "example.static-safety", "version": "0.1.0"},
            "dataset": {"id": "synthetic-safety", "version": "0.1.0", "locale": "en"},
            "split": "held_out",
            "example_count": 9,
            "exact_label_matches": 5,
            "unsafe_protected_predictions": 0,
            "confusion": {
                "gameplay": {"gameplay": 2},
                "transaction": {"transaction": 1, "__blocked__": 1, "__unknown__": 1},
                "popup": {"popup": 1},
                "unknown": {"__unknown__": 2, "unknown": 1},
            },
            "temporal_stability_evaluated": False,
            "live_readiness": False,
            "approved": False,
            "native_input": False,
            "screen_capture": False,
            "persistent_images": False,
            "model_training": False,
            "examples": examples,
        },
    }


class FixtureBuildSmokeTests(unittest.TestCase):
    def _runner(self, *, recognition: bool, malformed: bool = False, mutate=None):
        calls: list[tuple[str, ...]] = []

        def run(executable: Path, *arguments: str, timeout: float = 30.0):
            calls.append(arguments)
            if arguments[0] == "--evaluate-pack":
                self.assertEqual(timeout, check_build.FIXTURE_EVALUATION_HARNESS_TIMEOUT)
                report = Path(arguments[arguments.index("--fixture-report") + 1])
                self.assertFalse(report.exists())
                pack = Path(arguments[1])
                self.assertTrue((pack / "pack.json").is_file())
                self.assertEqual(json.loads((pack / "pack.json").read_text())["provenance"]["revision"], "0" * 40)
                self.assertTrue(Path(arguments[arguments.index("--training-packet") + 1]).is_file())
                self.assertTrue(Path(arguments[arguments.index("--fixture-directory") + 1]).is_dir())
                if malformed:
                    report.write_text('{"ok":true,"report":{}}', encoding="utf-8")
                elif recognition:
                    payload = successful_report()
                    if mutate is not None:
                        mutate(payload)
                    report.write_text(json.dumps(payload), encoding="utf-8")
                else:
                    report.write_text('{"ok":false,"error":"recognition_failed"}', encoding="utf-8")
                return subprocess.CompletedProcess([], 0 if recognition else 1, "fixture result\n", "")
            return subprocess.CompletedProcess([], 0, "ok\n", "")

        return run, calls

    def test_recognition_build_runs_validated_synthetic_fixture_smoke_and_existing_checks(self):
        runner, calls = self._runner(recognition=True)
        with tempfile.TemporaryDirectory() as directory, patch("tools.check_build.frozen_executable", return_value=Path("frozen")), patch("tools.check_build._run", side_effect=runner):
            check_build.smoke(Path(directory), system="win32", recognition=True)

        self.assertEqual(calls[0], ("--sdk-check",))
        self.assertEqual(calls[1][0], "--evaluate-pack")
        self.assertEqual([call[0] for call in calls[2:]], ["--dry-run", "--ui-smoke", "--check"])

    def test_sdk_free_build_requires_fixed_recognition_failure_and_keeps_existing_checks(self):
        runner, calls = self._runner(recognition=False)
        with tempfile.TemporaryDirectory() as directory, patch("tools.check_build.frozen_executable", return_value=Path("frozen")), patch("tools.check_build._run", side_effect=runner):
            check_build.smoke(Path(directory), system="win32")

        self.assertEqual([call[0] for call in calls], ["--evaluate-pack", "--dry-run", "--ui-smoke", "--check"])

    def test_recognition_build_rejects_malformed_external_fixture_report(self):
        runner, _ = self._runner(recognition=True, malformed=True)
        with tempfile.TemporaryDirectory() as directory, patch("tools.check_build.frozen_executable", return_value=Path("frozen")), patch("tools.check_build._run", side_effect=runner), self.assertRaisesRegex(RuntimeError, "invalid metadata report"):
            check_build.smoke(Path(directory), system="win32", recognition=True)

    def test_recognition_build_rejects_schema_valid_report_with_wrong_selected_inputs(self):
        def wrong_pack(payload: dict[str, object]) -> None:
            payload["report"]["pack"]["id"] = "other.synthetic-pack"  # type: ignore[index]

        def wrong_expected_label(payload: dict[str, object]) -> None:
            row = payload["report"]["examples"][2]  # type: ignore[index]
            row["expected_state"] = "popup"
            row["expected_kind"] = "popup"
            report = payload["report"]  # type: ignore[assignment]
            report["confusion"] = {
                "gameplay": {"gameplay": 2},
                "popup": {"transaction": 1, "popup": 1},
                "transaction": {"__blocked__": 1, "__unknown__": 1},
                "unknown": {"__unknown__": 2, "unknown": 1},
            }
            report["exact_label_matches"] = 4

        for mutate in (wrong_pack, wrong_expected_label):
            with self.subTest(mutate=mutate.__name__):
                payload = successful_report()
                mutate(payload)
                self.assertEqual(_validate_report(payload), payload["report"])
                runner, _ = self._runner(recognition=True, mutate=mutate)
                with tempfile.TemporaryDirectory() as directory, patch("tools.check_build.frozen_executable", return_value=Path("frozen")), patch("tools.check_build._run", side_effect=runner), self.assertRaisesRegex(RuntimeError, "invalid metadata report"):
                    check_build.smoke(Path(directory), system="win32", recognition=True)

    def test_recognition_build_rejects_outcome_swap_with_same_aggregate_metrics(self):
        def swap_outcomes(payload: dict[str, object]) -> None:
            rows = payload["report"]["examples"]  # type: ignore[index]
            overlay, conflict = rows[4], rows[5]
            overlay["status"], conflict["status"] = conflict["status"], overlay["status"]
            overlay["reason"], conflict["reason"] = conflict["reason"], overlay["reason"]

        payload = successful_report()
        swap_outcomes(payload)
        self.assertEqual(_validate_report(payload), payload["report"])
        runner, _ = self._runner(recognition=True, mutate=swap_outcomes)
        with tempfile.TemporaryDirectory() as directory, patch("tools.check_build.frozen_executable", return_value=Path("frozen")), patch("tools.check_build._run", side_effect=runner), self.assertRaisesRegex(RuntimeError, "invalid metadata report|safety expectations"):
            check_build.smoke(Path(directory), system="win32", recognition=True)

    def test_fixture_child_timeout_uses_required_bound(self):
        self.assertEqual(EVALUATION_TIMEOUT, 120.0)
        with patch("tools.check_build.subprocess.run", side_effect=subprocess.TimeoutExpired(["frozen"], check_build.FIXTURE_EVALUATION_HARNESS_TIMEOUT)), self.assertRaisesRegex(RuntimeError, "timed out after 130 seconds"):
            check_build._run(Path("frozen"), "--evaluate-pack", "pack", timeout=check_build.FIXTURE_EVALUATION_HARNESS_TIMEOUT)


if __name__ == "__main__":
    unittest.main()
