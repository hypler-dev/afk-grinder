"""SDK inventory checks use fake bundles and never execute frozen applications."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.inventory_build import inventory, write_inventory


COMMIT = "a" * 40


class InventoryBuildTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.bundle = self.root / "AFKGrinder.app"
        self.executable = self.bundle / "Contents" / "MacOS" / "AFKGrinder"
        self.executable.parent.mkdir(parents=True)
        self.executable.write_bytes(b"\xcf\xfa\xed\xfe" + b"fake frozen executable")
        self.framework = self.bundle / "Contents" / "Frameworks" / "libMaaFramework.5.dylib"
        self.framework.parent.mkdir()
        self.framework.write_bytes(b"framework bytes")
        self.extension = self.framework.parent / "extension.cpython-312-darwin.so"
        self.extension.write_bytes(b"extension bytes")
        self.dll = self.framework.parent / "runtime.dll"
        self.dll.write_bytes(b"dll bytes")
        self.pyd = self.framework.parent / "tagged.cp312-win_amd64.pyd"
        self.pyd.write_bytes(b"pyd bytes")
        self.framework_payload = self.framework.parent / "Tcl.framework" / "Versions" / "A" / "Tcl"
        self.framework_payload.parent.mkdir(parents=True)
        self.framework_payload.write_bytes(b"\xca\xfe\xba\xbf" + b"framework executable")
        self.pe_payload = self.framework.parent / "WindowsRuntime"
        pe_header = bytearray(132)
        pe_header[:2] = b"MZ"
        pe_header[0x3C:0x40] = (128).to_bytes(4, "little")
        pe_header[128:132] = b"PE\0\0"
        self.pe_payload.write_bytes(pe_header)
        self.plaintext = self.framework.parent / "not-a-library"
        self.plaintext.write_text("plain text only", encoding="utf-8")
        legal = self.bundle / "Contents" / "Resources" / "legal"
        legal.mkdir(parents=True)
        (legal / "NOTICE.txt").write_bytes(b"notice bytes")
        self.modules = patch(
            "tools.inventory_build.embedded_module_names",
            return_value={"afk_grinder", "maa", "maa.resource"},
        ).start()
        self.addCleanup(patch.stopall)

    def test_inventory_hashes_relative_sdk_native_and_legal_content(self) -> None:
        alias = self.framework.parent / "libMaaFramework.alias.dylib"
        alias.symlink_to(self.framework.name)
        record = inventory(self.bundle, self.executable, COMMIT, "macos-arm64")

        self.assertEqual(record["source"], {"commit": COMMIT, "label": "macos-arm64"})
        self.assertEqual(record["embedded_modules"], ["afk_grinder", "maa", "maa.resource"])
        native = record["native_files"]
        self.assertEqual(len(native), 7)
        framework_record = next(
            record for record in native
            if "Contents/Frameworks/libMaaFramework.5.dylib" in record["paths"]
        )
        self.assertEqual(
            framework_record["paths"],
            [
                "Contents/Frameworks/libMaaFramework.5.dylib",
                "Contents/Frameworks/libMaaFramework.alias.dylib",
            ],
        )
        self.assertEqual(framework_record["size_bytes"], len(b"framework bytes"))
        self.assertEqual(framework_record["sha256"], hashlib.sha256(b"framework bytes").hexdigest())
        native_paths = {path for record in native for path in record["paths"]}
        self.assertTrue({
            "Contents/Frameworks/extension.cpython-312-darwin.so",
            "Contents/Frameworks/Tcl.framework/Versions/A/Tcl",
            "Contents/Frameworks/WindowsRuntime",
            "Contents/Frameworks/runtime.dll",
            "Contents/Frameworks/tagged.cp312-win_amd64.pyd",
            "Contents/MacOS/AFKGrinder",
        }.issubset(native_paths))
        self.assertNotIn("Contents/Frameworks/not-a-library", native_paths)
        self.assertEqual(record["executable"]["path"], "Contents/MacOS/AFKGrinder")
        self.assertTrue(record["executable"]["native"])
        self.assertEqual(
            record["executable"]["sha256"],
            hashlib.sha256(self.executable.read_bytes()).hexdigest(),
        )
        self.assertIn("not operating-system validation", record["evidence_scope"])
        self.assertEqual(
            record["legal_files"],
            [{"path": "Contents/Resources/legal/NOTICE.txt", "sha256": hashlib.sha256(b"notice bytes").hexdigest()}],
        )
        serialized = json.dumps(record)
        self.assertNotIn(str(self.root), serialized)
        self.assertFalse(record["sdk_presence"]["maaagentbinary_present"])

    def test_missing_sdk_and_agent_namespace_are_rejected(self) -> None:
        self.modules.return_value = {"afk_grinder"}
        with self.assertRaisesRegex(ValueError, "requires embedded maa"):
            inventory(self.bundle, self.executable, COMMIT, "macos-arm64")
        self.modules.return_value = {"maa", "MaaAgentBinary.runner"}
        with self.assertRaisesRegex(ValueError, "MaaAgentBinary"):
            inventory(self.bundle, self.executable, COMMIT, "macos-arm64")

    def test_agent_path_and_escaping_symlink_are_rejected(self) -> None:
        agent = self.bundle / "Contents" / "MaaAgentBinary"
        agent.mkdir()
        with self.assertRaisesRegex(ValueError, "MaaAgentBinary"):
            inventory(self.bundle, self.executable, COMMIT, "macos-arm64")
        agent.rmdir()
        agent_library = self.framework.parent / "MaaAgentBinary.dll"
        agent_library.write_bytes(b"forbidden")
        with self.assertRaisesRegex(ValueError, "MaaAgentBinary"):
            inventory(self.bundle, self.executable, COMMIT, "macos-arm64")
        agent_library.unlink()
        outside = self.root / "outside.dylib"
        outside.write_bytes(b"outside")
        (self.framework.parent / "escape.dylib").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "outside"):
            inventory(self.bundle, self.executable, COMMIT, "macos-arm64")

    def test_symlink_loops_are_rejected_without_host_traceback(self) -> None:
        self_link = self.framework.parent / "self-link"
        self_link.symlink_to(self_link.name)
        with self.assertRaisesRegex(ValueError, "symlink loop"):
            inventory(self.bundle, self.executable, COMMIT, "macos-arm64")
        self_link.unlink()
        directory_loop = self.framework.parent / "directory-loop"
        directory_loop.symlink_to(".")
        with self.assertRaisesRegex(ValueError, "symlink directory cycle"):
            inventory(self.bundle, self.executable, COMMIT, "macos-arm64")

    def test_invalid_source_fields_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "label"):
            inventory(self.bundle, self.executable, COMMIT, "linux-x64")
        with self.assertRaisesRegex(ValueError, "commit"):
            inventory(self.bundle, self.executable, "short", "macos-arm64")

    def test_write_inventory_is_json_and_atomic_result(self) -> None:
        output = self.root / "build-evidence" / "sdk-inventory.json"
        record = inventory(self.bundle, self.executable, COMMIT, "macos-arm64")
        write_inventory(output, record)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8")), record)
        self.assertEqual(list(output.parent.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
