"""Build an unsigned local app on its target OS; never publish a release."""

from pathlib import Path
import os
import subprocess
import sys


def main() -> None:
    if sys.platform not in {"darwin", "win32"}:
        raise SystemExit("Only Windows and macOS builds are supported.")
    root = Path(__file__).resolve().parents[1]
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
               "--windowed", "--onedir", "--name", "AFKGrinder", "--paths", str(root / "src"),
               "--distpath", str(root / "dist"), "--workpath", str(root / "build"),
               "--specpath", str(root / "build")]
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
