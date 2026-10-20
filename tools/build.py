"""Build an unsigned local app on its target OS; never publish a release."""

import argparse
from pathlib import Path
import os
import subprocess
import sys

from collect_legal import collect


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-recognition", action="store_true",
                        help="Build a local SDK diagnostic bundle; not approved for redistribution yet")
    args = parser.parse_args()
    if sys.platform not in {"darwin", "win32"}:
        raise SystemExit("Only Windows and macOS builds are supported.")
    root = Path(__file__).resolve().parents[1]
    runtime_legal = root / "build" / "runtime-legal"
    collect(runtime_legal)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--windowed", "--onedir", "--name", "AFKGrinder", "--paths", str(root / "src"),
               "--distpath", str(root / "dist"), "--workpath", str(root / "build"),
               "--specpath", str(root / "build")]
    command += ["--add-data", f"{root / 'LICENSE'}{os.pathsep}legal",
                "--add-data", f"{root / 'THIRD_PARTY_NOTICES.md'}{os.pathsep}legal",
                "--add-data", f"{root / 'docs' / 'DEPENDENCIES.md'}{os.pathsep}legal/docs",
                "--add-data", f"{root / 'licenses'}{os.pathsep}legal/licenses",
                "--add-data", f"{runtime_legal}{os.pathsep}legal/build-runtime"]
    if args.with_recognition:
        # Private build/startup verification only until the source/notice gate is closed.
        # Never collect MaaAgentBinary: those are separate Android agents.
        command += ["--copy-metadata", "MaaFw", "--collect-binaries", "maa",
                    "--exclude-module", "MaaAgentBinary"]
        for module in ("maa.library", "maa.tasker", "maa.resource", "maa.controller", "maa.define"):
            command += ["--hidden-import", module]
    else:
        command += ["--exclude-module", "maa", "--exclude-module", "MaaAgentBinary",
                    "--exclude-module", "numpy", "--exclude-module", "strenum"]
    if sys.platform == "darwin":
        command += ["--osx-bundle-identifier", "com.hypler.afkgrinder"]
        # Native modules load lazily via importlib so dry run stays portable.
        # Explicit collection is needed for the frozen app's permission checks.
        for module in ("AppKit", "Quartz", "ApplicationServices", "objc"):
            command += ["--hidden-import", module]
    command.append(str(root / "tools" / "launch.py"))
    environment = dict(os.environ, PYINSTALLER_CONFIG_DIR=str(root / "build" / "pyinstaller-cache"))
    subprocess.run(command, cwd=root, env=environment, check=True)
    print("Unsigned local app built in dist/. Installation, permissions, and game input require native testing.")


if __name__ == "__main__":
    main()
