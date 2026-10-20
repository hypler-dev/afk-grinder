"""Prepare pinned MaaDeps build prerequisites for private SDK rebuild tests.

This helper fetches and verifies data only.  It never builds, installs, loads,
or executes SDK code, and the application does not import it.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile

from tools.fetch_sdk_sources import _publish_new


MANIFEST_PATH = Path(__file__).with_name("sdk_build_dependencies.json")
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024
MAX_REGULAR_BYTES = 2 * 1024 * 1024 * 1024
MAX_MEMBERS = 50_000
MAX_SYMLINK_CHAIN = 16
_RELEASE = "v3.0.0"
_TARGETS = {
    "macos-arm64": ("darwin", "arm64", "maa-arm64-osx", "MaaDeps-arm64-osx.tar.xz"),
    "macos-x64": ("darwin", "x86_64", "maa-x64-osx", "MaaDeps-x64-osx.tar.xz"),
    "windows-x64": ("win32", "AMD64", "maa-x64-windows", "MaaDeps-x64-windows.tar.xz"),
}
_TOP_LEVELS = {"vcpkg", "runtime", "msbuild", "maadeps.cmake"}


@dataclass(frozen=True)
class BuildDependency:
    label: str
    system: str
    architecture: str
    triplet: str
    archive_name: str
    url: str
    size: int
    sha256: str


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _lower_hex(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and all(character in "0123456789abcdef" for character in value)


def _parse_manifest(raw: object) -> dict[str, BuildDependency]:
    _require(isinstance(raw, dict), "SDK build dependency manifest must be an object.")
    _require(set(raw) == {"schema_version", "release", "scope", "targets"}, "SDK build dependency manifest has unexpected fields.")
    _require(isinstance(raw["schema_version"], int) and not isinstance(raw["schema_version"], bool) and raw["schema_version"] == 1,
             "SDK build dependency manifest schema version is unsupported.")
    _require(raw["release"] == _RELEASE, "SDK build dependency manifest release is invalid.")
    _require(isinstance(raw["scope"], str) and raw["scope"], "SDK build dependency manifest scope is invalid.")
    targets = raw["targets"]
    _require(isinstance(targets, dict) and set(targets) == set(_TARGETS), "SDK build dependency manifest target labels are invalid.")
    fields = {"system", "architecture", "triplet", "archive_name", "url", "size", "sha256"}
    parsed: dict[str, BuildDependency] = {}
    for label, (system, architecture, triplet, archive_name) in _TARGETS.items():
        entry = targets[label]
        _require(isinstance(entry, dict) and set(entry) == fields, "SDK build dependency manifest target has unexpected fields.")
        _require(
            entry["system"] == system
            and entry["architecture"] == architecture
            and entry["triplet"] == triplet
            and entry["archive_name"] == archive_name,
            "SDK build dependency manifest target identity is invalid.",
        )
        _require(isinstance(entry["size"], int) and not isinstance(entry["size"], bool) and 0 < entry["size"] <= MAX_ARCHIVE_BYTES,
                 "SDK build dependency manifest archive size is invalid.")
        _require(_lower_hex(entry["sha256"], 64), "SDK build dependency manifest SHA-256 is invalid.")
        expected_url = f"https://github.com/MaaXYZ/MaaDeps/releases/download/{_RELEASE}/{archive_name}"
        _require(entry["url"] == expected_url, "SDK build dependency manifest archive URL is invalid.")
        parsed[label] = BuildDependency(label=label, **entry)
    return parsed


def _load_manifest() -> tuple[dict[str, BuildDependency], bytes]:
    try:
        contents = MANIFEST_PATH.read_bytes()
        raw = json.loads(contents)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("SDK build dependency manifest cannot be read.") from error
    return _parse_manifest(raw), contents


def load_dependencies() -> dict[str, BuildDependency]:
    """Return fixed, validated dependency records keyed by target label."""
    dependencies, _contents = _load_manifest()
    return dependencies


def _download(curl: str, dependency: BuildDependency, output: Path) -> None:
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
            "180",
            "--max-filesize",
            str(dependency.size),
            "--output",
            str(output),
            dependency.url,
        ],
        check=True,
    )


def _verify_archive(archive: Path, dependency: BuildDependency) -> None:
    _require(archive.is_file() and not archive.is_symlink(), "SDK build dependency download is not a regular file.")
    _require(archive.stat().st_size == dependency.size, "SDK build dependency archive size did not match fixed manifest.")
    digest = hashlib.sha256()
    with archive.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    _require(digest.hexdigest() == dependency.sha256, "SDK build dependency archive SHA-256 did not match fixed manifest.")


def _member_parts(member: tarfile.TarInfo) -> tuple[str, ...]:
    name = member.name
    _require(isinstance(name, str) and "\x00" not in name and "\\" not in name and ":" not in name,
             "SDK build dependency archive has an unsafe path.")
    if name == "." or name == "./":
        _require(member.isdir(), "SDK build dependency archive root is not a directory.")
        return ()
    if name.startswith("./"):
        name = name[2:]
    _require(name and not name.startswith("/"), "SDK build dependency archive has an absolute or empty path.")
    _require("//" not in name, "SDK build dependency archive has an empty path segment.")
    parts = PurePosixPath(name.rstrip("/")).parts
    _require(parts and all(part not in {"", ".", ".."} for part in parts), "SDK build dependency archive has path traversal.")
    _require(parts[0] in _TOP_LEVELS, "SDK build dependency archive has an unexpected top-level path.")
    if parts[0] == "maadeps.cmake":
        _require(len(parts) == 1 and member.isreg(), "SDK build dependency archive maadeps.cmake must be a regular root file.")
    return parts


def _inspect_archive(
    archive: Path,
) -> tuple[list[tuple[tarfile.TarInfo, tuple[str, ...]]], dict[tuple[str, ...], str], dict[tuple[str, ...], str]]:
    entries: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
    kinds: dict[tuple[str, ...], str] = {}
    links: dict[tuple[str, ...], str] = {}
    folded: set[tuple[str, ...]] = set()
    regular_bytes = 0
    member_count = 0
    try:
        with tarfile.open(archive, "r:xz") as source:
            for member in source:
                _require(member_count < MAX_MEMBERS, "SDK build dependency archive exceeds member limit.")
                member_count += 1
                _require((member.isdir() or member.isreg() or member.issym()) and not member.issparse(),
                         "SDK build dependency archive contains a special file or hard link.")
                parts = _member_parts(member)
                if not parts:
                    continue
                folded_parts = tuple(part.casefold() for part in parts)
                _require(parts not in kinds and folded_parts not in folded, "SDK build dependency archive has duplicate paths.")
                folded.add(folded_parts)
                if member.isdir():
                    kind = "dir"
                elif member.isreg():
                    _require(member.size >= 0 and regular_bytes <= MAX_REGULAR_BYTES - member.size,
                             "SDK build dependency archive exceeds regular-file size limit.")
                    regular_bytes += member.size
                    kind = "file"
                else:
                    _validate_link_target(member.linkname)
                    kind = "link"
                kinds[parts] = kind
                if kind == "link":
                    links[parts] = member.linkname
                entries.append((member, parts))
    except (tarfile.TarError, OSError) as error:
        raise ValueError("SDK build dependency archive could not be inspected.") from error
    _require(entries, "SDK build dependency archive is empty.")
    _validate_tree(kinds, links)
    return entries, kinds, links


def _validate_link_target(target: object) -> None:
    _require(isinstance(target, str) and target and "/" not in target and "\\" not in target and ":" not in target and "\x00" not in target,
             "SDK build dependency archive symlink target is unsafe.")
    _require(target not in {".", ".."}, "SDK build dependency archive symlink target is unsafe.")


def _validate_tree(kinds: dict[tuple[str, ...], str], links: dict[tuple[str, ...], str]) -> None:
    for parts, kind in kinds.items():
        for length in range(1, len(parts)):
            ancestor = parts[:length]
            _require(kinds.get(ancestor) != "file" and kinds.get(ancestor) != "link",
                     "SDK build dependency archive has a file or link with children.")
        if kind != "link":
            continue
        current = parts
        visited: set[tuple[str, ...]] = set()
        depth = 0
        while kinds.get(current) == "link":
            _require(depth < MAX_SYMLINK_CHAIN, "SDK build dependency archive symlink chain exceeds depth limit.")
            _require(current not in visited, "SDK build dependency archive has a cyclic symlink chain.")
            visited.add(current)
            current = current[:-1] + (links[current],)
            depth += 1
        _require(kinds.get(current) == "file", "SDK build dependency archive symlink chain does not end at a regular file.")


def _extract(archive: Path, stage: Path, dependency: BuildDependency) -> None:
    entries, _kinds, _links = _inspect_archive(archive)
    try:
        with tarfile.open(archive, "r:xz") as source:
            for member, parts in entries:
                if not member.isdir() or not parts:
                    continue
                output = stage.joinpath(*parts)
                output.mkdir(parents=True, exist_ok=True)
                os.chmod(output, 0o755)
            for member, parts in entries:
                if not member.isreg():
                    continue
                output = stage.joinpath(*parts)
                output.parent.mkdir(parents=True, exist_ok=True)
                _require(not output.exists() and not output.is_symlink(), "SDK build dependency archive would overwrite a file.")
                stream = source.extractfile(member)
                _require(stream is not None, "SDK build dependency archive file cannot be read.")
                with stream, output.open("xb") as destination:
                    shutil.copyfileobj(stream, destination, length=1024 * 1024)
                os.chmod(output, 0o644 | (stat.S_IMODE(member.mode) & 0o111))
            for member, parts in entries:
                if not member.issym():
                    continue
                output = stage.joinpath(*parts)
                _require(not output.exists() and not output.is_symlink(), "SDK build dependency archive would overwrite a link.")
                output.symlink_to(member.linkname)
    except (tarfile.TarError, OSError) as error:
        raise ValueError("SDK build dependency archive could not be extracted.") from error
    _require((stage / "vcpkg" / "installed" / dependency.triplet).is_dir(), "SDK build dependency archive lacks expected vcpkg installation.")
    _require((stage / "runtime" / dependency.triplet).is_dir(), "SDK build dependency archive lacks expected runtime directory.")
    _require((stage / "maadeps.cmake").is_file() and not (stage / "maadeps.cmake").is_symlink(),
             "SDK build dependency archive lacks regular maadeps.cmake.")


def _write_provenance(stage: Path, dependency: BuildDependency) -> None:
    (stage / "PROVENANCE.json").write_text(
        json.dumps(
            {
                "manifest": "sdk_build_dependencies.json",
                "dependency": {
                    "label": dependency.label,
                    "archive": f"archives/{dependency.archive_name}",
                    "url": dependency.url,
                    "size": dependency.size,
                    "sha256": dependency.sha256,
                },
            },
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )


def prepare_dependencies(label: str, destination: Path | str) -> Path:
    """Prepare one fixed MaaDeps target in a new destination directory."""
    dependencies, manifest = _load_manifest()
    _require(label in dependencies, "SDK build dependency label is not supported.")
    dependency = dependencies[label]
    requested = Path(destination)
    target = requested.parent.resolve(strict=True) / requested.name
    _require(not target.exists() and not target.is_symlink(), "SDK build dependency destination already exists or is a link.")
    parent = target.parent.resolve(strict=True)
    _require(parent.is_dir() and not parent.is_symlink(), "SDK build dependency destination parent must be a real directory.")
    curl = shutil.which("curl")
    _require(curl is not None, "TLS-verifying curl is required for SDK build dependency preparation.")
    stage = Path(tempfile.mkdtemp(prefix=f".{target.name}.stage-", dir=parent))
    try:
        archives = stage / "archives"
        archives.mkdir()
        archive = archives / dependency.archive_name
        _download(curl, dependency, archive)
        _verify_archive(archive, dependency)
        _extract(archive, stage, dependency)
        (stage / "sdk_build_dependencies.json").write_bytes(manifest)
        _write_provenance(stage, dependency)
        _publish_new(stage, target)
        return target
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise
