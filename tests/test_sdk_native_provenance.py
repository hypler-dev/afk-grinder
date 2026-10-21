"""Synthetic, data-only tests for direct SDK native provenance auditing."""

from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import sdk_native_provenance


COMMIT = "a" * 40


class SdkNativeProvenanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "repo"
        (self.root / "tools").mkdir(parents=True)
        (self.root / "licenses").mkdir()
        self.sources = Path(self.temporary.name) / "sources"
        (self.sources / "archives").mkdir(parents=True)
        self.notice = b"fixture notice\n"
        (self.root / "licenses" / "notice.txt").write_bytes(self.notice)
        self.notice_hash = hashlib.sha256(self.notice).hexdigest()
        self._write_sources()
        self._write_build_dependencies()
        self._write_mapping()
        (self.root / "licenses" / "provenance.json").write_text(json.dumps({
            "notice_inventory_only": True,
            "files": [{"file": "notice.txt", "sha256": self.notice_hash}],
        }), encoding="utf-8")

    def _write_sources(self) -> None:
        template = json.loads((Path(__file__).resolve().parents[1] / "tools" / "sdk_sources.json").read_text())
        for component in template["components"]:
            archive = self.sources / "archives" / f"{component['name']}-{component['commit']}.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                root = component["archive_root"]
                directory = tarfile.TarInfo(f"{root}/")
                directory.type = tarfile.DIRTYPE
                output.addfile(directory)
                payload = f"recipe:{component['name']}\n".encode()
                recipe = tarfile.TarInfo(f"{root}/recipe.txt")
                recipe.size = len(payload)
                output.addfile(recipe, io.BytesIO(payload))
            raw = archive.read_bytes()
            component["size"] = len(raw)
            component["sha256"] = hashlib.sha256(raw).hexdigest()
        self.source_raw = template
        self.source_bytes = json.dumps(template, sort_keys=True, separators=(",", ":")).encode()
        (self.root / "tools" / "sdk_sources.json").write_bytes(self.source_bytes)

    def _write_build_dependencies(self) -> None:
        raw = json.loads((Path(__file__).resolve().parents[1] / "tools" / "sdk_build_dependencies.json").read_text())
        self.build_bytes = json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()
        (self.root / "tools" / "sdk_build_dependencies.json").write_bytes(self.build_bytes)

    def _mapping_record(self, label: str) -> dict[str, object]:
        path = "_internal/maa/bin/MaaCore.dll" if label == "windows-x64" else "Contents/Frameworks/maa/bin/libMaaCore.dylib"
        return {"component": "core", "paths": [path], "sha256": hashlib.sha256(b"native").hexdigest(), "size_bytes": 6}

    def _write_mapping(self) -> None:
        recipe_hash = hashlib.sha256(b"recipe:MaaFramework\n").hexdigest()
        raw = {
            "schema_version": 1,
            "scope": "direct-sdk-native-notice-traceability",
            "sdk_version": "5.14.3",
            "reference_inventory_commit": COMMIT,
            "source_manifest_sha256": hashlib.sha256(self.source_bytes).hexdigest(),
            "build_dependency_manifest_sha256": hashlib.sha256(self.build_bytes).hexdigest(),
            "components": {
                "core": {
                    "source_component": "MaaFramework",
                    "source_evidence": "pinned-source-archive",
                    "identity": "fixture Maa core",
                    "recipes": [{"path": "recipe.txt", "sha256": recipe_hash}],
                    "notices": ["notice.txt"],
                    "limitations": ["fixture only"],
                }
            },
            "targets": {label: [self._mapping_record(label)] for label in sdk_native_provenance.LABELS},
        }
        self.mapping = raw
        (self.root / "tools" / "sdk_native_provenance.json").write_text(json.dumps(raw), encoding="utf-8")

    def _inventory(self, label: str) -> dict[str, object]:
        record = self._mapping_record(label)
        native_record = {key: value for key, value in record.items() if key != "component"}
        notices = (
            [{"path": "_internal/legal/licenses/notice.txt", "sha256": self.notice_hash}]
            if label == "windows-x64"
            else [
                {"path": "Contents/Frameworks/legal/licenses/notice.txt", "sha256": self.notice_hash},
                {"path": "Contents/Resources/legal/licenses/notice.txt", "sha256": self.notice_hash},
            ]
        )
        return {
            "schema_version": "sdk-inventory.v2",
            "source": {"commit": COMMIT, "label": label},
            "evidence_scope": "fixture",
            "executable": {"path": "AFKGrinder", "sha256": "b" * 64, "size_bytes": 1, "native": True},
            "embedded_modules": ["maa"],
            "native_files": [native_record, {"paths": ["baseline/runtime.dll"], "sha256": "c" * 64, "size_bytes": 1}],
            "legal_files": notices,
            "sdk_presence": {"required": True, "maa_modules": ["maa"], "maaframework_native_paths": [record["paths"][0]], "maaagentbinary_present": False},
        }

    def _write_inventory(self, label: str, raw: dict[str, object] | None = None) -> Path:
        path = Path(self.temporary.name) / f"{label}.json"
        path.write_text(json.dumps(self._inventory(label) if raw is None else raw), encoding="utf-8")
        return path

    def _audit(self, label: str, raw: dict[str, object] | None = None) -> dict[str, object]:
        return sdk_native_provenance.audit(self._write_inventory(label, raw), self.sources, label, COMMIT, repo=self.root)

    def test_valid_all_targets_records_closed_gate_and_exclusive_output(self) -> None:
        for label in sdk_native_provenance.LABELS:
            with self.subTest(label=label):
                report = self._audit(label)
                self.assertEqual(len(report["matched_native_groups"]), 1)
                self.assertEqual(report["baseline_excluded_native_group_count"], 1)
                self.assertEqual(report["sdk_publication_gate"], "closed")
                self.assertFalse(report["source_coverage_complete"])
                self.assertFalse(report["vendor_archives_verified"])
        output = Path(self.temporary.name) / "report.json"
        sdk_native_provenance._write_new(output, self._audit("windows-x64"))
        with self.assertRaisesRegex(ValueError, "already exists"):
            sdk_native_provenance._write_new(output, self._audit("windows-x64"))

    def test_historical_mapping_reference_does_not_replace_current_inventory_commit(self) -> None:
        historical = "d" * 40
        altered = copy.deepcopy(self.mapping)
        altered["reference_inventory_commit"] = historical
        (self.root / "tools" / "sdk_native_provenance.json").write_text(json.dumps(altered), encoding="utf-8")
        report = self._audit("windows-x64")
        self.assertEqual(report["commit"], COMMIT)
        self.assertEqual(report["reference_inventory_commit"], historical)
        stale_inventory = self._inventory("windows-x64")
        stale_inventory["source"]["commit"] = historical
        with self.assertRaisesRegex(ValueError, "label or commit"):
            self._audit("windows-x64", stale_inventory)

    def test_reference_inventory_commit_may_equal_current_inventory_commit(self) -> None:
        report = self._audit("windows-x64")
        self.assertEqual(report["reference_inventory_commit"], COMMIT)
        self.assertEqual(report["commit"], COMMIT)

    def test_project_mapping_declares_current_complete_group_counts(self) -> None:
        """Keep the accepted 25-group mapping visible in a focused regression."""
        raw = json.loads((Path(__file__).resolve().parents[1] / "tools" / "sdk_native_provenance.json").read_text())
        self.assertEqual({label: len(raw["targets"][label]) for label in sdk_native_provenance.LABELS}, {
            "macos-arm64": 7,
            "macos-x64": 7,
            "windows-x64": 11,
        })
        self.assertEqual(len(raw["components"]), 11)
        self.assertEqual(sum(len(entry["paths"]) for rows in raw["targets"].values() for entry in rows), 59)

    def test_rejects_unknown_missing_partial_alias_hash_and_size_groups(self) -> None:
        cases: list[tuple[str, dict[str, object]]] = []
        unknown = self._inventory("windows-x64")
        unknown["native_files"].append({"paths": ["_internal/maa/bin/MaaUnknown.dll"], "sha256": "d" * 64, "size_bytes": 1})
        cases.append(("cover", unknown))
        missing = self._inventory("windows-x64")
        missing["native_files"] = missing["native_files"][1:]
        cases.append(("no direct", missing))
        partial = self._inventory("windows-x64")
        partial["native_files"][0]["paths"].append("_internal/alias/MaaCore.dll")
        partial["native_files"][0]["paths"].sort()
        cases.append(("cover", partial))
        case_altered = self._inventory("windows-x64")
        case_altered["native_files"][0]["paths"] = ["aliases/libmaacore.dll"]
        cases.append(("cover", case_altered))
        altered_hash = self._inventory("windows-x64")
        altered_hash["native_files"][0]["sha256"] = "d" * 64
        cases.append(("hash or size", altered_hash))
        altered_size = self._inventory("windows-x64")
        altered_size["native_files"][0]["size_bytes"] = 7
        cases.append(("hash or size", altered_size))
        for expected, raw in cases:
            with self.subTest(expected=expected):
                with self.assertRaisesRegex(ValueError, expected):
                    self._audit("windows-x64", raw)

    def test_rejects_source_archive_and_recipe_tampering(self) -> None:
        component = self.source_raw["components"][0]
        archive = self.sources / "archives" / f"{component['name']}-{component['commit']}.tar.gz"
        original = archive.read_bytes()
        archive.write_bytes(original + b"tamper")
        with self.assertRaisesRegex(ValueError, "size did not match"):
            self._audit("windows-x64")
        archive.write_bytes(original)
        altered = copy.deepcopy(self.mapping)
        altered["components"]["core"]["recipes"][0]["sha256"] = "0" * 64
        (self.root / "tools" / "sdk_native_provenance.json").write_text(json.dumps(altered), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "recipe SHA-256"):
            self._audit("windows-x64")

    def test_rejects_notice_bytes_missing_bundled_notice_and_manifest_pin_mismatch(self) -> None:
        (self.root / "licenses" / "notice.txt").write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "Retained notice SHA-256"):
            self._audit("windows-x64")
        (self.root / "licenses" / "notice.txt").write_bytes(self.notice)
        missing = self._inventory("windows-x64")
        missing["legal_files"] = []
        with self.assertRaisesRegex(ValueError, "bundled notice"):
            self._audit("windows-x64", missing)
        altered = copy.deepcopy(self.mapping)
        altered["source_manifest_sha256"] = "0" * 64
        (self.root / "tools" / "sdk_native_provenance.json").write_text(json.dumps(altered), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source manifest SHA-256"):
            self._audit("windows-x64")

    def test_rejects_strict_json_unsafe_paths_links_and_count_bounds(self) -> None:
        inventory = self._write_inventory("windows-x64")
        inventory.write_text('{"schema_version":"sdk-inventory.v2","schema_version":"sdk-inventory.v2"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "strict JSON"):
            sdk_native_provenance.audit(inventory, self.sources, "windows-x64", COMMIT, repo=self.root)
        unsafe = copy.deepcopy(self.mapping)
        unsafe["targets"]["windows-x64"][0]["paths"] = ["../MaaCore.dll"]
        (self.root / "tools" / "sdk_native_provenance.json").write_text(json.dumps(unsafe), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unsafe"):
            self._audit("windows-x64")
        self._write_mapping()
        excessive = self._inventory("windows-x64")
        excessive["native_files"].extend(
            {"paths": [f"baseline/{index}.dll"], "sha256": f"{index:064x}", "size_bytes": 1}
            for index in range(sdk_native_provenance.MAX_NATIVE_GROUPS)
        )
        with self.assertRaisesRegex(ValueError, "native groups"):
            self._audit("windows-x64", excessive)
        link = Path(self.temporary.name) / "inventory-link.json"
        try:
            link.symlink_to(self._write_inventory("windows-x64"))
        except OSError as error:
            self.skipTest(f"symlink fixture unavailable: {error}")
        with self.assertRaisesRegex(ValueError, "non-linked regular"):
            sdk_native_provenance.audit(link, self.sources, "windows-x64", COMMIT, repo=self.root)


if __name__ == "__main__":
    unittest.main()
