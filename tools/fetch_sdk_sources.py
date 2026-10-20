"""Prepare pinned Maa SDK source archives for private developer work.

This developer-only tool does not build, install, execute, or publish SDK code.
The application never calls it.  Its fixed manifest is intentionally not a CLI
input: source provenance must remain reviewable in this repository.
"""

from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from typing import Any


MANIFEST_PATH = Path(__file__).with_name("sdk_sources.json")
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_UNPACKED_BYTES = 128 * 1024 * 1024
MAX_UNPACKED_MEMBERS = 30_000
_RENAME_EXCL = 0x00000004

_COMPONENTS = (
    ("MaaFramework", "MaaXYZ/MaaFramework", "source/MaaFramework"),
    ("MaaUtils", "MaaXYZ/MaaUtils", "source/MaaFramework/source/MaaUtils"),
    ("MaaDeps", "MaaXYZ/MaaDeps", "source/MaaFramework/source/MaaUtils/MaaDeps"),
    ("vcpkg", "microsoft/vcpkg", "source/MaaFramework/source/MaaUtils/MaaDeps/vcpkg"),
)


@dataclass(frozen=True)
class SourceComponent:
    name: str
    repository: str
    commit: str
    url: str
    size: int
    sha256: str
    archive_root: str
    destination: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _is_lower_hex(value: object, length: int) -> bool:
    return (
        isinstance(value, str)
        and len(value) == length
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_manifest(raw: object) -> tuple[SourceComponent, ...]:
    _require(isinstance(raw, dict), "SDK source manifest must be an object.")
    _require(set(raw) == {"schema_version", "sdk_version", "scope", "components"}, "SDK source manifest has unexpected fields.")
    _require(isinstance(raw["schema_version"], int) and not isinstance(raw["schema_version"], bool) and raw["schema_version"] == 1,
             "SDK source manifest schema version is unsupported.")
    _require(isinstance(raw["sdk_version"], str) and raw["sdk_version"], "SDK source manifest sdk_version is invalid.")
    _require(isinstance(raw["scope"], str) and raw["scope"], "SDK source manifest scope is invalid.")
    entries = raw["components"]
    _require(isinstance(entries, list) and len(entries) == len(_COMPONENTS), "SDK source manifest must contain four components.")

    result: list[SourceComponent] = []
    fields = {"name", "repository", "commit", "url", "size", "sha256", "archive_root", "destination"}
    for entry, expected in zip(entries, _COMPONENTS, strict=True):
        name, repository, destination = expected
        _require(isinstance(entry, dict) and set(entry) == fields, "SDK source manifest component has unexpected fields.")
        _require(entry["name"] == name and entry["repository"] == repository and entry["destination"] == destination,
                 "SDK source manifest component order or destination is invalid.")
        _require(_is_lower_hex(entry["commit"], 40), "SDK source manifest commit must be 40 lowercase hexadecimal characters.")
        _require(_is_lower_hex(entry["sha256"], 64), "SDK source manifest sha256 must be 64 lowercase hexadecimal characters.")
        _require(isinstance(entry["size"], int) and not isinstance(entry["size"], bool) and 0 < entry["size"] <= MAX_ARCHIVE_BYTES,
                 "SDK source manifest archive size is invalid.")
        expected_url = f"https://codeload.github.com/{repository}/tar.gz/{entry['commit']}"
        _require(entry["url"] == expected_url, "SDK source manifest URL is not the fixed codeload archive URL.")
        expected_root = f"{repository.rsplit('/', 1)[1]}-{entry['commit']}"
        _require(entry["archive_root"] == expected_root, "SDK source manifest archive root is invalid.")
        result.append(SourceComponent(**entry))
    return tuple(result)


def load_manifest() -> tuple[tuple[SourceComponent, ...], bytes]:
    """Load and validate the single repository-owned SDK source manifest."""
    try:
        manifest_bytes = MANIFEST_PATH.read_bytes()
        raw = json.loads(manifest_bytes)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("SDK source manifest cannot be read.") from error
    return _validate_manifest(raw), manifest_bytes


def download_archive(curl: str, component: SourceComponent, target: Path) -> None:
    """Download one fixed archive with curl's HTTPS-only transport policy."""
    subprocess.run(
        [
            curl,
            "--disable",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--proto",
            "=https",
            "--proto-redir",
            "=https",
            "--max-time",
            "60",
            "--max-filesize",
            str(component.size),
            "--output",
            str(target),
            component.url,
        ],
        check=True,
    )


def _verify_archive(path: Path, component: SourceComponent) -> None:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{component.name} archive was not a regular file.")
    if path.stat().st_size != component.size:
        raise ValueError(f"{component.name} archive size did not match fixed manifest.")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != component.sha256:
        raise ValueError(f"{component.name} archive SHA-256 did not match fixed manifest.")


def _archive_path_parts(member: tarfile.TarInfo, component: SourceComponent) -> tuple[str, ...]:
    name = member.name
    _require(isinstance(name, str) and name and not name.startswith("/"), f"{component.name} archive has an absolute path.")
    _require("\\" not in name and ":" not in name and "\x00" not in name,
             f"{component.name} archive has a backslash, drive, or null path.")
    normalized = name.rstrip("/")
    _require(normalized, f"{component.name} archive has an empty path.")
    _require("//" not in normalized, f"{component.name} archive has an unsafe empty path segment.")
    parts = PurePosixPath(normalized).parts
    _require(parts and all(part not in {"", ".", ".."} for part in parts), f"{component.name} archive has path traversal.")
    _require(parts[0] == component.archive_root, f"{component.name} archive root did not match fixed manifest.")
    return parts


def _inspect_archive(
    archive_path: Path,
    component: SourceComponent,
    remaining_bytes: int,
    remaining_members: int,
) -> tuple[list[tuple[tarfile.TarInfo, tuple[str, ...]]], int]:
    entries: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
    seen: set[tuple[str, ...]] = set()
    total_bytes = 0
    found_root_directory = False
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive:
                _require((member.isdir() or member.isreg()) and not member.issparse(),
                         f"{component.name} archive contains a link or special file.")
                parts = _archive_path_parts(member, component)
                _require(parts not in seen, f"{component.name} archive has duplicate paths.")
                seen.add(parts)
                if parts == (component.archive_root,):
                    _require(member.isdir(), f"{component.name} archive root is not a directory.")
                    found_root_directory = True
                _require(len(entries) < remaining_members, f"{component.name} archive exceeds member limit.")
                if member.isreg():
                    _require(member.size >= 0 and total_bytes <= remaining_bytes - member.size,
                             f"{component.name} archive exceeds unpacked size limit.")
                    total_bytes += member.size
                entries.append((member, parts))
    except (tarfile.TarError, OSError) as error:
        raise ValueError(f"{component.name} archive could not be inspected.") from error
    _require(entries, f"{component.name} archive is empty.")
    _require(found_root_directory, f"{component.name} archive is missing its expected root directory.")
    return entries, total_bytes


def _ensure_empty_directory(path: Path, label: str) -> None:
    if path.exists() or path.is_symlink():
        _require(not path.is_symlink() and path.is_dir(), f"{label} is not a real directory.")
        _require(not any(path.iterdir()), f"{label} is not empty; refusing to overwrite source.")
        return
    path.mkdir(parents=True)


def _extract_archive(
    archive_path: Path,
    component: SourceComponent,
    target_root: Path,
    remaining_bytes: int,
    remaining_members: int,
) -> tuple[int, int]:
    entries, total_bytes = _inspect_archive(archive_path, component, remaining_bytes, remaining_members)
    _ensure_empty_directory(target_root, f"{component.name} destination")
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member, parts in entries:
                relative_parts = parts[1:]
                if not relative_parts:
                    _require(member.isdir(), f"{component.name} archive root is not a directory.")
                    continue
                output = target_root.joinpath(*relative_parts)
                if member.isdir():
                    if output.exists() or output.is_symlink():
                        _require(not output.is_symlink() and output.is_dir(), f"{component.name} archive has a file/directory collision.")
                    else:
                        output.mkdir(parents=True)
                    continue
                _require(not output.exists() and not output.is_symlink(), f"{component.name} archive would overwrite a file.")
                output.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                _require(source is not None, f"{component.name} archive member cannot be read.")
                with source, output.open("xb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
                os.chmod(output, stat.S_IMODE(member.mode) & 0o777)
    except (tarfile.TarError, OSError) as error:
        raise ValueError(f"{component.name} archive could not be extracted.") from error
    return total_bytes, len(entries)


def _write_provenance(stage: Path, components: tuple[SourceComponent, ...]) -> None:
    records = [
        {
            "name": component.name,
            "archive": f"archives/{component.name}-{component.commit}.tar.gz",
            "destination": component.destination,
            "url": component.url,
            "size": component.size,
            "sha256": component.sha256,
        }
        for component in components
    ]
    (stage / "PROVENANCE.json").write_text(
        json.dumps({"manifest": "sdk_sources.json", "components": records}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _publish_new(stage: Path, target: Path) -> None:
    """Atomically publish ``stage`` only when ``target`` does not exist.

    The platform calls below provide no-replace semantics themselves.  A
    pre-publication existence check cannot close a concurrent-create race.
    """
    if sys.platform == "win32":
        os.rename(stage, target)
        return
    if sys.platform == "darwin":
        library = ctypes.CDLL(None, use_errno=True)
        try:
            renamex_np = library.renamex_np
        except AttributeError as error:
            raise OSError("macOS renamex_np is unavailable; refusing non-atomic publication.") from error
        renamex_np.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
        renamex_np.restype = ctypes.c_int
        result = renamex_np(os.fsencode(stage), os.fsencode(target), _RENAME_EXCL)
        if result != 0:
            error_number = ctypes.get_errno()
            raise OSError(error_number, os.strerror(error_number), str(target))
        return
    raise OSError("Atomic no-replace SDK source publication is unsupported on this platform.")


def prepare(destination: Path | str) -> Path:
    """Fetch and safely assemble pinned source under a new destination only."""
    requested = Path(destination)
    target = requested.parent.resolve(strict=True) / requested.name
    if target.exists() or target.is_symlink():
        raise ValueError("SDK source destination already exists or is a link.")
    parent = target.parent.resolve(strict=True)
    if not parent.is_dir() or parent.is_symlink():
        raise ValueError("SDK source destination parent must be a real directory.")
    components, manifest_bytes = load_manifest()
    curl = shutil.which("curl")
    if not curl:
        raise ValueError("TLS-verifying curl is required for SDK source preparation.")

    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=parent))
    try:
        archives = stage / "archives"
        archives.mkdir()
        remaining_bytes = MAX_UNPACKED_BYTES
        remaining_members = MAX_UNPACKED_MEMBERS
        for component in components:
            archive = archives / f"{component.name}-{component.commit}.tar.gz"
            download_archive(curl, component, archive)
            _verify_archive(archive, component)
            extracted_bytes, extracted_members = _extract_archive(
                archive,
                component,
                stage / component.destination,
                remaining_bytes,
                remaining_members,
            )
            remaining_bytes -= extracted_bytes
            remaining_members -= extracted_members
        (stage / "sdk_sources.json").write_bytes(manifest_bytes)
        _write_provenance(stage, components)
        _publish_new(stage, target)
        return target
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare fixed Maa SDK source archives for private developer work.")
    parser.add_argument("--destination", required=True, type=Path, help="new output directory")
    arguments = parser.parse_args(argv)
    try:
        prepared = prepare(arguments.destination)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    print(f"Prepared verified SDK source at {prepared}. Developer-only; SDK distribution gate remains closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
