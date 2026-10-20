"""Record read-only evidence for an SDK-bearing frozen application bundle.

This tool only reads an existing bundle.  It never imports the bundled SDK,
executes the application, downloads dependencies, or changes packaging policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
from typing import Any

from tools.check_build import frozen_executable
from tools.package_build import LABELS, embedded_module_names


COMMIT_PATTERN = re.compile(r"[0-9a-fA-F]{40}")
NATIVE_FILE_PATTERN = re.compile(r"\.(?:dll|dylib|pyd|so)(?:\.[^/]+)?$", re.IGNORECASE)
MACH_O_MAGICS = {
    b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf", b"\xbe\xba\xfe\xca", b"\xbf\xba\xfe\xca",
}
SCHEMA_VERSION = "sdk-inventory.v2"


def _agent_component(part: str) -> bool:
    return part.casefold().startswith("maaagentbinary")


def _relative(path: Path, bundle: Path) -> str:
    """Return a portable bundle-relative path, never a host path."""
    try:
        relative = path.relative_to(bundle)
    except ValueError as error:
        raise ValueError("Bundle entry escapes the bundle root.") from error
    result = PurePosixPath(relative.as_posix())
    if result.is_absolute() or ".." in result.parts or str(result) == ".":
        raise ValueError("Bundle entry has an unsafe relative path.")
    return result.as_posix()


def _resolved_inside(path: Path, bundle: Path) -> Path:
    """Resolve an entry only when its target remains inside ``bundle``."""
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as error:
        raise ValueError("Bundle contains a broken symlink.") from error
    except RuntimeError as error:
        raise ValueError("Bundle contains a symlink loop.") from error
    try:
        resolved.relative_to(bundle)
    except ValueError as error:
        raise ValueError("Bundle contains a symlink target outside its root.") from error
    return resolved


def _bundle_files(bundle: Path) -> list[tuple[str, Path]]:
    """List regular bundle files while preserving safe internal symlink aliases."""
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("Bundle must be a real directory.")
    root = bundle.resolve(strict=True)
    files: list[tuple[str, Path]] = []

    def visit(logical: Path, ancestors: set[tuple[int, int]]) -> None:
        if logical != bundle and any(_agent_component(part) for part in PurePosixPath(_relative(logical, bundle)).parts):
            raise ValueError("MaaAgentBinary namespace or path is forbidden in SDK evidence.")
        resolved = _resolved_inside(logical, root)
        mode = resolved.stat().st_mode
        if stat.S_ISREG(mode):
            files.append((_relative(logical, bundle), resolved))
            return
        if not stat.S_ISDIR(mode):
            raise ValueError("Bundle contains an unsupported file type.")
        identity = (resolved.stat().st_dev, resolved.stat().st_ino)
        if identity in ancestors:
            raise ValueError("Bundle contains a symlink directory cycle.")
        descendants = ancestors | {identity}
        for child in sorted(logical.iterdir(), key=lambda item: item.name):
            child_mode = child.lstat().st_mode
            if stat.S_ISLNK(child_mode):
                _resolved_inside(child, root)
            elif not stat.S_ISREG(child_mode) and not stat.S_ISDIR(child_mode):
                raise ValueError("Bundle contains an unsupported file type.")
            visit(child, descendants)

    visit(bundle, set())
    return files


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            size += len(block)
            digest.update(block)
    return size, digest.hexdigest()


def _has_native_header(path: Path) -> bool:
    """Recognize native executable headers using at most one 4 KiB read."""
    with path.open("rb") as source:
        header = source.read(4096)
    if header[:4] in MACH_O_MAGICS:
        return True
    if header[:2] != b"MZ" or len(header) < 0x40:
        return False
    pe_offset = int.from_bytes(header[0x3C:0x40], "little")
    return pe_offset <= len(header) - 4 and header[pe_offset:pe_offset + 4] == b"PE\0\0"


def _native_file(relative: str, target: Path) -> bool:
    return bool(NATIVE_FILE_PATTERN.search(PurePosixPath(relative).name)) or _has_native_header(target)


def _contains_agent_binary(module_names: list[str], paths: list[str]) -> bool:
    if any(name.split(".", 1)[0].casefold() == "maaagentbinary" for name in module_names):
        return True
    return any(
        any(_agent_component(part) for part in PurePosixPath(path).parts)
        for path in paths
    )


def _is_framework_binary(path: str) -> bool:
    return "maaframework" in PurePosixPath(path).name.casefold()


def inventory(
    bundle: Path,
    executable: Path,
    commit: str,
    label: str,
    require_sdk: bool = True,
) -> dict[str, Any]:
    """Return serializable SDK-bundle evidence without executing bundle code."""
    if label not in LABELS:
        raise ValueError("label must be windows-x64, macos-arm64, or macos-x64.")
    if not COMMIT_PATTERN.fullmatch(commit):
        raise ValueError("commit must be exactly 40 hexadecimal characters.")

    bundle = bundle.absolute()
    executable = executable.absolute()
    root = _resolved_inside(bundle, bundle.resolve(strict=True))
    try:
        executable.relative_to(bundle)
    except ValueError as error:
        raise ValueError("Executable must be below the bundle root.") from error
    executable_target = _resolved_inside(executable, root)
    if not executable_target.is_file():
        raise ValueError("Executable must be a regular file.")

    bundle_files = _bundle_files(bundle)
    paths = [path for path, _target in bundle_files]
    modules = sorted(embedded_module_names(executable))
    if _contains_agent_binary(modules, paths):
        raise ValueError("MaaAgentBinary namespace or path is forbidden in SDK evidence.")

    native_by_content: dict[tuple[int, str], list[str]] = {}
    file_digests: dict[str, tuple[int, str]] = {}
    legal_files: list[dict[str, Any]] = []
    for relative, target in bundle_files:
        size, sha256 = _hash_file(target)
        file_digests[relative] = (size, sha256)
        if _native_file(relative, target):
            native_by_content.setdefault((size, sha256), []).append(relative)
        if any(part.casefold() == "legal" for part in PurePosixPath(relative).parts):
            legal_files.append({"path": relative, "sha256": sha256})

    native_files = [
        {"paths": sorted(paths), "sha256": sha256, "size_bytes": size}
        for (size, sha256), paths in native_by_content.items()
    ]
    native_files.sort(key=lambda record: record["paths"])
    maa_modules = [name for name in modules if name == "maa" or name.startswith("maa.")]
    framework_paths = sorted(
        path for record in native_files for path in record["paths"] if _is_framework_binary(path)
    )
    if require_sdk and (not maa_modules or not framework_paths):
        raise ValueError("SDK inventory requires embedded maa modules and a MaaFramework native library.")
    executable_relative = _relative(executable, bundle)
    executable_size, executable_sha256 = file_digests[executable_relative]

    return {
        "schema_version": SCHEMA_VERSION,
        "source": {"commit": commit.lower(), "label": label},
        "evidence_scope": "Static bundle contents only; source label is not operating-system validation.",
        "executable": {
            "path": executable_relative,
            "sha256": executable_sha256,
            "size_bytes": executable_size,
            "native": _native_file(executable_relative, executable_target),
        },
        "embedded_modules": modules,
        "native_files": native_files,
        "legal_files": sorted(legal_files, key=lambda record: record["path"]),
        "sdk_presence": {
            "required": require_sdk,
            "maa_modules": maa_modules,
            "maaframework_native_paths": framework_paths,
            "maaagentbinary_present": False,
        },
    }


def write_inventory(output: Path, record: dict[str, Any]) -> None:
    """Atomically write evidence JSON without exposing source filesystem paths."""
    output = output.absolute()
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=output.parent, prefix=f".{output.name}.", suffix=".tmp", delete=False
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, output)
    finally:
        if temporary_name is not None and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def _bundle_from_executable(executable: Path, label: str) -> Path:
    if label == "windows-x64":
        return executable.parent
    try:
        return executable.parents[2]
    except IndexError as error:
        raise ValueError("macOS executable does not have an app bundle root.") from error


def main() -> None:
    parser = argparse.ArgumentParser(description="Inventory an existing SDK diagnostic bundle without executing it.")
    parser.add_argument("--label", required=True, choices=sorted(LABELS))
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-sdk", action="store_true", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    try:
        executable = frozen_executable(root)
        record = inventory(
            _bundle_from_executable(executable, args.label),
            executable,
            args.commit,
            args.label,
            require_sdk=args.require_sdk,
        )
        write_inventory(root / args.output, record)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
