"""Synthetic tests for local unsigned macOS bundle version stamping."""

from __future__ import annotations

from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.macos_bundle import stamp_unsigned_bundle_version


class MacOSBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.bundle = Path(self.temporary.name) / "AFKGrinder.app"
        self.info = self.bundle / "Contents" / "Info.plist"
        self.info.parent.mkdir(parents=True)
        with self.info.open("wb") as destination:
            plistlib.dump(
                {
                    "CFBundleIdentifier": "com.hypler.afkgrinder",
                    "CFBundleShortVersionString": "0.0.0",
                    "CFBundleVersion": "0.0.0",
                    "NSHighResolutionCapable": True,
                },
                destination,
            )

    def _plist(self) -> dict[str, object]:
        with self.info.open("rb") as source:
            return plistlib.load(source)

    @patch("tools.macos_bundle.subprocess.run")
    def test_stamps_versions_preserves_keys_and_ad_hoc_verifies(self, run) -> None:
        stamp_unsigned_bundle_version(self.bundle, "0.2.0")

        self.assertEqual(
            self._plist(),
            {
                "CFBundleIdentifier": "com.hypler.afkgrinder",
                "CFBundleShortVersionString": "0.2.0",
                "CFBundleVersion": "0.2.0",
                "NSHighResolutionCapable": True,
            },
        )
        self.assertEqual(
            run.call_args_list,
            [
                unittest.mock.call(
                    ["codesign", "--force", "--sign", "-", str(self.bundle)], check=True
                ),
                unittest.mock.call(
                    ["codesign", "--verify", "--deep", "--strict", str(self.bundle)], check=True
                ),
            ],
        )

    @patch("tools.macos_bundle.subprocess.run")
    def test_invalid_version_or_plist_fails_without_rewrite_or_codesign(self, run) -> None:
        original = self.info.read_bytes()
        for version in ("0.2", "v0.2.0", "0.2.0-beta", ""):
            with self.subTest(version=version), self.assertRaisesRegex(ValueError, "numeric"):
                stamp_unsigned_bundle_version(self.bundle, version)
            self.assertEqual(self.info.read_bytes(), original)
        with self.info.open("wb") as destination:
            plistlib.dump(["not", "a", "dictionary"], destination)
        malformed = self.info.read_bytes()
        with self.assertRaisesRegex(ValueError, "dictionary"):
            stamp_unsigned_bundle_version(self.bundle, "0.2.0")
        self.assertEqual(self.info.read_bytes(), malformed)
        run.assert_not_called()

    @patch("tools.macos_bundle.subprocess.run")
    def test_propagates_sign_and_verification_failures(self, run) -> None:
        sign_error = subprocess.CalledProcessError(1, ["codesign"])
        run.side_effect = sign_error
        with self.assertRaises(subprocess.CalledProcessError):
            stamp_unsigned_bundle_version(self.bundle, "0.2.0")
        self.assertEqual(run.call_count, 1)

        run.reset_mock()
        verify_error = subprocess.CalledProcessError(1, ["codesign", "--verify"])
        run.side_effect = [None, verify_error]
        with self.assertRaises(subprocess.CalledProcessError):
            stamp_unsigned_bundle_version(self.bundle, "0.2.0")
        self.assertEqual(run.call_count, 2)

    @unittest.skipIf(sys.platform == "win32", "Windows runners may not permit symlink fixtures")
    @patch("tools.macos_bundle.subprocess.run")
    def test_contents_symlink_cannot_rewrite_an_external_plist(self, run) -> None:
        external = self.bundle.parent / "external-contents"
        external.mkdir()
        external_info = external / "Info.plist"
        external_info.write_bytes(b"external bytes")
        self.info.unlink()
        self.info.parent.rmdir()
        (self.bundle / "Contents").symlink_to(external, target_is_directory=True)

        with self.assertRaisesRegex(ValueError, "real Contents directory"):
            stamp_unsigned_bundle_version(self.bundle, "0.2.0")

        self.assertEqual(external_info.read_bytes(), b"external bytes")
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
