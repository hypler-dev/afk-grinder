"""Restricted recognition packs stay data-only and fail closed."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import zlib

from afk_grinder.recognition import packs
from afk_grinder.recognition.packs import PackError, load_pack


def png_chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(payload, zlib.crc32(kind)) & 0xFFFFFFFF)


def png(width: int = 1, height: int = 1, raw: bytes | None = None) -> bytes:
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\0" + b"\0\0\0" * width for _ in range(height)) if raw is None else raw
    return b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", header) + png_chunk(b"IDAT", zlib.compress(raw)) + png_chunk(b"IEND", b"")


class CachedZeroEntry:
    """Model Windows cached DirEntry metadata while retaining its real path."""

    def __init__(self, entry):
        self._entry = entry
        self.name = entry.name
        self.path = entry.path

    def stat(self, *, follow_symlinks=True):
        real = self._entry.stat(follow_symlinks=follow_symlinks)
        return SimpleNamespace(st_mode=real.st_mode, st_nlink=0, st_dev=0, st_ino=0)


class CachedZeroScandir:
    def __init__(self, original, path):
        self._scan = original(path)

    def __enter__(self):
        self._scan.__enter__()
        return self

    def __exit__(self, *arguments):
        return self._scan.__exit__(*arguments)

    def __iter__(self):
        return self

    def __next__(self):
        return CachedZeroEntry(next(self._scan))


def manifest(*, assets=None, anchors=None, states=None, routines=None, **changes):
    value = {
        "format": "afk-resource-pack",
        "schema_version": 1,
        "id": "adopt-me.skeleton",
        "version": "0.1.0",
        "min_app_version": "0.1.0",
        "provenance": {
            "source": "https://example.test/packs/adopt-me",
            "revision": "a" * 40,
            "license": "MIT",
            "attribution": "Example author",
        },
        "reference_size": [1920, 1080],
        "setup": {"language": "en", "instructions": "Use prescribed room.", "min_content_size": [960, 540]},
        "assets": [] if assets is None else assets,
        "anchors": [] if anchors is None else anchors,
        "states": [] if states is None else states,
        "routines": [] if routines is None else routines,
    }
    value.update(changes)
    return value


class PackLoaderTests(unittest.TestCase):
    def write_pack(self, root: Path, payload=None, files=None, *, raw=None):
        root.mkdir(parents=True, exist_ok=True)
        (root / "pack.json").write_bytes(raw if raw is not None else json.dumps(payload or manifest()).encode())
        for path, data in (files or {}).items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)

    def asset_manifest(self, data=None, **asset_changes):
        data = png() if data is None else data
        asset = {"id": "hud.icon", "path": "assets/hud.png", "sha256": hashlib.sha256(data).hexdigest()}
        asset.update(asset_changes)
        anchor = {"id": "hud.anchor", "asset": "hud.icon", "roi": [0, 0, 20, 20], "threshold": 0.9, "scale_range": [0.5, 2]}
        state = {"id": "gameplay", "positive": ["hud.anchor"], "exclude": [], "stable_frames": 2}
        return manifest(assets=[asset], anchors=[anchor], states=[state]), {"assets/hud.png": data}

    def test_empty_skeleton_is_immutable_and_has_no_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_pack(root)
            pack = load_pack(root)
        self.assertEqual(pack.assets, ())
        self.assertEqual(pack.anchors, ())
        self.assertEqual(pack.states, ())
        with self.assertRaises(AttributeError):
            pack.id = "mutated"

    def test_loads_only_hashed_png_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload, files = self.asset_manifest()
            self.write_pack(root, payload, files)
            pack = load_pack(root)
        self.assertEqual(pack.assets[0].data, png())
        self.assertIsInstance(pack.assets[0].data, bytes)
        self.assertEqual(pack.states[0].positive, ("hud.anchor",))

    def test_state_kind_is_optional_and_strict(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload, files = self.asset_manifest()
            self.write_pack(root, payload, files)
            self.assertEqual(load_pack(root).states[0].kind, "unclassified")

        for kind in ("unclassified", "gameplay", "popup", "transaction", "loading", "disconnected", "unknown"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payload, files = self.asset_manifest()
                payload["states"][0]["kind"] = kind
                self.write_pack(root, payload, files)
                self.assertEqual(load_pack(root).states[0].kind, kind)

        invalid = (None, True, 1, "Popup", "unsupported")
        for kind in invalid:
            with self.subTest(kind=repr(kind)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payload, files = self.asset_manifest()
                payload["states"][0]["kind"] = kind
                self.write_pack(root, payload, files)
                with self.assertRaises(PackError):
                    load_pack(root)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload, files = self.asset_manifest()
            payload["states"][0]["kind"] = "popup"
            payload["states"][0]["unexpected"] = True
            self.write_pack(root, payload, files)
            with self.assertRaises(PackError):
                load_pack(root)

    def test_tamper_hash_and_png_header_fail(self):
        for contents, label, matching_hash in ((b"tampered", "hash", False), (b"not-a-png", "header", True), (png(4001, 4000, b""), "bomb", True)):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payload, files = self.asset_manifest(contents if matching_hash else None)
                files["assets/hud.png"] = contents
                self.write_pack(root, payload, files)
                with self.assertRaises(PackError):
                    load_pack(root)

    def test_truncated_bad_crc_and_missing_iend_pngs_fail(self):
        valid = png()
        malformed = (valid[:24], valid[:-1] + bytes([valid[-1] ^ 1]), valid[:-12])
        for contents in malformed:
            with self.subTest(length=len(contents)), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payload, files = self.asset_manifest(contents)
                self.write_pack(root, payload, files)
                with self.assertRaises(PackError):
                    load_pack(root)

    def test_duplicate_json_keys_nonfinite_json_oversize_and_depth_fail(self):
        cases = [
            b'{"format":"afk-resource-pack","format":"afk-resource-pack"}',
            b'{"value":NaN}',
            b"[" * 1000 + b"0" + b"]" * 1000,
            b'{"integer":' + b"9" * 10000 + b"}",
            b" " * (256 * 1024 + 1),
        ]
        for raw in cases:
            with self.subTest(raw=raw[:30]), tempfile.TemporaryDirectory() as directory:
                self.write_pack(Path(directory), raw=raw)
                with self.assertRaises(PackError):
                    load_pack(directory)

    def test_huge_integer_in_known_numeric_field_becomes_pack_error(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload, files = self.asset_manifest()
            raw = json.dumps(payload).replace('"threshold": 0.9', '"threshold": ' + '9' * 4000).encode()
            self.write_pack(root, files=files, raw=raw)
            with self.assertRaises(PackError):
                load_pack(root)

    def test_curated_base_contains_real_directory_path_only(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "curated"
            root = base / "packs" / "one"
            self.write_pack(root)
            self.assertEqual(load_pack(root, curated_base=base).id, "adopt-me.skeleton")
            outside = Path(directory) / "outside"
            self.write_pack(outside)
            with self.assertRaises(PackError):
                load_pack(outside, curated_base=base)
            alias = base / "alias"
            alias.symlink_to(base / "packs", target_is_directory=True)
            with self.assertRaises(PackError):
                load_pack(alias / "one", curated_base=base)

    def test_root_swap_during_load_fails_even_when_descriptor_is_pinned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "pack"
            self.write_pack(root)
            original = packs._parse_manifest

            def swap_then_parse(data):
                root.rename(Path(directory) / "replaced")
                self.write_pack(root)
                return original(data)

            with patch.object(packs, "_parse_manifest", side_effect=swap_then_parse), self.assertRaises(PackError):
                load_pack(root)

    def test_path_fallback_uses_fresh_windows_metadata_and_rejects_hardlinks(self):
        original_scandir = packs.os.scandir

        def cached_zero_scandir(path):
            return CachedZeroScandir(original_scandir, path)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_pack(root)
            with patch.object(packs.os, "supports_dir_fd", set()), patch.object(packs.os, "scandir", side_effect=cached_zero_scandir):
                self.assertEqual(load_pack(root).id, "adopt-me.skeleton")
            (root / "LICENSE").write_bytes(b"MIT")
            (root / "LICENSE.txt").hardlink_to(root / "LICENSE")
            with patch.object(packs.os, "supports_dir_fd", set()), patch.object(packs.os, "scandir", side_effect=cached_zero_scandir), self.assertRaises(PackError):
                load_pack(root)

    def test_fallback_binary_read_preserves_crlf_and_substitute_byte(self):
        with tempfile.TemporaryDirectory() as directory:
            root_path = Path(directory)
            payload = b"first\r\nsecond\x1athird\r\n"
            (root_path / "payload.bin").write_bytes(payload)
            with patch.object(packs.os, "supports_dir_fd", set()):
                root = packs._open_root(root_path, None)
                try:
                    self.assertEqual(packs._read_regular(root, "payload.bin", 100), payload)
                finally:
                    root.close()
            root = packs._Root(root_path, (root_path.stat().st_dev, root_path.stat().st_ino), None)
            with patch.object(packs.os, "O_BINARY", 0x8000, create=True), patch.object(packs.os, "open", return_value=99) as open_file:
                packs._open_beneath_root(root, "payload.bin")
            self.assertTrue(open_file.call_args.args[1] & 0x8000)

    def test_tree_breadth_depth_and_unlisted_empty_directories_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_pack(root)
            for index in range(257):
                (root / f"file-{index}").write_bytes(b"x")
            with self.assertRaises(PackError):
                load_pack(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nested = "assets/" + "/".join(f"d{index}" for index in range(17)) + "/hud.png"
            payload, files = self.asset_manifest(path=nested)
            self.write_pack(root, payload, files)
            with self.assertRaises(PackError):
                load_pack(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_pack(root)
            (root / "assets" / "empty").mkdir(parents=True)
            with self.assertRaises(PackError):
                load_pack(root)

    def test_schema_unknown_fields_bools_bad_versions_and_nonempty_routines_fail(self):
        changes = [
            {"raw_sdk": {}},
            {"schema_version": True},
            {"version": "01.2.3"},
            {"min_app_version": "0.1"},
            {"routines": [{"action": "click"}]},
        ]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                self.write_pack(Path(directory), manifest(**change))
                with self.assertRaises(PackError):
                    load_pack(directory)

    def test_version_incompatible_and_bad_provenance_fail(self):
        cases = [
            manifest(min_app_version="0.2.0"),
            manifest(provenance={"source": "http://example.test", "revision": "a" * 40, "license": "MIT", "attribution": "A"}),
        ]
        for payload in cases:
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as directory:
                self.write_pack(Path(directory), payload)
                with self.assertRaises(PackError):
                    load_pack(directory)

    def test_bad_paths_unlisted_files_and_links_fail(self):
        paths = ["/assets/x.png", "assets/../x.png", "assets\\x.png", "https://example.test/x.png", "assets/x.jpg"]
        for path in paths:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payload, files = self.asset_manifest(path=path)
                self.write_pack(root, payload)
                with self.assertRaises(PackError):
                    load_pack(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_pack(root, files={"surprise.txt": b"no"})
            with self.assertRaises(PackError):
                load_pack(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "target"
            self.write_pack(root)
            linked = Path(directory) / "linked"
            linked.symlink_to(root, target_is_directory=True)
            with self.assertRaises(PackError):
                load_pack(linked)

    def test_asset_symlink_and_hardlink_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload, files = self.asset_manifest()
            self.write_pack(root, payload, files)
            (root / "assets/hud.png").unlink()
            (root / "assets/hud.png").symlink_to(root / "pack.json")
            with self.assertRaises(PackError):
                load_pack(root)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            payload, files = self.asset_manifest()
            self.write_pack(root, payload, files)
            (root / "copy.png").hardlink_to(root / "assets/hud.png")
            with self.assertRaises(PackError):
                load_pack(root)

    def test_bad_references_duplicates_bounds_and_numbers_fail(self):
        changes = [
            {"anchors": [{"id": "one", "asset": "missing", "roi": [0, 0, 1, 1], "threshold": 0.1, "scale_range": [1, 1]}]},
            {"anchors": [{"id": "one", "asset": "hud.icon", "roi": [1900, 0, 21, 1], "threshold": 0.1, "scale_range": [1, 1]}]},
            {"anchors": [{"id": "one", "asset": "hud.icon", "roi": [0, 0, 1, 1], "threshold": True, "scale_range": [1, 1]}]},
            {"anchors": [{"id": "one", "asset": "hud.icon", "roi": [0, 0, 1, 1], "threshold": 0.1, "scale_range": [0.2, 1]}]},
            {"states": [{"id": "bad", "positive": ["unknown"], "exclude": [], "stable_frames": 2}]},
            {"states": [{"id": "bad", "positive": ["hud.anchor"], "exclude": ["hud.anchor"], "stable_frames": 2}]},
        ]
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                payload, files = self.asset_manifest()
                payload.update(change)
                self.write_pack(root, payload, files)
                with self.assertRaises(PackError):
                    load_pack(root)


if __name__ == "__main__":
    unittest.main()
