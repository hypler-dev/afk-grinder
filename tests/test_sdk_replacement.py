"""Private SDK rebuild guards use synthetic files and fake subprocesses."""

import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from afk_grinder.recognition.windows_loader import observe_windows_sdk_loads
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
        for content in ("[]", "x" * 4097, '{"same": 1, "same": 2}',
                        '{"value": NaN}', '{"value": Infinity}', '{"value": -Infinity}',
                        '{"value": 1e999}', '{"value": -1e999}'):
            report.write_text(content)
            with self.assertRaises(ValueError):
                verifier._read_json(report)
        for limit in (4096, 65_536):
            content = json.dumps({"padding": "x" * (limit - len('{"padding": ""}'))})
            self.assertEqual(len(content.encode("utf-8")), limit)
            report.write_text(content)
            self.assertEqual(verifier._read_json(report, limit=limit), json.loads(content))
            report.write_text(content + "x")
            with self.assertRaises(ValueError):
                verifier._read_json(report, limit=limit)

    def test_worker_drops_external_loader_and_python_overrides(self):
        with patch.dict(os.environ, {"DYLD_LIBRARY_PATH": "/other-sdk", "DYLD_INSERT_LIBRARIES": "/inject",
                                     "MAAFW_BINARY_PATH": "/override", "PYTHONPATH": "/module", "PYTHONHOME": "/python",
                                     "PYTHONOPTIMIZE": "1"}, clear=True):
            environment = verifier._worker_environment(self.root, "macos-arm64")
        self.assertEqual(environment, {"DYLD_PRINT_LIBRARIES": "1"})

    def _lifecycle_report(self):
        return {"sdk_version": verifier.PINNED_MAA_VERSION, "native_version": verifier.PINNED_MAA_VERSION,
                "source_revision": verifier.MAA_SOURCE_REVISION, "cpu_only": True,
                "frame_cache_limit": verifier.FRAME_CACHE_LIMIT, "persistent_images": False,
                "persistent_logs": False, "native_input": False, "capture_source": "synthetic",
                "custom_controller": "input callbacks disabled", "cancellation": "passed",
                "replacement_probe": verifier.REPLACEMENT_PROBE, "synthetic_template_match": "passed"}

    def _windows_loader_fixture(self):
        copy = self.root / "windows-copy"
        directory = copy / "_internal/maa/bin"
        directory.mkdir(parents=True)
        names = (*verifier._names("windows-x64"), "onnxruntime.dll")
        for name in names:
            (directory / name).write_bytes(name.encode("ascii"))
        module_paths = [str(directory / name) for name in verifier._names("windows-x64")]
        return copy, observe_windows_sdk_loads(copy, _module_paths=module_paths)

    def _mac_loader_fixture(self):
        copy = self.root / "mac-copy"
        directory = copy / "Contents/Resources/maa/bin"
        directory.mkdir(parents=True)
        names = (*verifier._names("macos-arm64"), "libfastdeploy.dylib", "libonnxruntime.dylib",
                 "libopencv_core.dylib", "libwebgpu_dawn.dylib")
        paths = []
        for name in names:
            path = directory / name
            path.write_bytes(name.encode("ascii"))
            paths.append(path)
        return copy, paths

    def _frozen_worker(self, work, payload, *, stderr="", returncode=0):
        def worker(command, **options):
            self.assertIn("--sdk-worker", command)
            self.assertIn("--sdk-replacement-probe", command)
            self.assertNotIn("--ui-smoke", command)
            self.assertEqual(options["timeout"], 30)
            report_path = Path(command[command.index("--sdk-report") + 1])
            self.assertEqual(report_path, work / "sdk-worker.json")
            report_path.write_text(json.dumps(payload))
            return Mock(returncode=returncode, stderr=stderr)
        return worker

    def test_frozen_windows_verifier_requires_loader_and_strict_lifecycle_report(self):
        copy, loader = self._windows_loader_fixture()
        expected = self._lifecycle_report()
        expected["windows_sdk_loads"] = loader
        for index, altered in enumerate((
                {"synthetic_template_match": "failed"},
                {"cpu_only": 1},
                {"frame_cache_limit": True},
                {"unexpected": "field"},
                {"windows_sdk_loads": None},
                {"windows_sdk_loads": {**loader, "loaded": [{**loader["loaded"][0], "sha256": "0" * 64}, *loader["loaded"][1:]]}},
        )):
            with self.subTest(altered=altered):
                work = self.root / f"windows-{index}"
                work.mkdir()
                report = dict(expected)
                report.update(altered)
                payload = {"ok": True, "report": report}
                with patch.object(verifier, "_run", side_effect=self._frozen_worker(work, payload)), \
                     patch.object(verifier, "_worker_environment", return_value={}):
                    with self.assertRaises(ValueError):
                        verifier._frozen_probe(copy, work, "windows-x64")

        for index, payload in enumerate((
                {"ok": True, "report": expected, "extra": None},
                {"ok": 1, "report": expected},
                {"ok": True},
        )):
            with self.subTest(envelope=payload):
                work = self.root / f"envelope-{index}"
                work.mkdir()
                with patch.object(verifier, "_run", side_effect=self._frozen_worker(work, payload)), \
                     patch.object(verifier, "_worker_environment", return_value={}):
                    with self.assertRaises(ValueError):
                        verifier._frozen_probe(copy, work, "windows-x64")

    def test_frozen_windows_verifier_requires_zero_worker_exit(self):
        copy, loader = self._windows_loader_fixture()
        report = self._lifecycle_report()
        report["windows_sdk_loads"] = loader
        work = self.root / "nonzero"
        work.mkdir()
        with patch.object(verifier, "_run", side_effect=self._frozen_worker(
                work, {"ok": True, "report": report}, returncode=1)), \
             patch.object(verifier, "_worker_environment", return_value={}):
            with self.assertRaisesRegex(ValueError, "did not exit successfully"):
                verifier._frozen_probe(copy, work, "windows-x64")

    def test_frozen_macos_verifier_requires_seven_private_dyld_libraries(self):
        copy, paths = self._mac_loader_fixture()
        expected = self._lifecycle_report()
        stderr = "\n".join(f"dyld: loaded {path}" for path in paths)
        work = self.root / "mac-success"
        work.mkdir()
        with patch.object(verifier, "_run", side_effect=self._frozen_worker(
                work, {"ok": True, "report": expected}, stderr=stderr)), \
             patch.object(verifier, "_worker_environment", return_value={}):
            result, loaded = verifier._frozen_probe(copy, work, "macos-arm64")
        self.assertEqual(result, expected)
        self.assertNotIn("windows_sdk_loads", result)
        self.assertEqual(loaded, sorted(path.relative_to(copy).as_posix() for path in paths))

        outside = self.root / "outside" / "libMaaFramework.dylib"
        outside.parent.mkdir()
        outside.write_bytes(b"outside")
        for label, trace in (
                ("missing", "\n".join(f"dyld: loaded {path}" for path in paths[:-1])),
                ("outside", f"dyld: loaded {outside}"),
        ):
            with self.subTest(label=label):
                work = self.root / f"mac-{label}"
                work.mkdir()
                with patch.object(verifier, "_run", side_effect=self._frozen_worker(
                        work, {"ok": True, "report": expected}, stderr=trace)), \
                     patch.object(verifier, "_worker_environment", return_value={}):
                    with self.assertRaises(ValueError):
                        verifier._frozen_probe(copy, work, "macos-arm64")


if __name__ == "__main__":
    unittest.main()
