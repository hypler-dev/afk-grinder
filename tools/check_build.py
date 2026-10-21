"""Smoke-check a frozen build without sending native input."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile


FIXTURE_EVALUATION_HARNESS_TIMEOUT = 130.0
_SYNTHETIC_SOURCE_REVISION = "0" * 40


KNOWN_MAC_PERMISSION_MESSAGES = (
    "Accessibility permission is required for native input control.",
    "Input Monitoring permission is required to read Escape emergency stop.",
    "Accessibility permission is required to post native input events.",
)


def frozen_executable(root: Path, *, system: str | None = None) -> Path:
    """Locate the expected executable for the current platform's build output."""
    system = system or sys.platform
    if system == "win32":
        executable = root / "dist" / "AFKGrinder" / "AFKGrinder.exe"
    elif system == "darwin":
        executable = root / "dist" / "AFKGrinder.app" / "Contents" / "MacOS" / "AFKGrinder"
    else:
        raise RuntimeError("Frozen smoke checks support only Windows and macOS.")
    if not executable.is_file() or executable.is_symlink():
        raise RuntimeError(f"Expected frozen executable is missing: {executable}")
    return executable


def _run(
    executable: Path, *arguments: str, timeout: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    """Run one frozen diagnostic with a bounded lifetime."""
    command = [str(executable), *arguments]
    description = " ".join(arguments)
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{description} timed out after {timeout:g} seconds.") from error


def _print_diagnostics(argument: str, result: subprocess.CompletedProcess[str]) -> None:
    print(f"{argument} return code: {result.returncode}")
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")


def _acceptable_macos_check(result: subprocess.CompletedProcess[str]) -> bool:
    if result.returncode == 0:
        return True
    if result.returncode != 1:
        return False
    output = f"{result.stdout}\n{result.stderr}"
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    foreground_lines = {"Foreground Roblox player: yes", "Foreground Roblox player: no"}
    return bool(lines) and any(
        line in KNOWN_MAC_PERMISSION_MESSAGES for line in lines
    ) and all(line in KNOWN_MAC_PERMISSION_MESSAGES or line in foreground_lines for line in lines)


def _fixture_evaluation_smoke(executable: Path, *, recognition: bool) -> None:
    """Exercise frozen fixture evaluation with original synthetic pixels only."""
    from afk_grinder.fixture_evaluation import (
        MAX_REPORT_BYTES,
        EvaluationError,
        _bind_report,
        _load_metadata,
        _read_json,
        _validate_report,
    )
    if __package__:
        from .make_fixture_demo import generate
    else:
        from make_fixture_demo import generate

    with tempfile.TemporaryDirectory(prefix="afk-grinder-fixture-build-") as temporary:
        destination = Path(temporary) / "synthetic-demo"
        pack, training_packet, fixtures = generate(destination, _SYNTHETIC_SOURCE_REVISION)
        report_path = Path(temporary) / "fixture-evaluation.json"
        evaluation = _run(
            executable,
            "--evaluate-pack", str(pack),
            "--training-packet", str(training_packet),
            "--fixture-directory", str(fixtures),
            "--fixture-consent",
            "--fixture-report", str(report_path),
            timeout=FIXTURE_EVALUATION_HARNESS_TIMEOUT,
        )
        _print_diagnostics("--evaluate-pack", evaluation)
        try:
            payload = _read_json(report_path, MAX_REPORT_BYTES)
        except Exception as error:
            raise RuntimeError("Frozen --evaluate-pack did not write a valid metadata report.") from error

        if not recognition:
            if evaluation.returncode != 1 or payload != {"ok": False, "error": "recognition_failed"}:
                raise RuntimeError("SDK-free frozen --evaluate-pack did not fail as recognition_failed.")
            return

        if evaluation.returncode != 0:
            raise RuntimeError("Frozen --evaluate-pack failed with the recognition SDK present.")
        try:
            report = _validate_report(payload)
            loaded_pack, packet = _load_metadata(pack, training_packet)
            _bind_report(report, loaded_pack, packet, "held_out")
        except EvaluationError as error:
            raise RuntimeError("Frozen --evaluate-pack wrote an invalid metadata report.") from error
        expected_outcomes = (
            ("clear", "candidate", "gameplay", "unstabilized"),
            ("large", "candidate", "gameplay", "unstabilized"),
            ("purchase", "blocked", "transaction", "transaction"),
            ("notice", "blocked", "popup", "popup"),
            ("overlay", "blocked", None, "excluded"),
            ("conflict", "unknown", None, "ambiguous"),
            ("unclassified", "unknown", None, "no_match"),
            ("known-unknown", "unknown", "unknown", "unknown_screen"),
            ("small", "unknown", None, "unsupported_layout"),
        )
        outcomes = tuple(
            (row["example_id"], row["status"], row["predicted_state"], row["reason"])
            for row in report["examples"]
        )
        false_flags = (
            "temporal_stability_evaluated", "live_readiness", "approved", "native_input",
            "screen_capture", "persistent_images", "model_training",
        )
        if (outcomes != expected_outcomes or report["split"] != "held_out" or report["example_count"] != 9
                or report["exact_label_matches"] != 5 or report["unsafe_protected_predictions"] != 0
                or any(report[flag] is not False for flag in false_flags)):
            raise RuntimeError("Frozen --evaluate-pack report did not preserve synthetic fixture safety expectations.")


def smoke(root: Path, *, system: str | None = None, recognition: bool = False) -> None:
    """Run frozen ``--dry-run`` and platform-aware ``--check`` diagnostics."""
    system = system or sys.platform
    executable = frozen_executable(root, system=system)
    if recognition:
        sdk = _run(executable, "--sdk-check")
        _print_diagnostics("--sdk-check", sdk)
        if sdk.returncode != 0:
            raise RuntimeError("Frozen --sdk-check failed.")
    _fixture_evaluation_smoke(executable, recognition=recognition)
    dry_run = _run(executable, "--dry-run")
    _print_diagnostics("--dry-run", dry_run)
    if dry_run.returncode != 0:
        raise RuntimeError("Frozen --dry-run failed.")

    ui_smoke = _run(executable, "--ui-smoke")
    _print_diagnostics("--ui-smoke", ui_smoke)
    if ui_smoke.returncode != 0:
        raise RuntimeError("Frozen --ui-smoke failed.")

    check = _run(executable, "--check")
    _print_diagnostics("--check", check)
    if system == "win32" and check.returncode == 0:
        return
    if system == "darwin" and _acceptable_macos_check(check):
        return
    raise RuntimeError("Frozen --check failed its platform-specific readiness expectation.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-check the local frozen AFK Grinder build.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--recognition", action="store_true", help="Require the local SDK diagnostic")
    args = parser.parse_args()
    try:
        smoke(args.root.resolve(), recognition=args.recognition)
    except RuntimeError as error:
        print(f"Smoke check failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
