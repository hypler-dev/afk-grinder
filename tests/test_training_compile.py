"""Offline crop-export tests using original synthetic images only."""

import importlib.metadata
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from afk_grinder import __version__, training_compile as compilation
from afk_grinder.recognition.pack_compiler import compile_pack
from afk_grinder.recognition.packs import load_pack
from tools.make_training_demo import generate


class TrainingCompileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.packet, self.recipe, self.fixtures = generate(self.root / "demo", "a" * 40)
        self.output = self.root / "proposal"

    def run_compile(self):
        executable = os.environ.get("AFK_GRINDER_TEST_COMPILE_EXECUTABLE")
        if executable:
            result = subprocess.run([
                str(Path(executable).resolve(strict=True)), "--compile-training", str(self.packet),
                "--crop-recipe", str(self.recipe), "--fixture-directory", str(self.fixtures),
                "--compile-output", str(self.output), "--compile-consent",
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=compilation.COMPILE_TIMEOUT + 10, check=False)
            self.assertEqual(result.returncode, 0)
            return json.loads((self.output / "proposal.json").read_text(encoding="utf-8"))
        return compilation.run_compile(self.packet, self.recipe, self.fixtures, self.output, consent=True)

    def test_consent_required_before_io_or_child_creation(self):
        for value in (False, None, 1, "true"):
            with self.subTest(value=repr(value)), patch.object(compilation, "_packet") as read, \
                    patch.object(compilation.subprocess, "run") as launch:
                with self.assertRaisesRegex(compilation.CompilationError, "^consent_required$"):
                    compilation.run_compile(object(), object(), object(), object(), consent=value)
                read.assert_not_called()
                launch.assert_not_called()

    def test_real_disposable_worker_exports_valid_recognition_candidate(self):
        report = self.run_compile()
        saved = json.loads((self.output / "proposal.json").read_text(encoding="utf-8"))
        self.assertEqual(report, saved)
        pack = load_pack(self.output / "candidate", app_version=__version__)
        compiled = compile_pack(pack, pack.reference_size)
        self.assertTrue(compiled.templates)
        self.assertEqual({state.kind for state in pack.states}, {"gameplay", "transaction", "popup", "unknown"})
        self.assertEqual(len(pack.assets), 4)
        manifest = json.loads((self.output / "candidate" / "pack.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["routines"], [])
        self.assertEqual({item["id"] for item in report["selected_examples"]},
                         {f"train-{name}" for name in ("gameplay", "transaction", "popup", "unknown")})
        for key in ("approved", "live_readiness", "native_input", "screen_capture", "held_out_used", "model_training"):
            self.assertIs(report[key], False)
        self.assertIs(report["persistent_images"], True)
        self.assertIs(report["recognition_only"], True)
        self.assertEqual(len([path for path in self.output.rglob("*") if path.is_file()]), 6)
        if os.name == "posix":
            self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
            self.assertTrue(all(path.stat().st_mode & 0o777 == 0o600 for path in self.output.rglob("*") if path.is_file()))

    def test_real_worker_does_not_read_validation_or_held_out_files(self):
        packet = json.loads(self.packet.read_text(encoding="utf-8"))
        for example in packet["examples"]:
            if example["split"] != "train":
                (self.fixtures / example["path"]).unlink()
        report = self.run_compile()
        self.assertIs(report["held_out_used"], False)
        self.assertEqual(len(report["selected_examples"]), 4)

    def test_held_out_selection_rejected_before_fixture_or_child_work(self):
        recipe = json.loads(self.recipe.read_text(encoding="utf-8"))
        recipe["anchors"][0]["example_id"] = "clear"
        self.recipe.write_text(json.dumps(recipe), encoding="utf-8")
        with patch.object(compilation.subprocess, "run") as launch:
            with self.assertRaisesRegex(compilation.CompilationError, "^recipe_invalid$"):
                compilation.run_compile(self.packet, self.recipe, self.root / "missing", self.output, consent=True)
            launch.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_tampered_train_file_fails_without_export(self):
        (self.fixtures / "examples/train-gameplay.png").write_bytes(b"private invalid image")
        with self.assertRaisesRegex(compilation.CompilationError, "^fixture_invalid$"):
            compilation.run_compile(self.packet, self.recipe, self.fixtures, self.output, consent=True)
        self.assertFalse(self.output.exists())

    def test_existing_output_and_symlink_are_never_overwritten(self):
        self.output.mkdir()
        marker = self.output / "keep"
        marker.write_text("untouched", encoding="utf-8")
        with self.assertRaisesRegex(compilation.CompilationError, "^output_invalid$"):
            compilation.run_compile(self.packet, self.recipe, self.fixtures, self.output, consent=True)
        self.assertEqual(marker.read_text(encoding="utf-8"), "untouched")
        # lstat, rather than exists alone, is the final-component boundary.
        with patch.object(Path, "lstat", return_value=SimpleNamespace(st_mode=0o120777)):
            with self.assertRaisesRegex(compilation.CompilationError, "^output_invalid$"):
                compilation.validate_output(self.root / "absent")

    def test_timeout_discards_staging_and_never_publishes(self):
        captured = {}

        def timeout(command, **kwargs):
            captured.update(command=command, kwargs=kwargs)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"], output=b"PRIVATE_MARKER")

        with patch.object(compilation.subprocess, "run", side_effect=timeout):
            with self.assertRaisesRegex(compilation.CompilationError, "^timeout$") as error:
                compilation.run_compile(self.packet, self.recipe, self.fixtures, self.output, consent=True)
        self.assertNotIn("PRIVATE_MARKER", str(error.exception))
        self.assertEqual(captured["kwargs"]["timeout"], 60.0)
        self.assertEqual(captured["kwargs"]["stdout"], subprocess.DEVNULL)
        self.assertEqual(captured["kwargs"]["stderr"], subprocess.DEVNULL)
        snapshot = Path(captured["command"][captured["command"].index("--compile-worker") + 1])
        self.assertFalse(snapshot.parent.exists())
        self.assertFalse(self.output.exists())

    def test_private_staging_failure_has_only_fixed_error_code(self):
        with patch.object(compilation.tempfile, "TemporaryDirectory", side_effect=PermissionError("PRIVATE_PATH")):
            with self.assertRaisesRegex(compilation.CompilationError, "^worker_failed$"):
                compilation.run_compile(self.packet, self.recipe, self.fixtures, self.output, consent=True)
        self.assertFalse(self.output.exists())

    def test_nonzero_or_malformed_worker_result_fails_without_export(self):
        for code in (0, 1):
            def completed(command, **kwargs):
                report = Path(command[command.index("--compile-report") + 1])
                report.write_text('{"ok":true,"report":"PRIVATE_MARKER"}', encoding="utf-8")
                return SimpleNamespace(returncode=code)

            with self.subTest(code=code), patch.object(compilation.subprocess, "run", side_effect=completed):
                expected = "report_invalid" if code == 0 else "worker_failed"
                with self.assertRaisesRegex(compilation.CompilationError, f"^{expected}$"):
                    compilation.run_compile(self.packet, self.recipe, self.fixtures, self.output, consent=True)
                self.assertFalse(self.output.exists())

    def _worker_then_mutate(self, mutate):
        def completed(command, **kwargs):
            def arg(name):
                return Path(command[command.index(name) + 1])
            compilation.worker(arg("--compile-worker"), arg("--crop-recipe"), arg("--fixture-directory"),
                               arg("--compile-output"), arg("--compile-report"), consent=True)
            mutate(arg("--compile-output"), arg("--compile-report"))
            return SimpleNamespace(returncode=0)
        return completed

    def test_parent_rejects_forged_receipt_and_protected_kind_downgrade(self):
        def change_flag(staging, result):
            payload = json.loads(result.read_text(encoding="utf-8"))
            payload["report"]["approved"] = 0
            result.write_text(json.dumps(payload), encoding="utf-8")

        def change_kind(staging, result):
            path = staging / "candidate/pack.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["states"][1]["kind"] = "gameplay"
            path.write_text(json.dumps(manifest), encoding="utf-8")

        for mutate in (change_flag, change_kind):
            with self.subTest(mutate=mutate.__name__), \
                    patch.object(compilation.subprocess, "run", side_effect=self._worker_then_mutate(mutate)):
                with self.assertRaisesRegex(compilation.CompilationError, "^report_invalid$"):
                    compilation.run_compile(self.packet, self.recipe, self.fixtures, self.output, consent=True)
                self.assertFalse(self.output.exists())

    def test_parent_rejects_self_consistent_held_out_asset_substitution(self):
        def substitute(staging, result):
            from afk_grinder.recognition.training_proposal import validate_candidate

            candidate = staging / "candidate"
            manifest_path = candidate / "pack.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            # Simulate a worker substituting held-out pixels while preserving
            # dimensions and rewriting every related hash and receipt field.
            with Image.open(self.fixtures / "examples/clear.png") as image:
                crop = image.convert("RGB").crop((0, 0, 16, 16))
            stream = BytesIO()
            crop.save(stream, format="PNG", compress_level=9, optimize=False)
            data = stream.getvalue()
            digest = hashlib.sha256(data).hexdigest()
            (candidate / manifest["assets"][0]["path"]).write_bytes(data)
            manifest["assets"][0]["sha256"] = digest
            encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            manifest_path.write_bytes(encoded)
            forged = load_pack(candidate, app_version=__version__)
            # This substitution passes structural self-consistency checks.
            validate_candidate(compilation._packet(self.packet), self.recipe.read_text(encoding="utf-8"), encoded, forged.assets)
            payload = json.loads(result.read_text(encoding="utf-8"))
            payload["report"]["manifest_sha256"] = hashlib.sha256(encoded).hexdigest()
            payload["report"]["assets"][0]["sha256"] = digest
            result.write_text(json.dumps(payload), encoding="utf-8")

        with patch.object(compilation.subprocess, "run", side_effect=self._worker_then_mutate(substitute)):
            with self.assertRaisesRegex(compilation.CompilationError, "^report_invalid$"):
                compilation.run_compile(self.packet, self.recipe, self.fixtures, self.output, consent=True)
        self.assertFalse(self.output.exists())

    def test_packet_snapshot_survives_original_metadata_change(self):
        def change_original(staging, report):
            self.packet.write_text("private changed source", encoding="utf-8")
            self.recipe.write_text("private changed recipe", encoding="utf-8")

        with patch.object(compilation.subprocess, "run", side_effect=self._worker_then_mutate(change_original)):
            report = compilation.run_compile(self.packet, self.recipe, self.fixtures, self.output, consent=True)
        self.assertEqual(report["status"], "draft")
        self.assertTrue((self.output / "proposal.json").is_file())


class TrainingCompileCLI(unittest.TestCase):
    def test_missing_or_conflicting_flags_fail_before_dispatch(self):
        from afk_grinder.__main__ import main

        cases = [
            ["--compile-consent"], ["--crop-recipe", "recipe.json"],
            ["--compile-training", "packet.json"],
            ["--dry-run", "--compile-training", "packet.json"],
            ["--compile-training", "packet.json", "--author-model", "model:tag"],
            ["--compile-training", "packet.json", "--fixture-consent"],
            ["--compile-report", "report.json"],
        ]
        for args in cases:
            with self.subTest(args=args), patch.object(sys, "argv", ["afk-grinder", *args]), \
                    patch.object(compilation, "run_compile") as run, patch("sys.stderr"):
                with self.assertRaises(SystemExit) as exit_status:
                    main()
                self.assertEqual(exit_status.exception.code, 2)
                run.assert_not_called()

    def test_fixed_failure_code_is_reported_without_native_details(self):
        from afk_grinder.__main__ import main

        args = ["afk-grinder", "--compile-training", "packet.json", "--crop-recipe", "recipe.json",
                "--fixture-directory", "fixtures", "--compile-output", "new", "--compile-consent"]
        with patch.object(sys, "argv", args), patch.object(compilation, "run_compile", side_effect=compilation.CompilationError("fixture_invalid")), \
                patch("sys.stderr") as stderr:
            with self.assertRaises(SystemExit) as exit_status:
                main()
            self.assertEqual(exit_status.exception.code, 1)
            self.assertIn("fixture_invalid", stderr.write.call_args_list[0].args[0])


class TrainingCompileNativeCanary(unittest.TestCase):
    def test_compiled_candidate_evaluates_separate_synthetic_held_out_images(self):
        from afk_grinder.fixture_evaluation import run_evaluation
        from afk_grinder.recognition.maa_adapter import PINNED_MAA_VERSION

        try:
            version = importlib.metadata.version("MaaFw").removeprefix("v")
        except importlib.metadata.PackageNotFoundError:
            self.skipTest("Pinned Maa SDK is unavailable.")
        if version != PINNED_MAA_VERSION:
            self.skipTest("Pinned Maa SDK is unavailable.")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet, recipe, fixtures = generate(root / "demo", "a" * 40)
            output = root / "proposal"
            compilation.run_compile(packet, recipe, fixtures, output, consent=True)
            report = run_evaluation(output / "candidate", packet, fixtures, consent=True, split="held_out")
            self.assertEqual((report["example_count"], report["exact_label_matches"], report["unsafe_protected_predictions"]), (9, 5, 0))
            self.assertIs(report["approved"], False)
            self.assertIs(report["native_input"], False)
            self.assertIs(report["temporal_stability_evaluated"], False)


if __name__ == "__main__":
    unittest.main()
