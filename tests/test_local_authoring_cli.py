"""CLI boundary tests for local authoring dispatch."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import afk_grinder.fixture_evaluation as fixture_evaluation
import afk_grinder.local_authoring as local_authoring
from afk_grinder.__main__ import main


class LocalAuthoringCLI(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.fixture_directory = self.root / "fixtures"
        self.fixture_directory.mkdir()
        self.calls: list[tuple[object, ...]] = []

    def tearDown(self) -> None:
        self.directory.cleanup()

    def author_args(self, output: Path, *extra: str) -> list[str]:
        return [
            "--author-local", str(self.root / "packet.json"),
            "--fixture-directory", str(self.fixture_directory),
            "--author-model", "local-model:latest",
            "--author-digest", "a" * 64,
            "--author-example", "train-001",
            "--author-output", str(output),
            "--author-consent",
            *extra,
        ]

    def invoke(self, arguments: list[str]) -> tuple[StringIO, StringIO, int | None]:
        stdout, stderr = StringIO(), StringIO()
        with patch.object(sys, "argv", ["afk-grinder", *arguments]), redirect_stdout(stdout), \
                redirect_stderr(stderr):
            try:
                main()
            except SystemExit as error:
                return stdout, stderr, error.code
        return stdout, stderr, None

    def test_invalid_author_arguments_do_not_import_or_dispatch(self) -> None:
        output = self.root / "report.json"
        cases = (
            ["--author-model", "local-model:latest"],
            ["--author-local", str(self.root / "packet.json")],
            [*self.author_args(output), "--training-packet", str(self.root / "training.json")],
            [*self.author_args(output), "--author-example", ""],
        )
        with patch.object(local_authoring, "validate_output") as validate, \
                patch.object(local_authoring, "run_authoring") as run, \
                patch.object(local_authoring, "worker") as worker:
            for arguments in cases:
                with self.subTest(arguments=arguments):
                    _stdout, _stderr, code = self.invoke(arguments)
                    self.assertEqual(code, 2)
        validate.assert_not_called()
        run.assert_not_called()
        worker.assert_not_called()

    def test_authoring_passes_selected_ids_default_port_and_consent(self) -> None:
        output = self.root / "report.json"
        arguments = [*self.author_args(output), "--author-example", "train-002"]
        def validate(path: Path) -> None:
            self.calls.append(("validate", path))

        def run(*args: object, **kwargs: object) -> dict[str, object]:
            self.calls.append(("run", *args, kwargs))
            return {"draft": "safe"}

        def write(path: Path, payload: dict[str, object]) -> None:
            self.calls.append(("write", path, payload))
            path.write_text(json.dumps(payload), encoding="utf-8")

        with patch.object(local_authoring, "validate_output", side_effect=validate), \
                patch.object(local_authoring, "run_authoring", side_effect=run), \
                patch.object(local_authoring, "write_output", side_effect=write):
            stdout, stderr, code = self.invoke(arguments)
        self.assertIsNone(code)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("Local authoring completed", stdout.getvalue())
        self.assertEqual(self.calls[0], ("validate", output))
        self.assertEqual(self.calls[1][0], "run")
        self.assertEqual(self.calls[1][5:], (("train-001", "train-002"), {"consent": True, "port": 11434}))
        self.assertEqual(self.calls[2][0], "write")
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"ok": True, "report": {"draft": "safe"}})

    def test_authoring_writes_safe_error_payload_without_exception_text(self) -> None:
        output = self.root / "report.json"
        def write(path: Path, payload: dict[str, object]) -> None:
            path.write_text(json.dumps(payload), encoding="utf-8")

        with patch.object(local_authoring, "run_authoring",
                          side_effect=local_authoring.AuthoringError("model_unavailable")), \
                patch.object(local_authoring, "write_output", side_effect=write):
            stdout, stderr, code = self.invoke(self.author_args(output))
        self.assertEqual(code, 1)
        self.assertEqual(stderr.getvalue(), "")
        self.assertIn("model_unavailable", stdout.getvalue())
        self.assertNotIn("private detail", stdout.getvalue())
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), {"ok": False, "error": "model_unavailable"})

    def test_hidden_worker_dispatches_with_explicit_port(self) -> None:
        output = self.root / "worker-report.json"
        arguments = self.author_args(output, "--author-port", "2244")
        arguments[0] = "--author-worker"
        def validate(path: Path) -> None:
            self.calls.append(("validate", path))

        def worker(*args: object, **kwargs: object) -> None:
            self.calls.append(("worker", *args, kwargs))

        with patch.object(local_authoring, "validate_output", side_effect=validate), \
                patch.object(local_authoring, "worker", side_effect=worker):
            stdout, stderr, code = self.invoke(arguments)
        self.assertIsNone(code)
        self.assertEqual((stdout.getvalue(), stderr.getvalue()), ("", ""))
        self.assertEqual(self.calls[0], ("validate", output))
        self.assertEqual(self.calls[1][0], "worker")
        self.assertEqual(self.calls[1][5:], (("train-001",), output, {"consent": True, "port": 2244}))

    def test_fixture_evaluation_arguments_remain_available(self) -> None:
        calls: list[tuple[object, ...]] = []

        def run_evaluation(pack: Path, packet: Path, fixtures: Path, *, consent: bool = False, split: str = "held_out") -> dict[str, object]:
            calls.append((pack, packet, fixtures, consent, split))
            return {"split": split}
        report = self.root / "fixture-report.json"
        arguments = [
            "--evaluate-pack", str(self.root / "pack"),
            "--training-packet", str(self.root / "packet.json"),
            "--fixture-directory", str(self.fixture_directory),
            "--fixture-report", str(report),
            "--fixture-consent",
        ]
        with patch.object(fixture_evaluation, "run_evaluation", side_effect=run_evaluation):
            stdout, stderr, code = self.invoke(arguments)
        self.assertIsNone(code)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(calls[0][3:], (True, "held_out"))
        self.assertEqual(json.loads(report.read_text(encoding="utf-8")), {"ok": True, "report": {"split": "held_out"}})
        self.assertIn("fixture evaluation completed", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
