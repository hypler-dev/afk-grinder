"""Fail-closed loader for recognition-only AFK resource packs.

Schema version 1 is deliberately data-only.  Its exact top-level keys are
``format``, ``schema_version``, ``id``, ``version``, ``min_app_version``,
``provenance``, ``reference_size``, ``setup``, ``assets``, ``anchors``,
``states``, and ``routines``.  Unknown keys are rejected at every level.

Limits are part of this contract: manifest JSON is at most 256 KiB and depth
16; IDs use ``^[a-z][a-z0-9_.-]{0,63}$``; versions are strict ``X.Y.Z``;
reference and PNG images are at most 16 megapixels; each PNG is at most 8 MiB;
all PNGs total at most 32 MiB; there are at most 128 files, 64 assets, 64
anchors, and 32 states.  ``routines`` must be an empty list until reviewed,
engine-owned semantic routines exist in a later milestone.

This module validates declarative recognition data only.  Provenance and
license values remain claims in data, not legal approval.  It performs no
network access, archive extraction, hot update, code import, native image
decode, Maa pipeline loading, or input action.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import struct
from typing import Any, Final
from urllib.parse import urlparse
import zlib


MAX_JSON_BYTES: Final = 256 * 1024
MAX_DEPTH: Final = 16
MAX_NODES: Final = 4096
MAX_COLLECTION_ITEMS: Final = 128
MAX_FILES: Final = 128
MAX_ASSETS: Final = 64
MAX_ANCHORS: Final = 64
MAX_STATES: Final = 32
MAX_ASSET_BYTES: Final = 8 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES: Final = 32 * 1024 * 1024
MAX_IMAGE_PIXELS: Final = 16_000_000
MAX_DIMENSION: Final = 4096
MAX_TEXT_BYTES: Final = 4096
MAX_TREE_ENTRIES: Final = 256
MAX_TREE_DEPTH: Final = 16
MAX_PNG_CHUNKS: Final = 4096

_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_LANGUAGE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


class PackError(ValueError):
    """Raised when an untrusted pack violates this loader's contract."""


@dataclass(frozen=True, slots=True)
class Provenance:
    source: str
    revision: str
    license: str
    attribution: str


@dataclass(frozen=True, slots=True)
class Setup:
    language: str
    instructions: str
    min_content_size: tuple[int, int]


@dataclass(frozen=True, slots=True)
class Asset:
    id: str
    path: str
    sha256: str
    data: bytes


@dataclass(frozen=True, slots=True)
class Anchor:
    id: str
    asset: str
    roi: tuple[int, int, int, int]
    threshold: float
    scale_range: tuple[float, float]


@dataclass(frozen=True, slots=True)
class State:
    id: str
    positive: tuple[str, ...]
    exclude: tuple[str, ...]
    stable_frames: int


@dataclass(frozen=True, slots=True)
class ResourcePack:
    id: str
    version: str
    min_app_version: str
    provenance: Provenance
    reference_size: tuple[int, int]
    setup: Setup
    assets: tuple[Asset, ...]
    anchors: tuple[Anchor, ...]
    states: tuple[State, ...]


@dataclass(slots=True)
class _Root:
    path: Path
    identity: tuple[int, int]
    descriptor: int | None

    @property
    def descriptor_pinned(self) -> bool:
        return self.descriptor is not None

    def close(self) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None


