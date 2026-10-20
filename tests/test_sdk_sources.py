"""Synthetic safety tests for fixed Maa SDK source preparation."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import fetch_sdk_sources


class SdkSourcePreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archives = self.root / "archives"
        self.archives.mkdir()
        self.raw_manifest = json.loads(fetch_sdk_sources.MANIFEST_PATH.read_text(encoding="utf-8"))

    def _archive(self, component: dict[str, object], entries: list[tuple[str, bytes, str]] | None = None) -> Path:
        root = str(component["archive_root"])
        path = self.archives / f"{component['name']}.tar.gz"
        entries = entries or [(f"{root}/", b"", "dir"), (f"{root}/LICENSE", b"upstream notice\n", "file"), (f"{root}/src/main.cpp", b"int main() {}\n", "file")]
        with tarfile.open(path, "w:gz") as archive:
            for name, payload, kind in entries:
                info = tarfile.TarInfo(name)
                if kind == "dir":
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    archive.addfile(info)
                elif kind == "symlink":
                    info.type = tarfile.SYMTYPE
                    info.linkname = "elsewhere"
                    archive.addfile(info)
                elif kind == "hardlink":
                    info.type = tarfile.LNKTYPE
                    info.linkname = "elsewhere"
                    archive.addfile(info)
                else:
                    info.size = len(payload)
                    info.mode = 0o755 if name.endswith("tool") else 0o644
                    archive.addfile(info, io.BytesIO(payload))
        return path

    def _manifest_for(self, archive_by_name: dict[str, Path]) -> Path:
        raw = json.loads(json.dumps(self.raw_manifest))
        for component in raw["components"]:
            payload = archive_by_name[component["name"]].read_bytes()
            component["size"] = len(payload)
            component["sha256"] = hashlib.sha256(payload).hexdigest()
        path = self.root / "sdk_sources.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        return path

    def _prepare(self, manifest: Path, archive_by_name: dict[str, Path], destination: Path) -> None:
        def fake_download(_curl: str, component: fetch_sdk_sources.SourceComponent, output: Path) -> None:
            shutil.copyfile(archive_by_name[component.name], output)

        with patch.object(fetch_sdk_sources, "MANIFEST_PATH", manifest), patch.object(fetch_sdk_sources.shutil, "which", return_value="curl"), patch.object(fetch_sdk_sources, "download_archive", side_effect=fake_download):
            fetch_sdk_sources.prepare(destination)

    def _valid_archives(self) -> dict[str, Path]:
        return {component["name"]: self._archive(component) for component in self.raw_manifest["components"]}

    def test_prepares_all_fixed_archives_nested_sources_notices_and_provenance(self) -> None:
        archives = self._valid_archives()
        manifest = self._manifest_for(archives)
        destination = self.root / "prepared"
        self._prepare(manifest, archives, destination)
        components = json.loads(manifest.read_text())["components"]
        for component in components:
            source = destination / component["destination"]
            self.assertEqual((source / "LICENSE").read_bytes(), b"upstream notice\n")
            archived = destination / "archives" / f"{component['name']}-{component['commit']}.tar.gz"
            self.assertEqual(archived.read_bytes(), archives[component["name"]].read_bytes())
        self.assertEqual((destination / "sdk_sources.json").read_bytes(), manifest.read_bytes())
        self.assertEqual(json.loads((destination / "PROVENANCE.json").read_text())["manifest"], "sdk_sources.json")
        self.assertTrue((destination / "source/MaaFramework/source/MaaUtils/MaaDeps/vcpkg/src/main.cpp").is_file())

    def test_rejects_size_or_hash_mismatch_before_extracting(self) -> None:
        archives = self._valid_archives()
        manifest = self._manifest_for(archives)
        raw = json.loads(manifest.read_text())
        raw["components"][0]["size"] += 1
        manifest.write_text(json.dumps(raw), encoding="utf-8")
        destination = self.root / "bad-size"
        with self.assertRaisesRegex(ValueError, "size did not match"):
            self._prepare(manifest, archives, destination)
        self.assertFalse(destination.exists())
        raw["components"][0]["size"] -= 1
        raw["components"][0]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256 did not match"):
            self._prepare(manifest, archives, destination)
        self.assertFalse(destination.exists())

    def test_rejects_malicious_archive_shapes_and_cleans_stage(self) -> None:
        cases = {
            "traversal": [("MaaFramework-8963191215ca49d6b037802acd07d20a4213160a/../escape", b"x", "file")],
            "link": [("MaaFramework-8963191215ca49d6b037802acd07d20a4213160a/link", b"", "symlink")],
            "duplicate": [("MaaFramework-8963191215ca49d6b037802acd07d20a4213160a/a", b"x", "file"), ("MaaFramework-8963191215ca49d6b037802acd07d20a4213160a/a", b"y", "file")],
            "wrong-root": [("other-root/LICENSE", b"x", "file")],
        }
        for case, entries in cases.items():
            with self.subTest(case=case):
                archives = self._valid_archives()
                archives["MaaFramework"] = self._archive(self.raw_manifest["components"][0], entries)
                manifest = self._manifest_for(archives)
                destination = self.root / case
                with self.assertRaises(ValueError):
                    self._prepare(manifest, archives, destination)
                self.assertFalse(destination.exists())
                self.assertFalse(list(self.root.glob(f".{destination.name}.stage-*")))

    def test_rejects_unpacked_size_and_member_limits(self) -> None:
        component = self.raw_manifest["components"][0]
        root = component["archive_root"]
        archives = self._valid_archives()
        archives["MaaFramework"] = self._archive(component, [(f"{root}/a", b"x" * 65, "file")])
        manifest = self._manifest_for(archives)
        with patch.object(fetch_sdk_sources, "MAX_UNPACKED_BYTES", 64):
            with self.assertRaisesRegex(ValueError, "unpacked size"):
                self._prepare(manifest, archives, self.root / "too-large")
        archives["MaaFramework"] = self._archive(component, [(f"{root}/a", b"x", "file"), (f"{root}/b", b"x", "file"), (f"{root}/c", b"x", "file")])
        manifest = self._manifest_for(archives)
        with patch.object(fetch_sdk_sources, "MAX_UNPACKED_MEMBERS", 2):
            with self.assertRaisesRegex(ValueError, "member limit"):
                self._prepare(manifest, archives, self.root / "too-many")
        archives = self._valid_archives()
        manifest = self._manifest_for(archives)
        with patch.object(fetch_sdk_sources, "MAX_UNPACKED_MEMBERS", 11):
            with self.assertRaisesRegex(ValueError, "member limit"):
                self._prepare(manifest, archives, self.root / "too-many-total")

    def test_refuses_existing_directory_or_symlink_without_touching_it(self) -> None:
        archives = self._valid_archives()
        manifest = self._manifest_for(archives)
        destination = self.root / "existing"
        destination.mkdir()
        marker = destination / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self._prepare(manifest, archives, destination)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        link = self.root / "source-link"
        try:
            link.symlink_to(destination, target_is_directory=True)
        except OSError as error:
            self.skipTest(f"symlink fixture unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self._prepare(manifest, archives, link)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    @unittest.skipUnless(sys.platform in {"darwin", "win32"}, "native no-replace publication is supported only on delivery hosts")
    def test_publish_race_keeps_empty_directory_or_symlink_and_cleans_stage(self) -> None:
        for kind in ("directory", "symlink"):
            with self.subTest(kind=kind):
                archives = self._valid_archives()
                manifest = self._manifest_for(archives)
                destination = self.root / f"race-{kind}"
                sentinel = self.root / f"sentinel-{kind}"
                sentinel.mkdir()
                marker = sentinel / "keep.txt"
                marker.write_text("keep", encoding="utf-8")
                original_publish = fetch_sdk_sources._publish_new

                def create_destination(stage: Path, target: Path) -> None:
                    if kind == "directory":
                        target.mkdir()
                    else:
                        target.symlink_to(sentinel, target_is_directory=True)
                    original_publish(stage, target)

                with patch.object(fetch_sdk_sources, "_publish_new", side_effect=create_destination):
                    with self.assertRaises(FileExistsError):
                        self._prepare(manifest, archives, destination)
                self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
                if kind == "directory":
                    self.assertTrue(destination.is_dir())
                    self.assertFalse(destination.is_symlink())
                    self.assertEqual(list(destination.iterdir()), [])
                else:
                    self.assertTrue(destination.is_symlink())
                    self.assertTrue(destination.samefile(sentinel))
                self.assertFalse(list(self.root.glob(f".{destination.name}.stage-*")))

    @unittest.skipUnless(sys.platform == "darwin", "macOS native backend proof")
    def test_macos_publish_uses_native_exclusive_rename(self) -> None:
        stage = self.root / "native-stage"
        stage.mkdir()
        (stage / "receipt.txt").write_text("verified", encoding="utf-8")
        destination = self.root / "native-destination"
        fetch_sdk_sources._publish_new(stage, destination)
        self.assertFalse(stage.exists())
        self.assertEqual((destination / "receipt.txt").read_text(encoding="utf-8"), "verified")

    def test_windows_and_unsupported_publish_backends_fail_closed(self) -> None:
        stage = self.root / "backend-stage"
        target = self.root / "backend-target"
        with patch("tools.fetch_sdk_sources.sys.platform", "win32"), patch("tools.fetch_sdk_sources.os.rename", side_effect=FileExistsError("occupied")) as rename:
            with self.assertRaises(FileExistsError):
                fetch_sdk_sources._publish_new(stage, target)
        rename.assert_called_once_with(stage, target)
        with patch("tools.fetch_sdk_sources.sys.platform", "linux"):
            with self.assertRaisesRegex(OSError, "unsupported"):
                fetch_sdk_sources._publish_new(stage, target)

    def test_rejects_invalid_fixed_manifest_before_transport(self) -> None:
        raw = json.loads(json.dumps(self.raw_manifest))
        raw["components"][0]["url"] = "https://example.test/arbitrary.tar.gz"
        manifest = self.root / "invalid.json"
        manifest.write_text(json.dumps(raw), encoding="utf-8")
        with patch.object(fetch_sdk_sources, "MANIFEST_PATH", manifest), patch.object(fetch_sdk_sources, "download_archive") as download:
            with self.assertRaisesRegex(ValueError, "fixed codeload"):
                fetch_sdk_sources.prepare(self.root / "never")
        download.assert_not_called()

    def test_curl_transport_starts_with_disable_and_stays_https_only(self) -> None:
        component = fetch_sdk_sources.SourceComponent(
            "MaaFramework", "MaaXYZ/MaaFramework", "8963191215ca49d6b037802acd07d20a4213160a",
            "https://codeload.github.com/MaaXYZ/MaaFramework/tar.gz/8963191215ca49d6b037802acd07d20a4213160a",
            1, "0" * 64, "MaaFramework-8963191215ca49d6b037802acd07d20a4213160a", "source/MaaFramework",
        )
        with patch("tools.fetch_sdk_sources.subprocess.run") as run:
            fetch_sdk_sources.download_archive("/usr/bin/curl", component, self.root / "archive")
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["/usr/bin/curl", "--disable", "--fail"])
        self.assertIn("--proto", command)
        self.assertIn("--proto-redir", command)
        self.assertEqual(command[command.index("--proto") + 1], "=https")
        self.assertEqual(command[command.index("--proto-redir") + 1], "=https")


if __name__ == "__main__":
    unittest.main()
