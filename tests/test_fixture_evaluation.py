"""Tests for explicit-consent static fixture evaluation with synthetic images only."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from afk_grinder import __version__
from afk_grinder import fixture_evaluation as evaluation
from afk_grinder.recognition.maa_adapter import PINNED_MAA_VERSION
from afk_grinder.recognition.matcher import TemplateHit
from afk_grinder.recognition.packs import load_pack
from afk_grinder.training_packet import parse_training_packet
from tools.make_fixture_demo import generate


class FirstTemplateMatcher:
    """Synthetic matcher: only the first compiled template is an exact hit."""

    instances: list["FirstTemplateMatcher"] = []

    def __init__(self, specs):
        self.specs = tuple(specs)
        self.warmups = 0
        self.matches = 0
        self.closed = False
        type(self).instances.append(self)

    def warmup(self) -> None:
        self.warmups += 1

    def match(self, width: int, height: int, pixels: bytes, *, timeout: float):
        self.matches += 1
        hits = []
        for index, spec in enumerate(self.specs):
            box = (spec.roi[0], spec.roi[1], spec.width, spec.height) if index == 0 else None
            hits.append(TemplateHit(spec.template_id, 1.0 if index == 0 else 0.0, box))
        return tuple(hits)

    def close(self) -> None:
        self.closed = True


class ExplodingMatcher(FirstTemplateMatcher):
    def match(self, width: int, height: int, pixels: bytes, *, timeout: float):
        raise RuntimeError("SENSITIVE_NATIVE_MARKER /private/frame.png")


class FixtureEvaluationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.pack_directory, self.packet_path, self.fixture_directory = generate(self.root / "demo", "a" * 40)
        self.pack = load_pack(self.pack_directory, app_version=__version__)
        self.packet = parse_training_packet(self.packet_path.read_text(encoding="utf-8"))
        FirstTemplateMatcher.instances = []
        ExplodingMatcher.instances = []

    def report(self, *, split: str = "held_out") -> dict[str, object]:
        return evaluation.evaluate_fixtures(
            self.pack,
            self.packet,
            self.fixture_directory,
            consent=True,
            split=split,
            matcher_factory=FirstTemplateMatcher,
        )

    def test_consent_must_be_exactly_true_before_packet_or_fixture_work(self) -> None:
        for consent in (False, None, 1, "true"):
            with self.subTest(consent=repr(consent)), \
                    patch.object(evaluation, "validate_training_packet") as validate:
                with self.assertRaisesRegex(evaluation.EvaluationError, "^consent_required$"):
                    evaluation.evaluate_fixtures(object(), object(), self.fixture_directory, consent=consent)  # type: ignore[arg-type]
                validate.assert_not_called()

    def test_held_out_selection_reports_static_limits_and_protected_errors(self) -> None:
        report = self.report()

        self.assertEqual(report["split"], "held_out")
        self.assertEqual(report["example_count"], 9)
        self.assertEqual(report["exact_label_matches"], 2)
        self.assertEqual(report["unsafe_protected_predictions"], 6)
        self.assertEqual(report["confusion"], {
            "gameplay": {"gameplay": 2},
            "transaction": {"gameplay": 3},
            "popup": {"gameplay": 1},
            "unknown": {"gameplay": 2, "__unknown__": 1},
        })
        self.assertTrue(all(report[field] is False for field in (
            "temporal_stability_evaluated", "live_readiness", "approved", "native_input",
            "screen_capture", "persistent_images", "model_training",
        )))
        small = report["examples"][-1]
        self.assertEqual(small["example_id"], "small")
        self.assertEqual((small["status"], small["reason"], small["variant_count"], small["anchors"]),
                         ("unknown", "unsupported_layout", 0, []))

    def test_split_selection_and_empty_or_unknown_splits_fail_closed(self) -> None:
        validation = self.report(split="validation")
        self.assertEqual((validation["split"], validation["example_count"], validation["exact_label_matches"]),
                         ("validation", 1, 1))
        for split in ("train", "private"):
            with self.subTest(split=split), self.assertRaisesRegex(evaluation.EvaluationError, "^dataset_invalid$"):
                self.report(split=split)

    def test_matcher_lifecycle_restarts_for_geometry_and_closes_each_instance(self) -> None:
        self.report()

        self.assertEqual(len(FirstTemplateMatcher.instances), 3)
        self.assertEqual([instance.warmups for instance in FirstTemplateMatcher.instances], [1, 1, 1])
        self.assertEqual([instance.matches for instance in FirstTemplateMatcher.instances], [1, 1, 6])
        self.assertTrue(all(instance.closed for instance in FirstTemplateMatcher.instances))

    def test_matcher_or_fixture_failures_abort_without_partial_report_or_details(self) -> None:
        with self.assertRaisesRegex(evaluation.EvaluationError, "^recognition_failed$") as raised:
            evaluation.evaluate_fixtures(
                self.pack, self.packet, self.fixture_directory, consent=True, matcher_factory=ExplodingMatcher,
            )
        self.assertNotIn("SENSITIVE_NATIVE_MARKER", str(raised.exception))
        self.assertNotIn("/private/", str(raised.exception))
        self.assertTrue(all(instance.closed for instance in ExplodingMatcher.instances))

        missing = self.fixture_directory / "examples" / "clear.png"
        missing.unlink()
        with self.assertRaisesRegex(evaluation.EvaluationError, "^fixture_invalid$"):
            self.report()

    def test_malformed_matcher_metadata_fails_closed(self) -> None:
        def factory_for(kind: str):
            def factory(specs):
                instance = FirstTemplateMatcher(specs)
                first = instance.specs[0]
                if kind == "count":
                    instance.match = lambda *args, **kwargs: ()
                elif kind == "duplicate":
                    instance.match = lambda *args, **kwargs: tuple(
                        TemplateHit(first.template_id, 1.0, (first.roi[0], first.roi[1], first.width, first.height))
                        for _ in instance.specs
                    )
                elif kind == "score":
                    instance.match = lambda *args, **kwargs: tuple(
                        TemplateHit(spec.template_id, float("nan"), None) for spec in instance.specs
                    )
                else:
                    instance.match = lambda *args, **kwargs: tuple(
                        TemplateHit(spec.template_id, 1.0, (99999, 0, spec.width, spec.height))
                        for spec in instance.specs
                    )
                return instance
            return factory

        for kind in ("count", "duplicate", "score", "box"):
            with self.subTest(kind=kind), self.assertRaisesRegex(evaluation.EvaluationError, "^recognition_failed$"):
                evaluation.evaluate_fixtures(
                    self.pack, self.packet, self.fixture_directory, consent=True, matcher_factory=factory_for(kind),
                )

    def test_eager_pack_validation_rejects_bad_assets_when_only_fixture_is_unsupported(self) -> None:
        packet_payload = json.loads(self.packet_path.read_text(encoding="utf-8"))
        packet_payload["examples"] = [packet_payload["examples"][-1]]
        small_only = parse_training_packet(json.dumps(packet_payload))
        malformed = replace(self.pack, assets=(replace(self.pack.assets[0], sha256="0" * 64), *self.pack.assets[1:]))
        factory = Mock()

        with self.assertRaisesRegex(evaluation.EvaluationError, "^pack_invalid$"):
            evaluation.evaluate_fixtures(
                malformed, small_only, self.fixture_directory, consent=True, matcher_factory=factory,
            )
        factory.assert_not_called()

    def test_report_validator_rejects_metrics_unknown_fields_flags_duplicates_and_boxes(self) -> None:
        valid = self.report()
        self.assertEqual(evaluation._validate_report({"ok": True, "report": valid}), valid)

        mutations = {
            "metrics": lambda report: report.__setitem__("exact_label_matches", report["exact_label_matches"] + 1),
            "unknown-field": lambda report: report.__setitem__("unexpected", True),
            "claim": lambda report: report.__setitem__("screen_capture", True),
            "duplicate-example": lambda report: report["examples"][1].__setitem__("example_id", report["examples"][0]["example_id"]),
            "duplicate-anchor": lambda report: report["examples"][0]["anchors"].append(deepcopy(report["examples"][0]["anchors"][0])),
            "escaping-box": lambda report: report["examples"][0]["anchors"][0].__setitem__("box", [96, 0, 1, 1]),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                candidate = deepcopy(valid)
                mutate(candidate)
                with self.assertRaisesRegex(evaluation.EvaluationError, "^report_invalid$"):
                    evaluation._validate_report({"ok": True, "report": candidate})

    def test_bounded_json_and_worker_oversize_result_fail_closed(self) -> None:
        too_large = self.root / "too-large.json"
        too_large.write_bytes(b"x" * (evaluation.MAX_REPORT_BYTES + 1))
        with self.assertRaises(ValueError):
            evaluation._read_json(too_large, evaluation.MAX_REPORT_BYTES)

        output = self.root / "worker-report.json"
        with patch.object(evaluation, "load_pack", return_value=self.pack), \
                patch.object(evaluation, "evaluate_fixtures", return_value={"blob": "x" * evaluation.MAX_REPORT_BYTES}):
            evaluation.worker(self.pack_directory, self.packet_path, self.fixture_directory, output, consent=True, split="held_out")
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"ok": False, "error": "report_invalid"})

    def test_child_timeout_command_result_and_cleanup_are_bounded(self) -> None:
        captured: dict[str, object] = {}

        def timeout(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])

        with patch.object(evaluation.subprocess, "run", side_effect=timeout), \
                self.assertRaisesRegex(evaluation.EvaluationError, "^timeout$"):
            evaluation.run_evaluation(self.pack_directory, self.packet_path, self.fixture_directory, consent=True)
        command = captured["command"]
        report_path = Path(command[command.index("--fixture-report") + 1])
        self.assertFalse(report_path.parent.exists())
        self.assertEqual(captured["kwargs"]["stdout"], subprocess.DEVNULL)
        self.assertEqual(captured["kwargs"]["stderr"], subprocess.DEVNULL)
        self.assertNotIn("capture_output", captured["kwargs"])

        valid = self.report()
        captured.clear()

        def completed(command, **kwargs):
            captured["command"] = command
            report = Path(command[command.index("--fixture-report") + 1])
            report.write_text(json.dumps({"ok": True, "report": valid}), encoding="utf-8")
            return SimpleNamespace(returncode=0)

        with patch.object(evaluation.subprocess, "run", side_effect=completed):
            returned = evaluation.run_evaluation(self.pack_directory, self.packet_path, self.fixture_directory, consent=True)
        self.assertEqual(returned["example_count"], 9)
        report_path = Path(captured["command"][captured["command"].index("--fixture-report") + 1])
        self.assertFalse(report_path.parent.exists())

    def test_child_report_split_mismatch_and_nonzero_exit_fail_closed(self) -> None:
        valid = self.report()

        def result_with(report, code):
            def run(command, **kwargs):
                report_path = Path(command[command.index("--fixture-report") + 1])
                report_path.write_text(json.dumps({"ok": True, "report": report}), encoding="utf-8")
                return SimpleNamespace(returncode=code)
            return run

        mismatched = deepcopy(valid)
        mismatched["split"] = "validation"
        with patch.object(evaluation.subprocess, "run", side_effect=result_with(mismatched, 0)), \
                self.assertRaisesRegex(evaluation.EvaluationError, "^report_invalid$"):
            evaluation.run_evaluation(self.pack_directory, self.packet_path, self.fixture_directory, consent=True)
        with patch.object(evaluation.subprocess, "run", side_effect=result_with(valid, 1)), \
                self.assertRaisesRegex(evaluation.EvaluationError, "^worker_failed$"):
            evaluation.run_evaluation(self.pack_directory, self.packet_path, self.fixture_directory, consent=True)

    @staticmethod
    def _refresh_report_metrics(report: dict[str, object]) -> None:
        confusion: dict[str, dict[str, int]] = {}
        exact = unsafe = 0
        for row in report["examples"]:
            expected = row["expected_state"]
            prediction = row["predicted_state"] or f"__{row['status']}__"
            confusion.setdefault(expected, {})[prediction] = confusion.setdefault(expected, {}).get(prediction, 0) + 1
            exact += row["predicted_state"] == expected
            unsafe += row["expected_kind"] != "gameplay" and row["status"] == "candidate"
        report["confusion"] = confusion
        report["exact_label_matches"] = exact
        report["unsafe_protected_predictions"] = unsafe

    def test_parent_rejects_locally_valid_child_report_not_bound_to_selected_metadata(self) -> None:
        def run_with(report: dict[str, object]) -> None:
            self.assertEqual(evaluation._validate_report({"ok": True, "report": report}), report)

            def completed(command, **kwargs):
                report_path = Path(command[command.index("--fixture-report") + 1])
                report_path.write_text(json.dumps({"ok": True, "report": report}), encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with patch.object(evaluation.subprocess, "run", side_effect=completed), \
                    self.assertRaisesRegex(evaluation.EvaluationError, "^report_invalid$"):
                evaluation.run_evaluation(self.pack_directory, self.packet_path, self.fixture_directory, consent=True)

        def changed_pack_identity(report: dict[str, object]) -> None:
            report["pack"]["id"] = "other-pack"

        def changed_dataset_identity(report: dict[str, object]) -> None:
            report["dataset"]["version"] = "9.9.9"

        def relabeled_protected_expected_state(report: dict[str, object]) -> None:
            row = next(item for item in report["examples"] if item["expected_state"] == "transaction")
            row["expected_state"] = "popup"
            row["expected_kind"] = "popup"
            self._refresh_report_metrics(report)

        def changed_predicted_state_kind(report: dict[str, object]) -> None:
            row = report["examples"][0]
            row["predicted_state"] = "transaction"
            row["predicted_kind"] = "gameplay"
            self._refresh_report_metrics(report)

        def changed_row_dimensions(report: dict[str, object]) -> None:
            report["examples"][0]["width"] += 1

        def changed_anchor_order(report: dict[str, object]) -> None:
            report["examples"][0]["anchors"][0]["id"] = "forged-anchor"

        for label, mutate in {
            "pack-identity": changed_pack_identity,
            "dataset-identity": changed_dataset_identity,
            "protected-state": relabeled_protected_expected_state,
            "predicted-state-kind": changed_predicted_state_kind,
            "dimensions": changed_row_dimensions,
            "anchor-order": changed_anchor_order,
        }.items():
            with self.subTest(label=label):
                candidate = deepcopy(self.report())
                mutate(candidate)
                run_with(candidate)

    def test_parent_rejects_locally_valid_predictions_and_hit_metadata_that_disagree_with_anchors(self) -> None:
        def run_with(report: dict[str, object]) -> None:
            self.assertEqual(evaluation._validate_report({"ok": True, "report": report}), report)

            def completed(command, **kwargs):
                report_path = Path(command[command.index("--fixture-report") + 1])
                report_path.write_text(json.dumps({"ok": True, "report": report}), encoding="utf-8")
                return SimpleNamespace(returncode=0)

            with patch.object(evaluation.subprocess, "run", side_effect=completed), \
                    self.assertRaisesRegex(evaluation.EvaluationError, "^report_invalid$"):
                evaluation.run_evaluation(self.pack_directory, self.packet_path, self.fixture_directory, consent=True)

        def wrong_prediction(report: dict[str, object]) -> None:
            row = report["examples"][0]
            row.update({"status": "unknown", "predicted_state": None, "predicted_kind": None, "reason": "no_match"})
            self._refresh_report_metrics(report)

        def falsely_unsupported(report: dict[str, object]) -> None:
            row = report["examples"][0]
            row.update({
                "status": "unknown", "predicted_state": None, "predicted_kind": None,
                "reason": "unsupported_layout", "variant_count": 0, "anchors": [],
            })
            self._refresh_report_metrics(report)

        def missing_box_at_passing_score(report: dict[str, object]) -> None:
            report["examples"][0]["anchors"][0]["box"] = None

        def box_below_threshold(report: dict[str, object]) -> None:
            report["examples"][0]["anchors"][0]["score"] = 0.0

        for label, mutate in {
            "wrong-prediction": wrong_prediction,
            "falsely-unsupported": falsely_unsupported,
            "missing-box-at-passing-score": missing_box_at_passing_score,
            "box-below-threshold": box_below_threshold,
        }.items():
            with self.subTest(label=label):
                candidate = deepcopy(self.report())
                mutate(candidate)
                run_with(candidate)

    def test_cli_rejects_missing_consent_mixed_modes_and_existing_report(self) -> None:
        report = self.root / "report.json"
        base = [
            sys.executable, "-m", "afk_grinder", "--evaluate-pack", str(self.pack_directory),
            "--training-packet", str(self.packet_path), "--fixture-directory", str(self.fixture_directory),
            "--fixture-report", str(report),
        ]
        missing = subprocess.run(base, text=True, capture_output=True, check=False)
        self.assertEqual(missing.returncode, 2)
        self.assertIn("--fixture-consent", missing.stderr)

        mixed = subprocess.run([sys.executable, "-m", "afk_grinder", "--check", "--evaluate-pack", str(self.pack_directory)],
                               text=True, capture_output=True, check=False)
        self.assertEqual(mixed.returncode, 2)
        self.assertIn("not allowed with argument", mixed.stderr)

        report.write_text("existing", encoding="utf-8")
        existing = subprocess.run([*base, "--fixture-consent"], text=True, capture_output=True, check=False)
        self.assertEqual(existing.returncode, 2)
        self.assertIn("must be a new file", existing.stderr)
        self.assertEqual(report.read_text(encoding="utf-8"), "existing")


class FixtureEvaluationNativeCanaryTests(unittest.TestCase):
    def test_pinned_sdk_cli_evaluates_original_synthetic_held_out_fixtures(self) -> None:
        try:
            version = importlib.metadata.version("MaaFw").removeprefix("v")
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("Pinned Maa SDK is unavailable.")
        if version != PINNED_MAA_VERSION:
            self.skipTest("Pinned Maa SDK is unavailable.")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pack_directory, packet_path, fixture_directory = generate(root / "demo", "a" * 40)
            report_path = root / "report.json"
            result = subprocess.run(
                [
                    sys.executable, "-m", "afk_grinder", "--evaluate-pack", str(pack_directory),
                    "--training-packet", str(packet_path), "--fixture-directory", str(fixture_directory),
                    "--fixture-report", str(report_path), "--fixture-consent",
                ],
                text=True,
                capture_output=True,
                timeout=evaluation.EVALUATION_TIMEOUT + 10,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertTrue(payload["ok"])
            report = payload["report"]
            self.assertEqual((report["split"], report["example_count"], report["exact_label_matches"],
                              report["unsafe_protected_predictions"]), ("held_out", 9, 5, 0))
            self.assertTrue(all(report[field] is False for field in (
                "temporal_stability_evaluated", "live_readiness", "approved", "native_input",
                "screen_capture", "persistent_images", "model_training",
            )))
            self.assertTrue(all(path.is_file() for path in (pack_directory / "pack.json", packet_path,
                                                            fixture_directory / "examples" / "clear.png")))


if __name__ == "__main__":
    unittest.main()
