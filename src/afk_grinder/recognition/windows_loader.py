"""Bounded, self-only Windows loader observation for the private SDK probe."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import hashlib
import ntpath
import os
from pathlib import Path
import stat
import sys
from typing import Iterable, Sequence


_MAX_MODULES = 4096
_MAX_PATH_CHARS = 32768
_MAX_TOTAL_PATH_CHARS = 1024 * 1024
_MAX_DLLS = 64
_MAX_DIRECTORY_ENTRIES = 1024
_MAX_FILE_BYTES = 128 * 1024 * 1024
_MAX_TOTAL_FILE_BYTES = 512 * 1024 * 1024
_SDK_DIRECTORY = Path("_internal") / "maa" / "bin"
_CORE_NAMES = ("MaaFramework.dll", "MaaUtils.dll", "MaaCustomControlUnit.dll")
_SCOPE = "synthetic-replacement-worker"


@dataclass(frozen=True)
class _FileRecord:
    path: Path
    relative: str
    name: str
    identity: tuple[int, int, int, int]
    size: int
    sha256: str


class _LoaderFailure(Exception):
    pass


def _invalid_bundle() -> ValueError:
    return ValueError("Windows SDK bundle is invalid.")


def _invalid_observation() -> ValueError:
    return ValueError("Windows SDK loader observation is invalid.")


def _invalid_payload() -> ValueError:
    return ValueError("Windows SDK loader payload is invalid.")


def _identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _hash_regular_file(path: Path, expected_size: int) -> str:
    digest = hashlib.sha256()
    total = 0
    try:
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_FILE_BYTES:
                    raise _LoaderFailure
                digest.update(chunk)
    except (OSError, _LoaderFailure):
        raise _invalid_bundle() from None
    if total != expected_size:
        raise _invalid_bundle()
    return digest.hexdigest()


def _record_file(path: Path, relative: str) -> _FileRecord:
    def metadata() -> os.stat_result:
        try:
            link_info = path.lstat()
            info = path.stat()
        except OSError:
            raise _invalid_bundle() from None
        if stat.S_ISLNK(link_info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise _invalid_bundle()
        if info.st_nlink != 1 or info.st_size < 0 or info.st_size > _MAX_FILE_BYTES:
            raise _invalid_bundle()
        return info

    info = metadata()
    digest = _hash_regular_file(path, info.st_size)
    if _identity(metadata()) != _identity(info):
        raise _invalid_bundle()
    return _FileRecord(path, relative, path.name, _identity(info), info.st_size, digest)


def _bundle_root(bundle: Path) -> Path:
    try:
        raw = Path(bundle)
        if raw.is_symlink() or not raw.is_dir():
            raise OSError
        return raw.resolve(strict=True)
    except (OSError, RuntimeError, TypeError):
        raise _invalid_bundle() from None


def _expected_files(bundle: Path) -> tuple[_FileRecord, ...]:
    root = _bundle_root(bundle)
    directory = root
    for part in _SDK_DIRECTORY.parts:
        directory = directory / part
        try:
            info = directory.lstat()
        except OSError:
            raise _invalid_bundle() from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise _invalid_bundle()
    records: list[_FileRecord] = []
    names: set[str] = set()
    total = 0
    allowed_maa = {name.casefold() for name in _CORE_NAMES}
    try:
        with os.scandir(directory) as entries:
            for entry_count, entry in enumerate(entries, start=1):
                if entry_count > _MAX_DIRECTORY_ENTRIES:
                    raise _invalid_bundle()
                if entry.is_symlink():
                    raise _invalid_bundle()
                if not entry.name.casefold().endswith(".dll"):
                    continue
                if not 1 <= len(entry.name) <= 128 or not entry.name.isascii():
                    raise _invalid_bundle()
                folded = entry.name.casefold()
                if folded in names:
                    raise _invalid_bundle()
                names.add(folded)
                if folded.startswith("maa") and folded not in allowed_maa:
                    raise _invalid_bundle()
                record = _record_file(directory / entry.name, (_SDK_DIRECTORY / entry.name).as_posix())
                records.append(record)
                total += record.size
                if len(records) > _MAX_DLLS or total > _MAX_TOTAL_FILE_BYTES:
                    raise _invalid_bundle()
    except OSError:
        raise _invalid_bundle() from None
    if {name.casefold() for name in _CORE_NAMES} - names:
        raise _invalid_bundle()
    return tuple(sorted(records, key=lambda record: record.relative))


def _assert_unchanged(records: Sequence[_FileRecord]) -> None:
    for record in records:
        try:
            current = _record_file(record.path, record.relative)
        except ValueError:
            raise _invalid_observation() from None
        if (current.identity != record.identity or current.size != record.size or current.sha256 != record.sha256):
            raise _invalid_observation()


class _Kernel32Modules:
    """Minimal typed Kernel32 binding; it only sees this process handle."""

    def __init__(self) -> None:
        if sys.platform != "win32" or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise _LoaderFailure
        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            enum_modules = kernel32.K32EnumProcessModules
            module_name = kernel32.GetModuleFileNameW
            get_current_process = kernel32.GetCurrentProcess
            enum_modules.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
            enum_modules.restype = ctypes.c_int
            module_name.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32]
            module_name.restype = ctypes.c_uint32
            get_current_process.argtypes = []
            get_current_process.restype = ctypes.c_void_p
        except (AttributeError, OSError):
            raise _LoaderFailure from None
        self._enum_modules = enum_modules
        self._module_name = module_name
        self._process = get_current_process

    def current_process(self) -> int:
        value = self._process()
        if not value:
            raise _LoaderFailure
        return int(value)

    def enum_modules(self, process: int) -> tuple[int, ...]:
        handles = (ctypes.c_void_p * _MAX_MODULES)()
        needed = ctypes.c_uint32()
        if not self._enum_modules(ctypes.c_void_p(process), handles, ctypes.sizeof(handles), ctypes.byref(needed)):
            raise _LoaderFailure
        if needed.value % ctypes.sizeof(ctypes.c_void_p):
            raise _LoaderFailure
        count = needed.value // ctypes.sizeof(ctypes.c_void_p)
        if count > _MAX_MODULES:
            raise _LoaderFailure
        return tuple(int(handles[index]) for index in range(count) if handles[index])

    def module_path(self, module: int) -> str:
        buffer = ctypes.create_unicode_buffer(_MAX_PATH_CHARS)
        length = self._module_name(ctypes.c_void_p(module), buffer, _MAX_PATH_CHARS)
        if not length or length >= _MAX_PATH_CHARS - 1:
            raise _LoaderFailure
        return buffer.value


def _native_module_paths(*, _api: object | None = None) -> tuple[str, ...]:
    try:
        api = _Kernel32Modules() if _api is None else _api
        process = api.current_process()
        modules = api.enum_modules(process)
        if len(modules) > _MAX_MODULES:
            raise _LoaderFailure
        return _checked_module_paths(api.module_path(module) for module in modules)
    except Exception:
        raise _invalid_observation() from None


def _checked_module_paths(paths: Iterable[object]) -> tuple[str, ...]:
    checked: list[str] = []
    total = 0
    try:
        iterator = iter(paths)
        for raw in iterator:
            if type(raw) is not str or not raw or "\x00" in raw or len(raw) >= _MAX_PATH_CHARS:
                raise _LoaderFailure
            total += len(raw)
            if total > _MAX_TOTAL_PATH_CHARS or len(checked) >= _MAX_MODULES:
                raise _LoaderFailure
            checked.append(raw)
    except (TypeError, _LoaderFailure):
        raise _invalid_observation() from None
    return tuple(checked)


def _observed_records(records: Sequence[_FileRecord], module_paths: Iterable[object]) -> set[str]:
    expected_by_name = {record.name.casefold(): record for record in records}
    observed: set[str] = set()
    for raw in _checked_module_paths(module_paths):
        name = ntpath.basename(raw).casefold()
        record = expected_by_name.get(name)
        if record is None:
            continue
        if record.relative in observed:
            raise _invalid_observation()
        try:
            candidate = Path(raw).resolve(strict=True)
        except (OSError, RuntimeError):
            raise _invalid_observation() from None
        if candidate != record.path:
            raise _invalid_observation()
        observed.add(record.relative)
    core_names = {name.casefold() for name in _CORE_NAMES}
    required = {record.relative for record in records if record.name.casefold() in core_names}
    if not required.issubset(observed):
        raise _invalid_observation()
    return observed


def observe_windows_sdk_loads(bundle: Path, *, _module_paths: Iterable[object] | None = None) -> dict[str, object]:
    """Observe expected DLLs already loaded by this Windows probe process only."""
    records = _expected_files(bundle)
    paths = _native_module_paths() if _module_paths is None else _checked_module_paths(_module_paths)
    observed = _observed_records(records, paths)
    _assert_unchanged(records)
    loaded = [
        {"path": record.relative, "sha256": record.sha256, "size_bytes": record.size}
        for record in records if record.relative in observed
    ]
    unobserved = [record.relative for record in records if record.relative not in observed]
    return {"schema_version": 1, "scope": _SCOPE, "loaded": loaded, "unobserved": unobserved}


def _valid_sha256(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def validate_windows_sdk_loads(bundle: Path, payload: object) -> dict[str, object]:
    """Independently bind a loader report to current private bundle files."""
    records = _expected_files(bundle)
    if type(payload) is not dict or set(payload) != {"schema_version", "scope", "loaded", "unobserved"}:
        raise _invalid_payload()
    if (type(payload["schema_version"]) is not int or payload["schema_version"] != 1
            or type(payload["scope"]) is not str or payload["scope"] != _SCOPE):
        raise _invalid_payload()
    loaded = payload["loaded"]
    unobserved = payload["unobserved"]
    if type(loaded) is not list or type(unobserved) is not list:
        raise _invalid_payload()
    expected = {record.relative: record for record in records}
    loaded_paths: list[str] = []
    for item in loaded:
        if type(item) is not dict or set(item) != {"path", "sha256", "size_bytes"}:
            raise _invalid_payload()
        path = item["path"]
        if type(path) is not str or path not in expected or not _valid_sha256(item["sha256"]):
            raise _invalid_payload()
        if type(item["size_bytes"]) is not int or item["size_bytes"] < 0:
            raise _invalid_payload()
        record = expected[path]
        if item["sha256"] != record.sha256 or item["size_bytes"] != record.size:
            raise _invalid_payload()
        loaded_paths.append(path)
    if loaded_paths != sorted(loaded_paths) or len(set(loaded_paths)) != len(loaded_paths):
        raise _invalid_payload()
    if any(type(path) is not str or path not in expected for path in unobserved):
        raise _invalid_payload()
    if unobserved != sorted(unobserved) or len(set(unobserved)) != len(unobserved):
        raise _invalid_payload()
    if set(loaded_paths) | set(unobserved) != set(expected) or set(loaded_paths) & set(unobserved):
        raise _invalid_payload()
    core_names = {name.casefold() for name in _CORE_NAMES}
    required = {record.relative for record in records if record.name.casefold() in core_names}
    if not required.issubset(loaded_paths):
        raise _invalid_payload()
    return {"schema_version": 1, "scope": _SCOPE, "loaded": list(loaded), "unobserved": list(unobserved)}
