"""Synthetic tests for private MaaFramework native-bundle boundaries."""

from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.sdk_bundle import select_recognition_binaries, validate_recognition_bundle


class RecognitionSelectorTests(unittest.TestCase):
    def _entries(self, system: str) -> list[tuple[str, str]]:
        suffix = ".dll" if system == "win32" else ".dylib"
        prefix = "" if system == "win32" else "lib"
        names = [
            f"{prefix}MaaFramework{suffix}",
            f"{prefix}MaaUtils{suffix}",
            f"{prefix}MaaCustomControlUnit{suffix}",
            f"libopencv_world4.4.12.0{suffix}" if system == "darwin" else "opencv_world4120.dll",
            f"libonnxruntime{suffix}" if system == "darwin" else "onnxruntime.dll",
            f"{prefix}MaaAgentClient{suffix}",
            f"{prefix}MaaToolkit{suffix}",
            f"{prefix}MaaFramework{suffix}",
        ]
        return [(f"/wheel/maa/bin/{name}", "maa/bin") for name in names]

    def test_keeps_required_and_transitive_dependencies_deterministically(self) -> None:
        for system in ("win32", "darwin"):
            with self.subTest(system=system):
                entries = self._entries(system)
                entries.pop()
                selected = select_recognition_binaries(reversed(entries), system)
                names = [Path(source).name for source, _destination in selected]
                self.assertEqual(names, sorted(names))
                self.assertIn("onnxruntime.dll" if system == "win32" else "libonnxruntime.dylib", names)
                self.assertNotIn("MaaAgentClient.dll" if system == "win32" else "libMaaAgentClient.dylib", names)
                self.assertNotIn("MaaToolkit.dll" if system == "win32" else "libMaaToolkit.dylib", names)

    def test_drops_plugins_and_rejects_missing_unknown_or_unsafe_entries(self) -> None:
        entries = self._entries("win32")
        entries.pop()
        entries.append(("/wheel/maa/bin/plugins/Demo.dll", "maa/bin/plugins"))
        selected = select_recognition_binaries(entries, "win32")
        self.assertFalse(any("plugins" in source for source, _destination in selected))
        with self.assertRaisesRegex(ValueError, "missing required"):
            select_recognition_binaries(entries[1:], "win32")
        with self.assertRaisesRegex(ValueError, "repeated required"):
            select_recognition_binaries(entries[:3] + [entries[0]], "win32")
        with self.assertRaisesRegex(ValueError, "Unknown"):
            select_recognition_binaries(entries[:3] + [("/wheel/maa/bin/MaaFuture.dll", "maa/bin")], "win32")
        with self.assertRaisesRegex(ValueError, "traversal"):
            select_recognition_binaries(entries[:3] + [("/wheel/maa/bin/../MaaFramework.dll", "maa/bin")], "win32")
        with self.assertRaisesRegex(ValueError, "destination"):
            select_recognition_binaries(entries[:3] + [("/wheel/maa/bin/onnxruntime.dll", "maa/BIN")], "win32")
        with self.assertRaisesRegex(ValueError, "case-variant"):
            select_recognition_binaries(entries[:3] + [("/wheel/Maa/bin/onnxruntime.dll", "maa/bin")], "win32")
        with self.assertRaisesRegex(ValueError, "plugin destination"):
            select_recognition_binaries(entries[:3] + [("/wheel/maa/bin/plugins/Demo.dll", "maa/bin")], "win32")
        with self.assertRaisesRegex(ValueError, "unsupported native suffix"):
            select_recognition_binaries(entries[:3] + [("/wheel/maa/bin/payload.py", "maa/bin")], "win32")
        with self.assertRaisesRegex(ValueError, "path-like strings"):
            select_recognition_binaries(entries[:3] + [(object(), "maa/bin")], "win32")
        with self.assertRaisesRegex(ValueError, "tuple"):
            select_recognition_binaries(["bad"], "win32")


class RecognitionBundleValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.bundle = Path(self.temporary.name) / "AFKGrinder"
        self.native = self.bundle / "_internal" / "maa" / "bin"
        self.native.mkdir(parents=True)
        (self.bundle / "AFKGrinder.exe").write_bytes(b"executable")
        (self.bundle / "_internal" / "Python.so").write_bytes(b"extension")
        web = self.bundle / "_internal" / "afk_grinder" / "web"
        web.mkdir(parents=True)
        (web / "app.js").write_text("console.log('fixture');")
        (web / "cover.png").write_bytes(b"png")
        models = self.bundle / "_internal" / "afk_grinder" / "ocr_models"
        models.mkdir(parents=True)
        (models / "popup.onnx").write_bytes(b"onnx")
        legal = self.bundle / "legal"
        legal.mkdir()
        (legal / "LICENSE").write_text("fixture license")
        (legal / "MaaFramework-LGPL-3.0.md").write_text("LGPL notice")
        licenses = self.bundle / "licenses"
        licenses.mkdir()
        (licenses / "provenance.json").write_text("{}")

    def _required(self, system: str = "win32") -> None:
        names = (
            ("MaaFramework.dll", "MaaUtils.dll", "MaaCustomControlUnit.dll")
            if system == "win32"
            else ("libMaaFramework.dylib", "libMaaUtils.dylib", "libMaaCustomControlUnit.dylib")
        )
        for name in names:
            (self.native / name).write_bytes(name.encode())

    def test_allows_windows_required_groups(self) -> None:
        self._required()
        validate_recognition_bundle(self.bundle, "win32")

    @unittest.skipIf(sys.platform == "win32", "Windows runners may not permit symlink fixtures")
    def test_allows_required_groups_and_internal_aliases(self) -> None:
        self._required()
        aliases = self.bundle / "aliases"
        aliases.mkdir()
        (aliases / "MaaFramework.dll").symlink_to(self.native / "MaaFramework.dll")
        validate_recognition_bundle(self.bundle, "win32")

    def test_allows_macos_required_groups(self) -> None:
        self._required("darwin")
        validate_recognition_bundle(self.bundle, "darwin")

    def test_rejects_missing_unknown_forbidden_agent_plugin_and_escape(self) -> None:
        self._required()
        (self.native / "MaaUtils.dll").unlink()
        with self.assertRaisesRegex(ValueError, "missing required"):
            validate_recognition_bundle(self.bundle, "win32")
        self._required()
        (self.bundle / "MaaFuture.dll").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "Unknown"):
            validate_recognition_bundle(self.bundle, "win32")
        (self.bundle / "MaaFuture.dll").unlink()
        (self.native / "MaaAgentServer.dll").write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "Forbidden"):
            validate_recognition_bundle(self.bundle, "win32")
        (self.native / "MaaAgentServer.dll").unlink()
        plugin = self.native / "plugins"
        plugin.mkdir()
        with self.assertRaisesRegex(ValueError, "plugins"):
            validate_recognition_bundle(self.bundle, "win32")
        plugin.rmdir()
        agent = self.bundle / "MaaAgentBinary"
        agent.mkdir()
        with self.assertRaisesRegex(ValueError, "MaaAgentBinary"):
            validate_recognition_bundle(self.bundle, "win32")
        agent.rmdir()
    @unittest.skipIf(sys.platform == "win32", "Windows runners may not permit symlink fixtures")
    def test_rejects_external_alias(self) -> None:
        self._required()
        outside = self.bundle.parent / "outside.dll"
        outside.write_bytes(b"x")
        (self.native / "alias.dll").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "escapes"):
            validate_recognition_bundle(self.bundle, "win32")

    def test_rejects_raw_unknown_name_and_keeps_legal_maadeps_documents(self) -> None:
        self._required()
        legal = self.bundle / "legal"
        (legal / "MaaDeps-licenses.txt").write_text("notice")
        validate_recognition_bundle(self.bundle, "win32")
        (legal / "MaaToolkit.dll").write_bytes(b"forbidden")
        with self.assertRaisesRegex(ValueError, "Forbidden"):
            validate_recognition_bundle(self.bundle, "win32")
        (legal / "MaaToolkit.dll").unlink()
        (legal / "MaaDeps-evil.dll").write_bytes(b"forbidden")
        with self.assertRaisesRegex(ValueError, "Unknown"):
            validate_recognition_bundle(self.bundle, "win32")
        (legal / "MaaDeps-evil.dll").unlink()
        raw = self.bundle / "_internal" / "MaaFramework.dll.backup"
        raw.write_bytes(b"x")
        with self.assertRaisesRegex(ValueError, "Unknown"):
            validate_recognition_bundle(self.bundle, "win32")

    @unittest.skipIf(sys.platform == "win32", "Windows runners may not permit symlink fixtures")
    def test_rejects_logical_alias_names_and_broken_or_cyclic_aliases(self) -> None:
        self._required()
        aliases = self.bundle / "aliases"
        aliases.mkdir()
        core = self.native / "MaaFramework.dll"
        (aliases / "MaaFuture.dll").symlink_to(core)
        with self.assertRaisesRegex(ValueError, "Unknown"):
            validate_recognition_bundle(self.bundle, "win32")
        (aliases / "MaaFuture.dll").unlink()
        (aliases / "MaaToolkit.dll").symlink_to(core)
        with self.assertRaisesRegex(ValueError, "Forbidden"):
            validate_recognition_bundle(self.bundle, "win32")
        (aliases / "MaaToolkit.dll").unlink()
        legal_alias = self.bundle / "legal" / "MaaDeps-notice.txt"
        (aliases / "MaaToolkit.dll").symlink_to(core)
        legal_alias.symlink_to(aliases / "MaaToolkit.dll")
        with self.assertRaisesRegex(ValueError, "Forbidden"):
            validate_recognition_bundle(self.bundle, "win32")
        legal_alias.unlink()
        (aliases / "MaaToolkit.dll").unlink()
        (aliases / "broken.dll").symlink_to("missing.dll")
        with self.assertRaisesRegex(ValueError, "broken symlink"):
            validate_recognition_bundle(self.bundle, "win32")
        (aliases / "broken.dll").unlink()
        (aliases / "cycle.dll").symlink_to("cycle.dll")
        with self.assertRaisesRegex(ValueError, "symlink loop"):
            validate_recognition_bundle(self.bundle, "win32")

    @unittest.skipIf(sys.platform == "win32", "Windows runners may not permit symlink fixtures")
    def test_rejects_directory_aliases_to_forbidden_namespaces(self) -> None:
        self._required()
        aliases = self.bundle / "aliases"
        aliases.mkdir()
        hidden_agent = self.bundle / "hidden" / "MaaAgentBinary"
        hidden_agent.mkdir(parents=True)
        (aliases / "agent").symlink_to(hidden_agent, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "MaaAgentBinary"):
            validate_recognition_bundle(self.bundle, "win32")
        (aliases / "agent").unlink()
        hidden_agent.rmdir()
        hidden_plugins = self.bundle / "hidden" / "maa" / "bin" / "plugins"
        hidden_plugins.mkdir(parents=True)
        (aliases / "plugins").symlink_to(hidden_plugins, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "plugins"):
            validate_recognition_bundle(self.bundle, "win32")


if __name__ == "__main__":
    unittest.main()
