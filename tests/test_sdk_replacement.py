"""Private SDK rebuild guards use synthetic files and fake subprocesses."""

import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import verify_sdk_replacement as verifier


class SdkReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_target_must_match_native_host_before_rebuild(self):
        for label, system, machine in (("macos-arm64", "darwin", "arm64"),
                                       ("macos-x64", "darwin", "x86_64"),
                                       ("windows-x64", "win32", "AMD64")):
            with self.subTest(label=label), patch.object(verifier.sys, "platform", system), \
                 patch.object(verifier.platform, "machine", return_value=machine):
                verifier.require_host(label)
            with patch.object(verifier.sys, "platform", "linux"), \
                 self.assertRaisesRegex(ValueError, "does not match"):
                verifier.require_host(label)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            verifier.require_host("linux-x64")

    def test_build_configuration_has_no_second_input_controller(self):
        for label in verifier._HOSTS:
            with self.subTest(label=label):
                command = verifier.configure_command("cmake", Path("source"), Path("build"), label)
                self.assertIn("-DWITH_CUSTOM_CONTROLLER=ON", command)
                self.assertIn("-DMAA_HASH_VERSION=5.14.3", command)
                self.assertFalse(any(item.startswith("-DWITH_") and item.endswith("=ON")
                                     and item != "-DWITH_CUSTOM_CONTROLLER=ON" for item in command))
                for name in ("WITH_MAA_AGENT", "WITH_ADB_CONTROLLER", "WITH_MACOS_CONTROLLER", "WITH_WIN32_CONTROLLER"):
                    self.assertIn(f"-D{name}=OFF", command)
                if label == "windows-x64":
                    self.assertEqual(command[command.index("-A") + 1], "x64")
                else:
                    self.assertIn("-DCMAKE_OSX_DEPLOYMENT_TARGET=13.3", command)

    def test_all_bundled_core_copies_are_found_and_conflicts_rejected(self):
        bundle = self.root / "AFKGrinder"
        data = bundle / "_internal"
        native = data / "maa/bin"
        native.mkdir(parents=True)
        for name in verifier._names("windows-x64"):
            (native / name).write_bytes(name.encode())
            (data / name).write_bytes(name.encode())
        paths = verifier._core_paths(bundle, "windows-x64")
        self.assertTrue(all(len(copies) == 2 for copies in paths.values()))
        (data / "MaaUtils.dll").write_bytes(b"different old copy")
        with self.assertRaisesRegex(ValueError, "copies disagree"):
            verifier._core_paths(bundle, "windows-x64")

    def test_escaping_core_alias_cannot_be_replaced(self):
        bundle = self.root / "AFKGrinder.app"
        native = bundle / "Contents/Resources/maa/bin"
        native.mkdir(parents=True)
        sentinel = self.root / "outside.dylib"
        sentinel.write_bytes(b"keep")
        try:
            (native / "libMaaFramework.dylib").symlink_to(sentinel)
        except OSError as error:
            self.skipTest(f"symlink fixture unavailable: {error}")
        with self.assertRaises(ValueError):
            verifier._core_paths(bundle, "macos-arm64")
        self.assertEqual(sentinel.read_bytes(), b"keep")

    def test_source_output_is_unambiguous_and_not_a_link(self):
        build = self.root / "build"
        (build / "bin/Release").mkdir(parents=True)
        for name in verifier._names("windows-x64"):
            (build / "bin/Release" / name).write_bytes(b"library")
        self.assertEqual(set(verifier._source_outputs(build, "windows-x64")), set(verifier._names("windows-x64")))
        (build / "bin/MaaFramework.dll").write_bytes(b"duplicate")
        with self.assertRaisesRegex(ValueError, "unambiguous"):
            verifier._source_outputs(build, "windows-x64")

    def test_native_windows_architecture_cannot_be_faked_by_target_label(self):
        image = self.root / "image.dll"
        payload = bytearray(128)
        payload[:2] = b"MZ"
        struct.pack_into("<I", payload, 0x3C, 64)
        payload[64:68] = b"PE\0\0"
        struct.pack_into("<H", payload, 68, 0x8664)
        image.write_bytes(payload)
        self.assertEqual(verifier._native_architecture(image, "windows-x64"), "AMD64")
        struct.pack_into("<H", payload, 68, 0xAA64)
        image.write_bytes(payload)
        with self.assertRaisesRegex(ValueError, "AMD64"):
            verifier._native_architecture(image, "windows-x64")
        image.write_bytes(b"MZ")
        with self.assertRaisesRegex(ValueError, "PE image"):
            verifier._native_architecture(image, "windows-x64")

    def test_worker_metadata_is_bounded_regular_json(self):
        report = self.root / "report.json"
        for content in ("[]", "x" * 4097):
            report.write_text(content)
            with self.assertRaises(ValueError):
                verifier._read_json(report)
        report.write_text(json.dumps({"ok": True}))
        self.assertEqual(verifier._read_json(report), {"ok": True})

    def test_worker_drops_external_loader_and_python_overrides(self):
        with patch.dict(os.environ, {"DYLD_LIBRARY_PATH": "/other-sdk", "DYLD_INSERT_LIBRARIES": "/inject",
                                     "MAAFW_BINARY_PATH": "/override", "PYTHONPATH": "/module", "PYTHONHOME": "/python",
                                     "PYTHONOPTIMIZE": "1"}, clear=True):
            environment = verifier._worker_environment(self.root, "macos-arm64")
        self.assertEqual(environment, {"DYLD_PRINT_LIBRARIES": "1"})

    def test_frozen_verifier_requires_marker_and_read_only_lifecycle_report(self):
        expected = {"sdk_version": "5.14.3", "native_version": "5.14.3",
                    "source_revision": verifier.MAA_SOURCE_REVISION, "cpu_only": True, "frame_cache_limit": 2,
                    "persistent_images": False, "persistent_logs": False, "native_input": False,
                    "capture_source": "synthetic", "custom_controller": "input callbacks disabled",
                    "cancellation": "passed", "replacement_probe": verifier.REPLACEMENT_PROBE}
        for altered in (None, "native_input", "replacement_probe"):
            with self.subTest(altered=altered):
                work = self.root / (altered or "success")
                work.mkdir()
                report = dict(expected)
                if altered == "native_input":
                    report[altered] = True
                elif altered:
                    del report[altered]

                def worker(command, **options):
                    self.assertIn("--sdk-worker", command)
                    self.assertIn("--sdk-replacement-probe", command)
                    self.assertNotIn("--ui-smoke", command)
                    self.assertEqual(options["timeout"], 30)
                    (work / "sdk-worker.json").write_text(json.dumps({"ok": True, "report": report}))
                    return Mock(stderr="")

                with patch.object(verifier, "_run", side_effect=worker), \
                     patch.object(verifier, "_worker_environment", return_value={}):
                    if altered:
                        with self.assertRaisesRegex(ValueError, "did not pass"):
                            verifier._frozen_probe(self.root / "copy", work, "windows-x64")
                    else:
                        result, loaded = verifier._frozen_probe(self.root / "copy", work, "windows-x64")
                        self.assertEqual(result, expected)
                        self.assertEqual(loaded, [])


if __name__ == "__main__":
    unittest.main()