def load_pack(
    directory: str | os.PathLike[str],
    app_version: str = "0.1.0",
    *,
    curated_base: str | os.PathLike[str] | None = None,
) -> ResourcePack:
    """Read one local directory pack, validating manifest and listed PNG bytes.

    The caller supplies a directory, never an archive or URL.  Without
    ``curated_base``, that selected directory is the trust boundary.  With a
    curated base, its canonical directory bounds the selected root and every
    component from that base to the root must be a real directory.  This
    canonicalization preserves legitimate macOS ``/tmp`` aliases while still
    rejecting symlink traversal below the trusted base.

    POSIX platforms pin the root directory file descriptor for the whole load.
    Platforms without ``dir_fd`` support re-check path identities before and
    after loading, but cannot provide the same directory-object pinning.
    """
    _parse_semver(app_version, "app_version")
    root = _open_root(directory, curated_base)
    try:
        manifest_bytes = _read_regular(root, "pack.json", MAX_JSON_BYTES)
        payload = _parse_manifest(manifest_bytes)
        pack = _validate_manifest(payload, app_version)
        asset_data: dict[str, bytes] = {}
        total_size = 0
        for asset in pack.assets:
            data = _read_regular(root, asset.path, MAX_ASSET_BYTES)
            total_size += len(data)
            if total_size > MAX_TOTAL_ASSET_BYTES:
                raise PackError("total asset bytes exceed limit")
            _validate_png(data, asset.path)
            digest = hashlib.sha256(data).hexdigest()
            if digest != asset.sha256:
                raise PackError(f"asset hash mismatch: {asset.path}")
            asset_data[asset.id] = data
        _check_pack_tree(root, {asset.path for asset in pack.assets})
        _ensure_root_unchanged(root)
        return ResourcePack(
            id=pack.id,
            version=pack.version,
            min_app_version=pack.min_app_version,
            provenance=pack.provenance,
            reference_size=pack.reference_size,
            setup=pack.setup,
            assets=tuple(Asset(asset.id, asset.path, asset.sha256, asset_data[asset.id]) for asset in pack.assets),
            anchors=pack.anchors,
            states=pack.states,
        )
    finally:
        root.close()


def _open_root(directory: str | os.PathLike[str], curated_base: str | os.PathLike[str] | None) -> _Root:
    requested = Path(directory)
    if curated_base is not None:
        root = _curated_root(requested, Path(curated_base))
    else:
        root = requested
    try:
        before = root.lstat()
    except OSError as exc:
        raise PackError("pack root is unavailable") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise PackError("pack root must be a real directory")
    descriptor: int | None = None
    if os.open in os.supports_dir_fd:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(root, flags)
        except OSError as exc:
            raise PackError("cannot pin pack root") from exc
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or not _same_identity(before, opened):
            os.close(descriptor)
            raise PackError("pack root changed while opening")
    return _Root(root, (before.st_dev, before.st_ino), descriptor)


