"""Select and inspect the minimal MaaFramework native SDK bundle.

The selector operates only on PyInstaller's collected-path records.  The
validator reads an already-built bundle.  Neither function imports MaaFw,
executes native code, or writes to the filesystem.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePath
import re
import stat
from typing import Iterable


_SYSTEMS = {"win32", "darwin"}
_REQUIRED_STEMS = {"MaaFramework", "MaaUtils", "MaaCustomControlUnit"}
_UNUSED_STEMS = {
    "MaaAdbControlUnit",
    "MaaAgentClient",
    "MaaAgentServer",
    "MaaMacOSControlUnit",
    "MaaPlayCoverControlUnit",
    "MaaRecordControlUnit",
    "MaaReplayControlUnit",
    "MaaToolkit",
    "MaaWin32ControlUnit",
    "MaaGamepadControlUnit",
    "MaaDbgControlUnit",
    "MaaLinuxControlUnit",
    "MaaAndroidNativeControlUnit",
}
_WINDOWS_NAME = re.compile(r"^(Maa[A-Za-z0-9]+)\.dll$", re.ASCII)
_MACOS_NAME = re.compile(r"^lib(Maa[A-Za-z0-9]+)\.dylib$", re.ASCII)
_ANY_MAA_NAME = re.compile(r"^(?:lib)?maa", re.IGNORECASE)
_NATIVE_MARKERS = (".dll", ".dylib", ".so", ".pyd")


def _require_system(system: str) -> None:
    if system not in _SYSTEMS:
        raise ValueError("Recognition bundles support only win32 and darwin.")


def _path_string(value: object) -> str:
    """Return one path-like value or a stable validation error."""
    try:
        raw = os.fspath(value)
    except TypeError as error:
        raise ValueError("Collected binary paths must be path-like strings.") from error
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError("Collected binary paths must be non-empty safe strings.")
    return raw


def _path_parts(value: object, *, source: bool) -> tuple[str, ...]:
    """Parse one path form without resolving or accessing its filesystem."""
    raw = _path_string(value)
    normalized = raw.replace("\\", "/")
    if "//" in normalized or "/./" in f"/{normalized}/":
        raise ValueError("Collected binary path has an unsafe form.")
    parts = tuple(part for part in normalized.split("/") if part)
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("Collected binary path has traversal.")
    absolute = normalized.startswith("/") or bool(re.match(r"^[A-Za-z]:/", normalized))
    if source != absolute:
        description = "source" if source else "destination"
        raise ValueError(f"Collected binary {description} path has an unsafe form.")
    return parts


def _maa_bin_file(parts: tuple[str, ...]) -> str | None:
    """Return a direct ``maa/bin`` filename, rejecting case and path tricks."""
    matches = [index for index, part in enumerate(parts) if part.casefold() == "maa"]
    if not matches:
        raise ValueError("Collected binary is outside the locked maa package.")
    if len(matches) != 1:
        raise ValueError("Collected binary has an ambiguous maa package path.")
    index = matches[0]
    if parts[index] != "maa" or index + 1 >= len(parts) or parts[index + 1] != "bin":
        raise ValueError("Collected binary uses a case-variant or unsafe maa/bin path.")
    remainder = parts[index + 2:]
    if not remainder:
        raise ValueError("Collected binary does not name a maa/bin file.")
    if remainder[0].casefold() == "plugins":
        return None
    if len(remainder) != 1:
        raise ValueError("Collected binary is outside direct maa/bin dependencies.")
    return remainder[0]


def _maa_native_stem(name: str, system: str) -> str | None:
    """Classify Maa-named native libraries while leaving ordinary files alone."""
    folded = name.casefold()
    if not _ANY_MAA_NAME.match(name) or not any(marker in folded for marker in _NATIVE_MARKERS):
        return None
    pattern = _WINDOWS_NAME if system == "win32" else _MACOS_NAME
    matched = pattern.fullmatch(name)
    if matched:
        stem = matched.group(1)
        if stem not in _REQUIRED_STEMS and stem not in _UNUSED_STEMS:
            raise ValueError("Unknown Maa native library is forbidden.")
        return stem
    if _ANY_MAA_NAME.match(name):
        raise ValueError("Unknown or wrong-platform Maa native library is forbidden.")
    raise ValueError("Unknown or wrong-platform Maa native library is forbidden.")


def _required_name(stem: str, system: str) -> str:
    return f"{stem}.dll" if system == "win32" else f"lib{stem}.dylib"


def select_recognition_binaries(
    entries: Iterable[tuple[object, object]], system: str,
) -> list[tuple[str, str]]:
    """Keep MaaFw's three core libraries and direct non-plugin dependencies.

    ``entries`` has PyInstaller's ``(source_path, destination_directory)``
    shape.  Required Maa libraries must each appear exactly once.  The returned
    tuples are sorted, portable strings for deterministic build commands.
    """
    _require_system(system)
    selected: list[tuple[str, str]] = []
    required: dict[str, int] = {stem: 0 for stem in _REQUIRED_STEMS}
    for entry in entries:
        if not isinstance(entry, tuple) or len(entry) != 2:
            raise ValueError("Collected binary entry must be a source/destination tuple.")
        source_value, destination_value = entry
        source = _path_string(source_value)
        destination = _path_string(destination_value)
        source_parts = _path_parts(source, source=True)
        destination_parts = _path_parts(destination, source=False)
        filename = _maa_bin_file(source_parts)
        if filename is None:
            if len(destination_parts) < 3 or destination_parts[:3] != ("maa", "bin", "plugins"):
                raise ValueError("Collected plugin destination must remain under maa/bin/plugins.")
            continue
        if destination_parts != ("maa", "bin"):
            raise ValueError("Collected binary destination must be exactly maa/bin.")
        stem = _maa_native_stem(filename, system)
        if stem is None:
            expected = ".dll" if system == "win32" else ".dylib"
            if not filename.endswith(expected):
                raise ValueError("Collected maa/bin dependency has an unsupported native suffix.")
        if stem in _UNUSED_STEMS:
            continue
        if stem in _REQUIRED_STEMS:
            if filename != _required_name(stem, system):
                raise ValueError("Required Maa native library uses a case-variant name.")
            required[stem] += 1
        selected.append((str(source), str(destination)))
    missing = sorted(stem for stem, count in required.items() if count == 0)
    repeated = sorted(stem for stem, count in required.items() if count > 1)
    if missing or repeated:
        details = []
        if missing:
            details.append(f"missing required Maa libraries: {', '.join(missing)}")
        if repeated:
            details.append(f"repeated required Maa libraries: {', '.join(repeated)}")
        raise ValueError("; ".join(details))
    return sorted(selected, key=lambda item: (item[1], item[0]))


def _inside(path: Path, root: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError("Recognition bundle contains a broken symlink.") from error
    except RuntimeError as error:
        raise ValueError("Recognition bundle contains a symlink loop.") from error
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError("Recognition bundle symlink escapes its root.") from error
    return resolved


def _logical_parts(path: Path, bundle: Path) -> tuple[str, ...]:
    relative = path.relative_to(bundle)
    parts = PurePath(relative).parts
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("Recognition bundle has an unsafe relative path.")
    return parts


def _inspect_namespace(parts: tuple[str, ...]) -> None:
    """Reject forbidden directories before a future loader can discover them."""
    for index, part in enumerate(parts):
        if part.casefold().startswith("maaagentbinary"):
            raise ValueError("MaaAgentBinary namespace is forbidden in recognition bundles.")
        if part.casefold() == "maa":
            if part != "maa":
                raise ValueError("Recognition bundle uses a case-variant or unsafe maa/bin path.")
            if index + 1 >= len(parts):
                continue
            if parts[index + 1] != "bin":
                raise ValueError("Recognition bundle uses a case-variant or unsafe maa/bin path.")
            if len(parts) > index + 2 and parts[index + 2].casefold() == "plugins":
                raise ValueError("Native plugins under maa/bin are forbidden.")


def _inspect_native_name(name: str, system: str, required: set[str]) -> None:
    stem = _maa_native_stem(name, system)
    if stem is None:
        return
    if stem in _UNUSED_STEMS:
        raise ValueError("Forbidden unused Maa native library is present in recognition bundle.")
    if stem in _REQUIRED_STEMS:
        if name != _required_name(stem, system):
            raise ValueError("Required Maa native library uses a case-variant name.")
        required.add(stem)


def _inspect_logical_file(path: Path, target: Path, bundle: Path, system: str, required: set[str]) -> None:
    _logical_parts(path, bundle)
    _inspect_native_name(path.name, system, required)
    _inspect_native_name(target.name, system, required)


def validate_recognition_bundle(bundle: Path | str, system: str) -> None:
    """Fail closed unless a built Windows/macOS SDK bundle has exact core libs.

    Internal PyInstaller symlink aliases are permitted only when their resolved
    targets remain in ``bundle``.  This function reads the tree only.
    """
    _require_system(system)
    bundle_path = Path(bundle)
    if bundle_path.is_symlink() or not bundle_path.is_dir():
        raise ValueError("Recognition bundle must be a real directory.")
    root = bundle_path.resolve(strict=True)
    required: set[str] = set()

    def visit(logical: Path, ancestors: set[tuple[int, int]]) -> None:
        target = _inside(logical, root)
        if logical != bundle_path:
            _inspect_namespace(_logical_parts(logical, bundle_path))
        if target != root:
            _inspect_namespace(_logical_parts(target, root))
        mode = target.stat().st_mode
        if stat.S_ISREG(mode):
            _inspect_logical_file(logical, target, bundle_path, system, required)
            return
        if not stat.S_ISDIR(mode):
            raise ValueError("Recognition bundle contains an unsupported file type.")
        identity = (target.stat().st_dev, target.stat().st_ino)
        if identity in ancestors:
            raise ValueError("Recognition bundle contains a symlink directory cycle.")
        descendants = ancestors | {identity}
        for child in sorted(logical.iterdir(), key=lambda item: item.name):
            child_mode = child.lstat().st_mode
            if not stat.S_ISREG(child_mode) and not stat.S_ISDIR(child_mode) and not stat.S_ISLNK(child_mode):
                raise ValueError("Recognition bundle contains an unsupported file type.")
            visit(child, descendants)

    visit(bundle_path, set())
    missing = sorted(_REQUIRED_STEMS - required)
    if missing:
        raise ValueError(f"Recognition bundle is missing required Maa libraries: {', '.join(missing)}")
