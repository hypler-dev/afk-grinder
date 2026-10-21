"""Synthetic Windows SDK loader-report tests; no Windows APIs are invoked."""

from __future__ import annotations

import ctypes
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afk_grinder.recognition import windows_loader
from afk_grinder.recognition.windows_loader import (
    _MAX_PATH_CHARS,
    _MAX_TOTAL_PATH_CHARS,
    _Kernel32Modules,
    _expected_files,
    _native_module_paths,
    observe_windows_sdk_loads,
    validate_windows_sdk_loads,
)


class _NativeFake:
    def __init__(self, paths: list[str], *, fail: bool = False, overflow: bool = False) -> None:
        self.paths = paths
        self.fail = fail
        self.overflow = overflow

    def current_process(self) -> int:
        if self.fail:
            raise RuntimeError("hidden")
        return 1

    def enum_modules(self, _process: int) -> tuple[int, ...]:
        return tuple(range(4097)) if self.overflow else tuple(range(len(self.paths)))

    def module_path(self, module: int) -> str:
        return self.paths[module]


class _Function:
    def __init__(self, callback):
        self.callback = callback
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        return self.callback(*args)


class _Kernel32Fake:
    def __init__(self, *, needed: int = ctypes.sizeof(ctypes.c_void_p), path_length: int = 1) -> None:
        self.needed = needed
        self.path_length = path_length
        self.GetCurrentProcess = _Function(lambda: 1)

        def enum_modules(_process, handles, _size, needed_pointer):
            ctypes.cast(needed_pointer, ctypes.POINTER(ctypes.c_uint32)).contents.value = self.needed
            if self.needed == ctypes.sizeof(ctypes.c_void_p):
                ctypes.cast(handles, ctypes.POINTER(ctypes.c_void_p))[0] = 7
            return 1

        def module_name(_module, buffer, _size):
            buffer.value = "x"
            return self.path_length

        self.K32EnumProcessModules = _Function(enum_modules)
        self.GetModuleFileNameW = _Function(module_name)


class WindowsLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.bundle = Path(self.temporary.name) / "bundle"
        self.bin = self.bundle / "_internal" / "maa" / "bin"
        self.bin.mkdir(parents=True)
        for name in ("MaaFramework.dll", "MaaUtils.dll", "MaaCustomControlUnit.dll", "onnxruntime.dll"):
            (self.bin / name).write_bytes(name.encode("ascii"))

    def _paths(self) -> list[str]:
        return [str(self.bin / name) for name in ("MaaFramework.dll", "MaaUtils.dll", "MaaCustomControlUnit.dll")]

    def _report(self) -> dict[str, object]:
        return observe_windows_sdk_loads(self.bundle, _module_paths=self._paths())

    def test_valid_partition_and_independent_validation(self) -> None:
        report = self._report()
        self.assertEqual(report["scope"], "synthetic-replacement-worker")
        self.assertEqual([item["path"] for item in report["loaded"]], sorted(item["path"] for item in report["loaded"]))
        self.assertEqual(report["unobserved"], ["_internal/maa/bin/onnxruntime.dll"])
        self.assertEqual(validate_windows_sdk_loads(self.bundle, report), report)

    def test_missing_core_outside_exact_copy_and_duplicate_fail(self) -> None:
        with self.assertRaises(ValueError):
            observe_windows_sdk_loads(self.bundle, _module_paths=self._paths()[1:])
        outside = Path(self.temporary.name) / "outside" / "MaaFramework.dll"
        outside.parent.mkdir()
        outside.write_bytes(b"outside")
        with self.assertRaises(ValueError):
            observe_windows_sdk_loads(self.bundle, _module_paths=[str(outside), *self._paths()[1:]])
        with self.assertRaises(ValueError):
            observe_windows_sdk_loads(self.bundle, _module_paths=[*self._paths(), self._paths()[0]])

    def test_unknown_maa_case_collision_and_link_fail(self) -> None:
        (self.bin / "MaaFuture.dll").write_bytes(b"x")
        with self.assertRaises(ValueError):
            self._report()
        (self.bin / "MaaFuture.dll").unlink()
        entries = list(__import__("os").scandir(self.bin))

        class Duplicate:
            name = "maautils.DLL"

            @staticmethod
            def is_symlink() -> bool:
                return False

        class Entries:
            def __enter__(self):
                return iter([*entries, Duplicate()])

            def __exit__(self, *_args):
                return False

        with patch.object(windows_loader.os, "scandir", return_value=Entries()):
            with self.assertRaises(ValueError):
                _expected_files(self.bundle)
        target = Path(self.temporary.name) / "outside.dll"
        target.write_bytes(b"x")
        (self.bin / "alias.dll").symlink_to(target)
        with self.assertRaises(ValueError):
            self._report()

    def test_hardlinked_sdk_file_fails(self) -> None:
        alias = self.bin / "onnxruntime-copy.dll"
        alias.hardlink_to(self.bin / "onnxruntime.dll")
        with self.assertRaises(ValueError):
            self._report()

    def test_symlinked_sdk_ancestor_fails(self) -> None:
        escaped = Path(self.temporary.name) / "escaped" / "maa" / "bin"
        escaped.mkdir(parents=True)
        for name in ("MaaFramework.dll", "MaaUtils.dll", "MaaCustomControlUnit.dll"):
            (escaped / name).write_bytes(name.encode("ascii"))
        linked = Path(self.temporary.name) / "linked"
        linked.mkdir()
        (linked / "_internal").symlink_to(escaped.parent.parent, target_is_directory=True)
        with self.assertRaises(ValueError):
            observe_windows_sdk_loads(linked, _module_paths=[])

    def test_hash_size_and_current_file_tamper_fail(self) -> None:
        report = self._report()
        forged = {**report, "loaded": [dict(item) for item in report["loaded"]]}
        forged["loaded"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError):
            validate_windows_sdk_loads(self.bundle, forged)
        forged["loaded"][0]["sha256"] = hashlib.sha256((self.bin / "MaaCustomControlUnit.dll").read_bytes()).hexdigest()
        forged["loaded"][0]["size_bytes"] = 0
        with self.assertRaises(ValueError):
            validate_windows_sdk_loads(self.bundle, forged)
        (self.bin / "MaaCustomControlUnit.dll").write_bytes(b"changed")
        with self.assertRaises(ValueError):
            validate_windows_sdk_loads(self.bundle, report)

    def test_malformed_payload_escape_and_case_path_fail(self) -> None:
        report = self._report()
        for payload in (
            {},
            {**report, "schema_version": True},
            {**report, "unobserved": ["/tmp/x"]},
            {**report, "unobserved": ["_internal/maa/bin/../MaaUtils.dll"]},
            {**report, "unobserved": ["_internal/maa/bin/ONNXRUNTIME.dll"]},
            {**report, "unobserved": []},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError):
                    validate_windows_sdk_loads(self.bundle, payload)

    def test_unrelated_module_paths_do_not_require_filesystem_access(self) -> None:
        report = observe_windows_sdk_loads(self.bundle, _module_paths=["C:/missing/unrelated.dll", *self._paths()])
        self.assertEqual(report["unobserved"], ["_internal/maa/bin/onnxruntime.dll"])

    def test_bundle_count_and_size_bounds_fail(self) -> None:
        with patch.object(windows_loader, "_MAX_DLLS", 3):
            with self.assertRaises(ValueError):
                self._report()
        with patch.object(windows_loader, "_MAX_TOTAL_FILE_BYTES", 1):
            with self.assertRaises(ValueError):
                self._report()
        with patch.object(windows_loader, "_MAX_DIRECTORY_ENTRIES", 3):
            with self.assertRaises(ValueError):
                self._report()

    def test_change_during_observation_fails(self) -> None:
        paths = self._paths()

        def changing_paths():
            yield paths[0]
            (self.bin / "onnxruntime.dll").write_bytes(b"mutated")
            yield from paths[1:]

        with self.assertRaises(ValueError):
            observe_windows_sdk_loads(self.bundle, _module_paths=changing_paths())

    def test_path_caps_and_native_api_failure_fakes_fail_closed(self) -> None:
        with self.assertRaises(ValueError):
            observe_windows_sdk_loads(self.bundle, _module_paths=["x" * _MAX_PATH_CHARS])
        with self.assertRaises(ValueError):
            observe_windows_sdk_loads(self.bundle, _module_paths=["x" * 20000] * ((_MAX_TOTAL_PATH_CHARS // 20000) + 1))
        with self.assertRaises(ValueError):
            _native_module_paths(_api=_NativeFake([], fail=True))
        with self.assertRaises(ValueError):
            _native_module_paths(_api=_NativeFake([], overflow=True))
        with self.assertRaises(ValueError):
            _native_module_paths(_api=_NativeFake(["x" * _MAX_PATH_CHARS]))
        if sys.platform != "win32":
            with self.assertRaises(ValueError):
                _native_module_paths()

    def test_kernel32_prototypes_alignment_and_truncation_fail_closed(self) -> None:
        kernel32 = _Kernel32Fake()
        with patch.object(windows_loader.sys, "platform", "win32"), patch.object(windows_loader.ctypes, "WinDLL", return_value=kernel32, create=True):
            api = _Kernel32Modules()
            self.assertEqual(api.current_process(), 1)
            self.assertEqual(api.enum_modules(1), (7,))
            self.assertEqual(api.module_path(7), "x")
        self.assertEqual(kernel32.K32EnumProcessModules.argtypes[0], ctypes.c_void_p)
        self.assertEqual(kernel32.GetModuleFileNameW.argtypes[2], ctypes.c_uint32)
        for fake in (_Kernel32Fake(needed=3), _Kernel32Fake(path_length=_MAX_PATH_CHARS - 1)):
            with patch.object(windows_loader.sys, "platform", "win32"), patch.object(windows_loader.ctypes, "WinDLL", return_value=fake, create=True):
                api = _Kernel32Modules()
                with self.assertRaises(ValueError):
                    _native_module_paths(_api=api)


if __name__ == "__main__":
    unittest.main()
