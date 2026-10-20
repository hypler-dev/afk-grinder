"""Synthetic safety tests for pinned MaaDeps build prerequisites."""

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

from tools import sdk_build_dependencies


class SdkBuildDependencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.archives = self.root / "archives"
        self.archives.mkdir()
        self.raw_manifest = json.loads(sdk_build_dependencies.MANIFEST_PATH.read_text(encoding="utf-8"))

    def _entries(self, label: str, link_count: int = 1) -> list[tuple[str, bytes, str, str]]:
        triplet = self.raw_manifest["targets"][label]["triplet"]
        entries = [
            ("./vcpkg/", b"", "dir", ""),
            (f"./vcpkg/installed/{triplet}/", b"", "dir", ""),
            (f"./vcpkg/installed/{triplet}/NOTICE", b"notice\n", "file", ""),
            ("./runtime/", b"", "dir", ""),
            (f"./runtime/{triplet}/", b"", "dir", ""),
            (f"./runtime/{triplet}/libonnxruntime.dylib", b"runtime", "file", ""),
            ("./msbuild/props", b"props\n", "file", ""),
            ("./maadeps.cmake", b"set(MAA_DEPS 1)\n", "file", ""),
        ]
        for index in range(link_count):
            target = "libonnxruntime.dylib" if index + 1 == link_count else f"libonnxruntime.{index + 2}.dylib"
            entries.append((f"./runtime/{triplet}/libonnxruntime.{index + 1}.dylib", b"", "link", target))
        return entries

    def _archive(self, label: str, entries: list[tuple[str, bytes, str, str]] | None = None) -> Path:
        path = self.archives / f"{label}.tar.xz"
        entries = entries if entries is not None else self._entries(label)
        with tarfile.open(path, "w:xz") as archive:
            for name, payload, kind, linkname in entries:
                info = tarfile.TarInfo(name)
                if kind == "dir":
                    info.type = tarfile.DIRTYPE
                    info.mode = 0o755
                    archive.addfile(info)
                elif kind == "link":
                    info.type = tarfile.SYMTYPE
                    info.linkname = linkname
                    archive.addfile(info)
                else:
                    info.size = len(payload)
                    info.mode = 0o755 if name.endswith("tool") else 0o644
                    archive.addfile(info, io.BytesIO(payload))
        return path

    def _manifest_for(self, archives: dict[str, Path]) -> Path:
        raw = json.loads(json.dumps(self.raw_manifest))
        for label, entry in raw["targets"].items():
            payload = archives[label].read_bytes()
            entry["size"] = len(payload)
            entry["sha256"] = hashlib.sha256(payload).hexdigest()
        manifest = self.root / "sdk_build_dependencies.json"
        manifest.write_text(json.dumps(raw), encoding="utf-8")
        return manifest

    def _archives(self) -> dict[str, Path]:
        return {label: self._archive(label) for label in self.raw_manifest["targets"]}

    def _prepare(self, manifest: Path, archives: dict[str, Path], destination: Path, label: str = "macos-arm64") -> None:
        def transport(_curl: str, dependency: sdk_build_dependencies.BuildDependency, output: Path) -> None:
            shutil.copyfile(archives[dependency.label], output)

        with patch.object(sdk_build_dependencies, "MANIFEST_PATH", manifest), patch.object(sdk_build_dependencies.shutil, "which", return_value="curl"), patch.object(sdk_build_dependencies, "_download", side_effect=transport):
            sdk_build_dependencies.prepare_dependencies(label, destination)

    def test_loads_repository_fixed_manifest(self) -> None:
        dependencies = sdk_build_dependencies.load_dependencies()
        self.assertEqual(set(dependencies), {"macos-arm64", "macos-x64", "windows-x64"})
        self.assertEqual(dependencies["windows-x64"].triplet, "maa-x64-windows")

    def test_loads_fixed_dependencies_and_prepares_permitted_links_and_notices(self) -> None:
        archives = self._archives()
        manifest = self._manifest_for(archives)
        destination = self.root / "prepared"
        self._prepare(manifest, archives, destination)
        with patch.object(sdk_build_dependencies, "MANIFEST_PATH", manifest):
            loaded = sdk_build_dependencies.load_dependencies()
        dependency = loaded["macos-arm64"]
        self.assertEqual(dependency.triplet, "maa-arm64-osx")
        self.assertEqual((destination / "vcpkg/installed/maa-arm64-osx/NOTICE").read_bytes(), b"notice\n")
        link = destination / "runtime/maa-arm64-osx/libonnxruntime.1.dylib"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.readlink(), Path("libonnxruntime.dylib"))
        self.assertEqual((destination / "archives" / dependency.archive_name).read_bytes(), archives[dependency.label].read_bytes())
        self.assertEqual((destination / "sdk_build_dependencies.json").read_bytes(), manifest.read_bytes())
        self.assertEqual(json.loads((destination / "PROVENANCE.json").read_text())["dependency"]["label"], dependency.label)

    def test_prepares_windows_zero_link_fixture_with_native_publish(self) -> None:
        archives = self._archives()
        archives["windows-x64"] = self._archive("windows-x64", self._entries("windows-x64", link_count=0))
        manifest = self._manifest_for(archives)
        destination = self.root / "windows"
        self._prepare(manifest, archives, destination, label="windows-x64")
        dependency = sdk_build_dependencies.load_dependencies()["windows-x64"]
        self.assertTrue((destination / "vcpkg/installed/maa-x64-windows").is_dir())
        self.assertTrue((destination / "runtime/maa-x64-windows").is_dir())
        self.assertFalse(any(path.is_symlink() for path in (destination / "runtime/maa-x64-windows").iterdir()))
        self.assertEqual((destination / "archives" / dependency.archive_name).read_bytes(), archives["windows-x64"].read_bytes())
        self.assertEqual((destination / "sdk_build_dependencies.json").read_bytes(), manifest.read_bytes())
        self.assertEqual(json.loads((destination / "PROVENANCE.json").read_text())["dependency"]["label"], "windows-x64")

    def test_accepts_sixteen_link_chain_and_rejects_seventeen(self) -> None:
        for count, succeeds in ((16, True), (17, False), (100, False)):
            with self.subTest(link_count=count):
                archives = self._archives()
                archives["macos-arm64"] = self._archive("macos-arm64", self._entries("macos-arm64", link_count=count))
                manifest = self._manifest_for(archives)
                destination = self.root / f"chain-{count}"
                if succeeds:
                    self._prepare(manifest, archives, destination)
                    self.assertTrue(destination.is_dir())
                else:
                    with self.assertRaisesRegex(ValueError, "chain exceeds depth"):
                        self._prepare(manifest, archives, destination)
                    self.assertFalse(destination.exists())

    def test_rejects_hash_or_size_mismatch_before_extracting(self) -> None:
        archives = self._archives()
        manifest = self._manifest_for(archives)
        raw = json.loads(manifest.read_text())
        raw["targets"]["macos-arm64"]["size"] += 1
        manifest.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "size did not match"):
            self._prepare(manifest, archives, self.root / "bad-size")
        raw["targets"]["macos-arm64"]["size"] -= 1
        raw["targets"]["macos-arm64"]["sha256"] = "0" * 64
        manifest.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self._prepare(manifest, archives, self.root / "bad-hash")

    def test_rejects_escaping_cyclic_and_child_under_link(self) -> None:
        triplet = self.raw_manifest["targets"]["macos-arm64"]["triplet"]
        cases = {
            "escape": [(f"runtime/{triplet}/", b"", "dir", ""), (f"runtime/{triplet}/bad", b"", "link", "../outside")],
            "cycle": [(f"runtime/{triplet}/", b"", "dir", ""), (f"runtime/{triplet}/a", b"", "link", "b"), (f"runtime/{triplet}/b", b"", "link", "a")],
            "child": [
                (f"runtime/{triplet}/", b"", "dir", ""),
                (f"runtime/{triplet}/target", b"target", "file", ""),
                (f"runtime/{triplet}/link", b"", "link", "target"),
                (f"runtime/{triplet}/link/child", b"x", "file", ""),
            ],
        }
        for name, entries in cases.items():
            with self.subTest(name=name):
                archives = self._archives()
                archives["macos-arm64"] = self._archive("macos-arm64", entries)
                manifest = self._manifest_for(archives)
                with self.assertRaises(ValueError):
                    self._prepare(manifest, archives, self.root / name)
                self.assertFalse((self.root / name).exists())

    def test_rejects_member_and_regular_payload_limits(self) -> None:
        triplet = self.raw_manifest["targets"]["macos-arm64"]["triplet"]
        archives = self._archives()
        archives["macos-arm64"] = self._archive("macos-arm64", [(f"vcpkg/installed/{triplet}/huge", b"x" * 65, "file", "")])
        manifest = self._manifest_for(archives)
        with patch.object(sdk_build_dependencies, "MAX_REGULAR_BYTES", 64):
            with self.assertRaisesRegex(ValueError, "regular-file size"):
                self._prepare(manifest, archives, self.root / "large")
        archives = self._archives()
        manifest = self._manifest_for(archives)
        with patch.object(sdk_build_dependencies, "MAX_MEMBERS", 2):
            with self.assertRaisesRegex(ValueError, "member limit"):
                self._prepare(manifest, archives, self.root / "many")

    def test_rejects_wrong_manifest_existing_destination_and_publish_race(self) -> None:
        archives = self._archives()
        manifest = self._manifest_for(archives)
        raw = json.loads(manifest.read_text())
        raw["targets"]["macos-arm64"]["url"] = "https://example.test/other.tar.xz"
        manifest.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "URL"):
            self._prepare(manifest, archives, self.root / "wrong-manifest")
        manifest = self._manifest_for(archives)
        existing = self.root / "existing"
        existing.mkdir()
        marker = existing / "keep"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "already exists"):
            self._prepare(manifest, archives, existing)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
        dangling = self.root / "dangling"
        dangling.symlink_to(self.root / "missing", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "already exists"):
            self._prepare(manifest, archives, dangling)
        self.assertTrue(dangling.is_symlink())
        for kind in ("directory", "symlink"):
            with self.subTest(kind=kind):
                destination = self.root / f"race-{kind}"
                sentinel = self.root / f"sentinel-{kind}"
                sentinel.mkdir()
                marker = sentinel / "keep"
                marker.write_text("keep", encoding="utf-8")
                original_publish = sdk_build_dependencies._publish_new

                def create_target(stage: Path, target: Path) -> None:
                    if kind == "directory":
                        target.mkdir()
                    else:
                        target.symlink_to(sentinel, target_is_directory=True)
                    original_publish(stage, target)

                with patch.object(sdk_build_dependencies, "_publish_new", side_effect=create_target):
                    with self.assertRaises(FileExistsError):
                        self._prepare(manifest, archives, destination)
                self.assertEqual(marker.read_text(encoding="utf-8"), "keep")
                if kind == "directory":
                    self.assertEqual(list(destination.iterdir()), [])
                else:
                    self.assertTrue(destination.is_symlink())
                    self.assertTrue(destination.samefile(sentinel))
                self.assertFalse(list(self.root.glob(f".{destination.name}.stage-*")))

    def test_download_uses_fixed_https_only_curl_contract(self) -> None:
        dependency = sdk_build_dependencies.BuildDependency(
            "macos-arm64", "darwin", "arm64", "maa-arm64-osx", "MaaDeps-arm64-osx.tar.xz",
            "https://github.com/MaaXYZ/MaaDeps/releases/download/v3.0.0/MaaDeps-arm64-osx.tar.xz",
            123, "0" * 64,
        )
        with patch("tools.sdk_build_dependencies.subprocess.run") as run:
            sdk_build_dependencies._download("/usr/bin/curl", dependency, self.root / "asset.tar.xz")
        command = run.call_args.args[0]
        self.assertEqual(command[:3], ["/usr/bin/curl", "--disable", "--fail"])
        self.assertEqual(command[command.index("--proto") + 1], "=https")
        self.assertEqual(command[command.index("--proto-redir") + 1], "=https")
        self.assertEqual(command[command.index("--max-time") + 1], "180")
        self.assertEqual(command[command.index("--max-filesize") + 1], "123")


if __name__ == "__main__":
    unittest.main()
