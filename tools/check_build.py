"""Smoke-check a frozen build without sending native input."""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


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


def _run(executable: Path, argument: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            [str(executable), argument],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(f"{argument} timed out after 30 seconds.") from error


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


def smoke(root: Path, *, system: str | None = None) -> None:
    """Run frozen ``--dry-run`` and platform-aware ``--check`` diagnostics."""
    system = system or sys.platform
    executable = frozen_executable(root, system=system)
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
    args = parser.parse_args()
    try:
        smoke(args.root.resolve())
    except RuntimeError as error:
        print(f"Smoke check failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