def _curated_root(requested: Path, base_input: Path) -> Path:
    try:
        base = base_input.resolve(strict=True)
        selected = requested.resolve(strict=True)
    except OSError as exc:
        raise PackError("curated base or pack root is unavailable") from exc
    if not base.is_dir():
        raise PackError("curated base must be a directory")
    try:
        selected.relative_to(base)
    except ValueError as exc:
        raise PackError("pack root escapes curated base") from exc
    raw_base = base_input.absolute()
    raw_selected = requested.absolute()
    try:
        below_raw_base = raw_selected.relative_to(raw_base)
    except ValueError:
        below_raw_base = None
    if below_raw_base is not None and base.joinpath(*below_raw_base.parts) != selected:
        raise PackError("symlink traversal below curated base is forbidden")
    current = base
    for part in selected.relative_to(base).parts:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise PackError("curated pack component is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise PackError("curated pack path must use real directories")
    return selected


def _ensure_root_unchanged(root: _Root) -> None:
    try:
        current = root.path.lstat()
    except OSError as exc:
        raise PackError("pack root disappeared during load") from exc
    if stat.S_ISLNK(current.st_mode) or not _same_identity_tuple(root.identity, current):
        raise PackError("pack root changed during load")


def _read_regular(root: _Root, relative: str, limit: int) -> bytes:
    path = root.path.joinpath(*PurePosixPath(relative).parts)
    try:
        before = _relative_lstat(root, relative) if root.descriptor_pinned else path.lstat()
    except OSError as exc:
        raise PackError(f"missing required file: {relative}") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise PackError(f"file must be a non-linked regular file: {relative}")
    if before.st_size > limit:
        raise PackError(f"file exceeds size limit: {relative}")
    try:
        descriptor = _open_beneath_root(root, relative)
    except OSError as exc:
        raise PackError(f"cannot open required file: {relative}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1 or not _same_file(before, opened):
            raise PackError(f"file changed while opening: {relative}")
        data = _read_limited(descriptor, limit)
        after = os.fstat(descriptor)
        if not _same_file(opened, after):
            raise PackError(f"file changed while reading: {relative}")
        return data
    finally:
        os.close(descriptor)


def _relative_lstat(root: _Root, relative: str) -> os.stat_result:
    assert root.descriptor is not None
    try:
        return os.stat(relative, dir_fd=root.descriptor, follow_symlinks=False)
    except OSError as exc:
        raise PackError(f"missing required file: {relative}") from exc


def _open_beneath_root(root: _Root, relative: str) -> int:
    """Open a relative leaf through directory descriptors when available.

    A descriptor walk pins each ancestor while the next component is opened,
    preventing a checked directory from being swapped for a symlink on POSIX.
    Windows lacks ``dir_fd`` support, so its fallback repeats no-link ancestor
    validation and still rejects a changed leaf by inode/stat comparison.
    """
    parts = PurePosixPath(relative).parts
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    read_only = os.O_RDONLY | no_follow
    if not root.descriptor_pinned:
        _assert_ancestors(root.path, root.path.joinpath(*parts).parent)
        return os.open(root.path.joinpath(*parts), read_only)
    assert root.descriptor is not None
    directory_flags = read_only | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.dup(root.descriptor)
    try:
        for part in parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        leaf = os.open(parts[-1], read_only, dir_fd=descriptor)
    finally:
        os.close(descriptor)
    return leaf


def _assert_ancestors(root: Path, parent: Path) -> None:
    try:
        relative = parent.relative_to(root)
    except ValueError as exc:
        raise PackError("file escapes pack root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except OSError as exc:
            raise PackError("asset ancestor is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise PackError("asset ancestor is not a real directory")


def _read_limited(descriptor: int, limit: int) -> bytes:
    chunks: list[bytes] = []
    remaining = limit + 1
    while remaining:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    data = b"".join(chunks)
    if len(data) > limit:
        raise PackError("file exceeds size limit")
    return data


def _same_file(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino and first.st_size == second.st_size


def _same_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _same_identity_tuple(first: tuple[int, int], second: os.stat_result) -> bool:
    return first == (second.st_dev, second.st_ino)


def _parse_manifest(data: bytes) -> dict[str, Any]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PackError("pack.json must be UTF-8") from exc
    _check_json_structure(text)
    try:
        payload = json.loads(text, object_pairs_hook=_no_duplicate_keys, parse_constant=_reject_json_constant)
    except (json.JSONDecodeError, TypeError, ValueError, OverflowError, RecursionError, PackError) as exc:
        raise PackError("pack.json is invalid JSON") from exc
    _validate_tree(payload)
    if not isinstance(payload, dict):
        raise PackError("pack.json must be an object")
    return payload


def _check_json_structure(text: str) -> None:
    """Bound nesting before CPython's recursive JSON parser sees it."""
    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > MAX_DEPTH:
                raise PackError("JSON nesting exceeds limit")
        elif character in "]}":
            depth -= 1
            if depth < 0:
                raise PackError("JSON has unbalanced containers")


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PackError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise PackError(f"non-finite JSON value: {value}")


def _validate_tree(value: Any, depth: int = 1, nodes: list[int] | None = None) -> None:
    nodes = [0] if nodes is None else nodes
    nodes[0] += 1
    if nodes[0] > MAX_NODES:
        raise PackError("JSON has too many nodes")
    if depth > MAX_DEPTH:
        raise PackError("JSON nesting exceeds limit")
    if isinstance(value, dict):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise PackError("JSON object has too many fields")
        for key, child in value.items():
            if not isinstance(key, str):
                raise PackError("JSON keys must be strings")
            _validate_tree(child, depth + 1, nodes)
    elif isinstance(value, list):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise PackError("JSON list has too many items")
        for child in value:
            _validate_tree(child, depth + 1, nodes)
    elif isinstance(value, float) and not math.isfinite(value):
        raise PackError("non-finite number")


def _validate_manifest(payload: dict[str, Any], app_version: str) -> ResourcePack:
    _keys(payload, {"format", "schema_version", "id", "version", "min_app_version", "provenance", "reference_size", "setup", "assets", "anchors", "states", "routines"}, "manifest")
    if payload["format"] != "afk-resource-pack" or _integer(payload["schema_version"], "schema_version") != 1:
        raise PackError("unsupported pack format or schema version")
    pack_id = _id(payload["id"], "id")
    version = _parse_semver(payload["version"], "version")
    min_app_version = _parse_semver(payload["min_app_version"], "min_app_version")
    if _semver_tuple(app_version) < _semver_tuple(min_app_version):
        raise PackError("pack requires a newer app version")
    provenance = _provenance(payload["provenance"])
    reference_size = _size(payload["reference_size"], "reference_size")
    setup = _setup(payload["setup"], reference_size)
    routines = _list(payload["routines"], "routines", 0)
    if routines:
        raise PackError("routines are not enabled for this schema")
    assets = _assets(payload["assets"])
    anchors = _anchors(payload["anchors"], assets, reference_size)
    states = _states(payload["states"], anchors)
    return ResourcePack(pack_id, version, min_app_version, provenance, reference_size, setup, assets, anchors, states)


def _keys(value: Any, expected: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != expected:
        raise PackError(f"{label} has missing or unknown fields")
    return value


def _provenance(value: Any) -> Provenance:
    item = _keys(value, {"source", "revision", "license", "attribution"}, "provenance")
    source = _text(item["source"], "provenance.source", 2048, ascii_only=True)
    parsed = urlparse(source)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise PackError("provenance.source must be an HTTPS URL")
    revision = _text(item["revision"], "provenance.revision", 40, ascii_only=True)
    if not _REVISION_RE.fullmatch(revision):
        raise PackError("provenance.revision must be 40 hexadecimal characters")
    license_value = _text(item["license"], "provenance.license", 200, ascii_only=True)
    attribution = _text(item["attribution"], "provenance.attribution", 1024)
    return Provenance(source, revision, license_value, attribution)


def _setup(value: Any, reference_size: tuple[int, int]) -> Setup:
    item = _keys(value, {"language", "instructions", "min_content_size"}, "setup")
    language = _text(item["language"], "setup.language", 32, ascii_only=True)
    if not _LANGUAGE_RE.fullmatch(language):
        raise PackError("setup.language must be bounded ASCII")
    instructions = _text(item["instructions"], "setup.instructions", MAX_TEXT_BYTES)
    min_content_size = _size(item["min_content_size"], "setup.min_content_size")
    if min_content_size[0] > reference_size[0] or min_content_size[1] > reference_size[1]:
        raise PackError("setup.min_content_size exceeds reference_size")
    return Setup(language, instructions, min_content_size)


def _assets(value: Any) -> tuple[Asset, ...]:
    items = _list(value, "assets", MAX_ASSETS)
    result: list[Asset] = []
    seen: set[str] = set()
    paths: set[str] = set()
    for index, raw in enumerate(items):
        item = _keys(raw, {"id", "path", "sha256"}, f"assets[{index}]")
        asset_id = _id(item["id"], f"assets[{index}].id")
        path = _asset_path(item["path"])
        digest = _text(item["sha256"], f"assets[{index}].sha256", 64, ascii_only=True)
        if not _SHA256_RE.fullmatch(digest):
            raise PackError("asset SHA-256 must be lowercase hexadecimal")
        if asset_id in seen or path in paths:
            raise PackError("asset IDs and paths must be unique")
        seen.add(asset_id)
        paths.add(path)
        result.append(Asset(asset_id, path, digest, b""))
    return tuple(result)


def _anchors(value: Any, assets: tuple[Asset, ...], reference_size: tuple[int, int]) -> tuple[Anchor, ...]:
    items = _list(value, "anchors", MAX_ANCHORS)
    asset_ids = {asset.id for asset in assets}
    result: list[Anchor] = []
    seen: set[str] = set()
    for index, raw in enumerate(items):
        item = _keys(raw, {"id", "asset", "roi", "threshold", "scale_range"}, f"anchors[{index}]")
        anchor_id = _id(item["id"], f"anchors[{index}].id")
        asset = _id(item["asset"], f"anchors[{index}].asset")
        if asset not in asset_ids:
            raise PackError("anchor references an unknown asset")
        roi = _roi(item["roi"], reference_size)
        threshold = _number(item["threshold"], f"anchors[{index}].threshold")
        if not 0 <= threshold <= 1:
            raise PackError("anchor threshold must be in [0, 1]")
        scale = _number_pair(item["scale_range"], f"anchors[{index}].scale_range")
        if scale[0] < 0.25 or scale[1] > 4 or scale[0] > scale[1]:
            raise PackError("anchor scale range must be within 0.25..4")
        if anchor_id in seen:
            raise PackError("anchor IDs must be unique")
        seen.add(anchor_id)
        result.append(Anchor(anchor_id, asset, roi, threshold, scale))
    return tuple(result)


def _states(value: Any, anchors: tuple[Anchor, ...]) -> tuple[State, ...]:
    items = _list(value, "states", MAX_STATES)
    anchor_ids = {anchor.id for anchor in anchors}
    result: list[State] = []
    seen: set[str] = set()
    for index, raw in enumerate(items):
        item = _keys(raw, {"id", "positive", "exclude", "stable_frames"}, f"states[{index}]")
        state_id = _id(item["id"], f"states[{index}].id")
        positive = _references(item["positive"], f"states[{index}].positive", anchor_ids, nonempty=True)
        exclude = _references(item["exclude"], f"states[{index}].exclude", anchor_ids, nonempty=False)
        if set(positive) & set(exclude):
            raise PackError("state positive and exclude references overlap")
        stable_frames = _integer(item["stable_frames"], f"states[{index}].stable_frames")
        if not 2 <= stable_frames <= 5:
            raise PackError("state stable_frames must be 2..5")
        if state_id in seen:
            raise PackError("state IDs must be unique")
        seen.add(state_id)
        result.append(State(state_id, positive, exclude, stable_frames))
    return tuple(result)


def _asset_path(value: Any) -> str:
    path = _text(value, "asset path", 512, ascii_only=True)
    if "\\" in path or "://" in path or path.startswith("/"):
        raise PackError("asset path must be relative POSIX data")
    parsed = PurePosixPath(path)
    if parsed.parts[:1] != ("assets",) or any(part in {"", ".", ".."} for part in parsed.parts) or path != parsed.as_posix():
        raise PackError("asset path must stay under assets/")
    if parsed.suffix != ".png":
        raise PackError("asset path must name a PNG")
    return path


def _roi(value: Any, reference_size: tuple[int, int]) -> tuple[int, int, int, int]:
    fields = _list(value, "roi", 4)
    if len(fields) != 4:
        raise PackError("roi must have four integers")
    x, y, width, height = (_integer(field, "roi value") for field in fields)
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > reference_size[0] or y + height > reference_size[1]:
        raise PackError("roi is outside reference_size")
    return x, y, width, height


def _references(value: Any, label: str, allowed: set[str], *, nonempty: bool) -> tuple[str, ...]:
    fields = _list(value, label, MAX_ANCHORS)
    if nonempty and not fields:
        raise PackError("state positive evidence cannot be empty")
    references = tuple(_id(field, label) for field in fields)
    if len(set(references)) != len(references) or any(reference not in allowed for reference in references):
        raise PackError("state has duplicate or unknown anchor references")
    return references


def _size(value: Any, label: str) -> tuple[int, int]:
    fields = _list(value, label, 2)
    if len(fields) != 2:
        raise PackError(f"{label} must have width and height")
    width, height = (_integer(field, label) for field in fields)
    if width <= 0 or height <= 0 or width > MAX_DIMENSION or height > MAX_DIMENSION or width * height > MAX_IMAGE_PIXELS:
        raise PackError(f"{label} exceeds dimension limits")
    return width, height


def _number_pair(value: Any, label: str) -> tuple[float, float]:
    fields = _list(value, label, 2)
    if len(fields) != 2:
        raise PackError(f"{label} must have two numbers")
    return _number(fields[0], label), _number(fields[1], label)


def _list(value: Any, label: str, maximum: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > maximum:
        raise PackError(f"{label} must be a bounded list")
    return value


def _id(value: Any, label: str) -> str:
    text = _text(value, label, 64, ascii_only=True)
    if not _ID_RE.fullmatch(text):
        raise PackError(f"{label} has an invalid ID")
    return text


def _text(value: Any, label: str, maximum: int, *, ascii_only: bool = False) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > maximum:
        raise PackError(f"{label} must be nonempty bounded text")
    if ascii_only and not value.isascii():
        raise PackError(f"{label} must be ASCII")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise PackError(f"{label} contains control characters")
    return value


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PackError(f"{label} must be an integer")
    return value


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PackError(f"{label} must be a finite number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise PackError(f"{label} must be a finite number") from exc
    if not math.isfinite(number):
        raise PackError(f"{label} must be a finite number")
    return number


def _parse_semver(value: Any, label: str) -> str:
    text = _text(value, label, 64, ascii_only=True)
    if not _SEMVER_RE.fullmatch(text):
        raise PackError(f"{label} must be strict semantic version X.Y.Z")
    return text


def _semver_tuple(value: str) -> tuple[int, int, int]:
    return tuple(int(part) for part in value.split("."))  # type: ignore[return-value]


def _validate_png(data: bytes, path: str) -> None:
    """Validate bounded PNG chunk structure without decoding pixel bytes."""
    if not data.startswith(_PNG_SIGNATURE):
        raise PackError(f"asset is not a PNG: {path}")
    offset = len(_PNG_SIGNATURE)
    chunks = 0
    seen_ihdr = False
    seen_plte = False
    seen_idat = False
    ended_idat = False
    colour_type: int | None = None
    while offset < len(data):
        if chunks >= MAX_PNG_CHUNKS or offset + 12 > len(data):
            raise PackError(f"PNG chunk structure is invalid: {path}")
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            raise PackError(f"PNG chunk is truncated: {path}")
        chunk_type = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        expected_crc = struct.unpack(">I", data[offset + 8 + length:end])[0]
        actual_crc = zlib.crc32(payload, zlib.crc32(chunk_type)) & 0xFFFFFFFF
        if actual_crc != expected_crc:
            raise PackError(f"PNG chunk CRC is invalid: {path}")
        chunks += 1
        if not seen_ihdr:
            if chunk_type != b"IHDR" or length != 13:
                raise PackError(f"PNG must start with IHDR: {path}")
            width, height, bit_depth, colour_type, compression, filter_method, interlace = struct.unpack(">IIBBBBB", payload)
            if width == 0 or height == 0 or width * height > MAX_IMAGE_PIXELS:
                raise PackError(f"PNG dimensions exceed limit: {path}")
            valid_depths = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if bit_depth not in valid_depths.get(colour_type, set()) or compression != 0 or filter_method != 0 or interlace not in {0, 1}:
                raise PackError(f"PNG IHDR fields are invalid: {path}")
            seen_ihdr = True
        elif chunk_type == b"IHDR":
            raise PackError(f"PNG has duplicate IHDR: {path}")
        elif chunk_type == b"PLTE":
            if seen_idat or seen_plte or not 3 <= length <= 768 or length % 3:
                raise PackError(f"PNG palette is invalid: {path}")
            seen_plte = True
        elif chunk_type == b"IDAT":
            if ended_idat or (colour_type == 3 and not seen_plte):
                raise PackError(f"PNG image data order is invalid: {path}")
            seen_idat = True
        elif chunk_type == b"IEND":
            if length != 0 or not seen_idat or end != len(data):
                raise PackError(f"PNG ending is invalid: {path}")
            return
        elif seen_idat:
            ended_idat = True
        offset = end
    raise PackError(f"PNG has no IEND: {path}")


def _check_pack_tree(root: _Root, asset_paths: set[str]) -> None:
    seen_files: set[str] = set()
    allowed_directories = {"assets"}
    for asset_path in asset_paths:
        parent = PurePosixPath(asset_path).parent
        while parent != PurePosixPath("."):
            allowed_directories.add(parent.as_posix())
            parent = parent.parent
    entries = [0]
    if root.descriptor_pinned:
        assert root.descriptor is not None
        _scan_descriptor_tree(os.dup(root.descriptor), "", allowed_directories, seen_files, entries, 0)
    else:
        _scan_path_tree(root, root.path, "", allowed_directories, seen_files, entries, 0)
    allowed = {"pack.json", "LICENSE", "LICENSE.txt", *asset_paths}
    if seen_files != allowed & seen_files or not asset_paths.issubset(seen_files) or "pack.json" not in seen_files:
        raise PackError("pack contains missing or unlisted files")
    if len(seen_files) > MAX_FILES:
        raise PackError("pack has too many files")


def _count_tree_entry(entries: list[int]) -> None:
    entries[0] += 1
    if entries[0] > MAX_TREE_ENTRIES:
        raise PackError("pack tree has too many entries")


def _scan_descriptor_tree(descriptor: int, prefix: str, allowed_directories: set[str], seen_files: set[str], entries: list[int], depth: int) -> None:
    if depth > MAX_TREE_DEPTH:
        os.close(descriptor)
        raise PackError("pack tree exceeds directory depth limit")
    try:
        with os.scandir(os.dup(descriptor)) as scan:
            for entry in scan:
                _count_tree_entry(entries)
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise PackError("symlinks are forbidden in packs")
                if stat.S_ISDIR(info.st_mode):
                    if relative not in allowed_directories:
                        raise PackError("pack contains an unlisted directory")
                    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
                    child = os.open(entry.name, flags, dir_fd=descriptor)
                    _scan_descriptor_tree(child, relative, allowed_directories, seen_files, entries, depth + 1)
                elif stat.S_ISREG(info.st_mode):
                    if info.st_nlink != 1:
                        raise PackError("hardlinked files are forbidden in packs")
                    seen_files.add(relative)
                else:
                    raise PackError("pack contains a non-regular file")
    except OSError as exc:
        raise PackError("cannot inspect pack directory") from exc
    finally:
        os.close(descriptor)


def _scan_path_tree(root: _Root, directory: Path, prefix: str, allowed_directories: set[str], seen_files: set[str], entries: list[int], depth: int) -> None:
    if depth > MAX_TREE_DEPTH:
        raise PackError("pack tree exceeds directory depth limit")
    _assert_ancestors(root.path, directory)
    try:
        with os.scandir(directory) as scan:
            for entry in scan:
                _count_tree_entry(entries)
                relative = f"{prefix}/{entry.name}" if prefix else entry.name
                info = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise PackError("symlinks are forbidden in packs")
                if stat.S_ISDIR(info.st_mode):
                    if relative not in allowed_directories:
                        raise PackError("pack contains an unlisted directory")
                    _scan_path_tree(root, directory / entry.name, relative, allowed_directories, seen_files, entries, depth + 1)
                elif stat.S_ISREG(info.st_mode):
                    if info.st_nlink != 1:
                        raise PackError("hardlinked files are forbidden in packs")
                    seen_files.add(relative)
                else:
                    raise PackError("pack contains a non-regular file")
    except OSError as exc:
        raise PackError("cannot inspect pack directory") from exc
