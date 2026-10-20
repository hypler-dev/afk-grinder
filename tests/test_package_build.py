"""Packaging checks use disposable fake build output; no native app is run."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.package_build import package_archive
from tools.check_build import _acceptable_macos_check


COMMIT = "a" * 40
STAMP = datetime(2026, 10, 19, 12, 0, tzinfo=timezone.utc)


class PackageBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "pyproject.toml").write_text("[project]\nversion = '0.1.0'\n")

    def test_windows_zip_contains_full_runtime_and_metadata(self) -> None:
        bundle = self.root / "dist" / "AFKGrinder"
        (bundle / "_internal").mkdir(parents=True)
        (bundle / "AFKGrinder.exe").write_bytes(b"windows executable")
        (bundle / "_internal" / "runtime.dat").write_bytes(b"adjacent runtime")

        archive = package_archive(
            self.root, "windows-x64", COMMIT, self.root / "artifact-output",
            system="win32", machine="AMD64", timestamp=STAMP,
        )

        self.assertEqual(archive.name, "AFKGrinder-windows-x64.zip")
        with zipfile.ZipFile(archive) as packaged:
            self.assertIn("AFKGrinder/AFKGrinder.exe", packaged.namelist())
            self.assertIn("AFKGrinder/_internal/runtime.dat", packaged.namelist())
            self.assertIn("BUILD_INFO.json", packaged.namelist())
            metadata = json.loads(packaged.read("BUILD_INFO.json"))
        sums = (self.root / "artifact-output" / "SHA256SUMS.txt").read_text()
        external_metadata = json.loads(
            (self.root / "artifact-output" / "BUILD_INFO.json").read_text()
        )
        self.assertIn(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}", sums)
        self.assertIn(
            f"{hashlib.sha256((self.root / 'artifact-output' / 'BUILD_INFO.json').read_bytes()).hexdigest()}  BUILD_INFO.json",
            sums,
        )
        self.assertEqual(metadata["commit"], COMMIT)
        self.assertEqual(external_metadata, metadata)
        self.assertEqual(metadata["label"], "windows-x64")
        self.assertEqual(metadata["archive_filename"], archive.name)
        self.assertEqual(metadata["timestamp_utc"], "2026-10-19T12:00:00Z")
        self.assertIn("Unsigned prototype", metadata["warning"])
        self.assertEqual(metadata["validation"], "No game validation performed.")

    @unittest.skipIf(sys.platform == "win32", "Windows CI may not permit symlink fixtures")
    def test_macos_tar_preserves_executable_mode_and_symlink(self) -> None:
        executable = self.root / "dist" / "AFKGrinder.app" / "Contents" / "MacOS" / "AFKGrinder"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"mac executable")
        executable.chmod(0o755)
        resources = executable.parents[1] / "Resources"
        resources.mkdir()
        (resources / "runner-link").symlink_to("../MacOS/AFKGrinder")

        archive = package_archive(
            self.root, "macos-arm64", COMMIT, self.root / "artifact-output",
            system="darwin", machine="arm64", timestamp=STAMP,
        )

        self.assertEqual(archive.name, "AFKGrinder-macos-arm64.tar.gz")
        with tarfile.open(archive) as packaged:
            executable_info = packaged.getmember("AFKGrinder.app/Contents/MacOS/AFKGrinder")
            link_info = packaged.getmember("AFKGrinder.app/Contents/Resources/runner-link")
        self.assertTrue(executable_info.mode & stat.S_IXUSR)
        self.assertTrue(link_info.issym())
        self.assertEqual(link_info.linkname, "../MacOS/AFKGrinder")

    def test_rejects_invalid_label_commit_and_missing_bundles(self) -> None:
        with self.assertRaisesRegex(ValueError, "--label"):
            package_archive(self.root, "linux-x64", COMMIT, system="linux", machine="x86_64")
        with self.assertRaisesRegex(ValueError, "40 hexadecimal"):
            package_archive(self.root, "windows-x64", "short", system="win32", machine="AMD64")
        with self.assertRaisesRegex(ValueError, "Windows bundle"):
            package_archive(self.root, "windows-x64", COMMIT, system="win32", machine="AMD64")

        (self.root / "dist" / "AFKGrinder").mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "Windows executable"):
            package_archive(self.root, "windows-x64", COMMIT, system="win32", machine="AMD64")
        with self.assertRaisesRegex(ValueError, "macOS app bundle"):
            package_archive(self.root, "macos-x64", COMMIT, system="darwin", machine="x86_64")

    def test_rejects_runtime_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires win32"):
            package_archive(self.root, "windows-x64", COMMIT, system="darwin", machine="arm64")
        with self.assertRaisesRegex(ValueError, "x86_64"):
            package_archive(self.root, "macos-x64", COMMIT, system="darwin", machine="arm64")

    @unittest.skipIf(sys.platform == "win32", "Windows CI may not permit symlink fixtures")
    def test_rejects_escaping_macos_symlink(self) -> None:
        executable = self.root / "dist" / "AFKGrinder.app" / "Contents" / "MacOS" / "AFKGrinder"
        executable.parent.mkdir(parents=True)
        executable.write_bytes(b"mac executable")
        escaped = executable.parents[3] / "outside"
        escaped.write_text("outside")
        (executable.parents[1] / "escape").symlink_to("../../outside")
        with self.assertRaisesRegex(ValueError, "outside app bundle"):
            package_archive(
                self.root, "macos-x64", COMMIT, system="darwin", machine="x86_64"
            )

    def test_macos_check_allows_only_known_permission_messages(self) -> None:
        permission_result = subprocess.CompletedProcess(
            [], 1,
            "Foreground Roblox player: no\n"
            "Input Monitoring permission is required to read Escape emergency stop.\n",
            "",
        )
        unavailable_result = subprocess.CompletedProcess(
            [], 1,
            "Input Monitoring permission is required to read Escape emergency stop.\n"
            "CGPreflightListenEventAccess is unavailable.\n",
            "",
        )

        self.assertTrue(_acceptable_macos_check(permission_result))
        self.assertFalse(_acceptable_macos_check(unavailable_result))


if __name__ == "__main__":
    unittest.main()
