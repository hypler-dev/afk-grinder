"""Build an unsigned local app on its target OS; never publish a release."""

import argparse
import json
from pathlib import Path
import os
import subprocess
import sys
import tomllib

from collect_legal import collect


def build_identity(root: Path) -> tuple[str, str]:
    """Read package version and record exact source identity for Settings."""
    with (root / "pyproject.toml").open("rb") as project_file:
        project = tomllib.load(project_file)
    version = project.get("project", {}).get("version")
    if not isinstance(version, str) or not version:
        raise RuntimeError("pyproject.toml must define a non-empty project version.")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, check=True, text=True,
        capture_output=True,
    ).stdout.strip()
    if len(commit) != 40 or any(character not in "0123456789abcdef" for character in commit):
        raise RuntimeError("git rev-parse HEAD did not return a full lowercase commit ID.")
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=root, check=True, text=True,
        capture_output=True,
    ).stdout
    return version, f"{commit}-dirty" if dirty else commit


def write_build_info(root: Path) -> Path:
    """Create only the bundled build identity; do not alter package source."""
    version, commit = build_identity(root)
    destination = root / "build" / "generated" / "afk_grinder" / "build-info.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps({"version": version, "commit": commit}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return destination


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-recognition", action="store_true",
                        help="Build a local SDK diagnostic bundle; not approved for redistribution yet")
    parser.add_argument("--with-popup-models", action="store_true",
                        help="Include pinned developer-fetched OCR assets in a private recognition build")
    args = parser.parse_args()
    if sys.platform not in {"darwin", "win32"}:
        raise SystemExit("Only Windows and macOS builds are supported.")
    root = Path(__file__).resolve().parents[1]
    if args.with_popup_models and not args.with_recognition:
        parser.error("--with-popup-models requires --with-recognition and is private-build only")
    runtime_legal = root / "build" / "runtime-legal"
    build_info = write_build_info(root)
    collect(runtime_legal)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--windowed", "--onedir", "--name", "AFKGrinder", "--paths", str(root / "src"),
               "--distpath", str(root / "dist"), "--workpath", str(root / "build"),
               "--specpath", str(root / "build")]
    command += ["--add-data", f"{root / 'LICENSE'}{os.pathsep}legal",
                "--add-data", f"{root / 'THIRD_PARTY_NOTICES.md'}{os.pathsep}legal",
                "--add-data", f"{root / 'docs' / 'DEPENDENCIES.md'}{os.pathsep}legal/docs",
                "--add-data", f"{root / 'licenses'}{os.pathsep}legal/licenses",
                "--add-data", f"{runtime_legal}{os.pathsep}legal/build-runtime",
                "--add-data", f"{root / 'src' / 'afk_grinder' / 'web'}{os.pathsep}afk_grinder/web",
                "--add-data", f"{build_info}{os.pathsep}afk_grinder",
                "--copy-metadata", "pywebview"]
    if args.with_recognition:
        # Private build/startup verification only until the source/notice gate is closed.
        # Never collect MaaAgentBinary: those are separate Android agents.
        command += ["--copy-metadata", "MaaFw", "--collect-binaries", "maa",
                    "--exclude-module", "MaaAgentBinary"]
        for module in ("maa.library", "maa.tasker", "maa.resource", "maa.controller", "maa.define"):
            command += ["--hidden-import", module]
        for module in ("maa.pipeline", "numpy"):
            command += ["--hidden-import", module]
        if args.with_popup_models:
            from afk_grinder.recognition.ocr_models import model_directory, validate_models
            models = validate_models(model_directory())
            command += ["--add-data", f"{models}{os.pathsep}afk_grinder/ocr_models"]
    else:
        command += ["--exclude-module", "maa", "--exclude-module", "MaaAgentBinary",
                    "--exclude-module", "numpy", "--exclude-module", "strenum"]
    if sys.platform == "darwin":
        command += ["--osx-bundle-identifier", "com.hypler.afkgrinder"]
        # pywebview selects Cocoa lazily; bundle its WebKit platform path explicitly.
        for module in ("webview.platforms.cocoa", "WebKit", "AppKit", "Quartz",
                       "ApplicationServices", "ScreenCaptureKit", "objc"):
            command += ["--hidden-import", module]
    else:
        # pywebview selects WinForms and Edge Chromium lazily at native startup.
        for module in ("webview.platforms.winforms", "webview.platforms.edgechromium"):
            command += ["--hidden-import", module]
    command.append(str(root / "tools" / "launch.py"))
    environment = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(root / "build" / "pyinstaller-cache"))
    subprocess.run(command, cwd=root, env=environment, check=True)
    print("Unsigned local app built in dist/. Installation, permissions, and game input require native testing.")


if __name__ == "__main__":
    main()
