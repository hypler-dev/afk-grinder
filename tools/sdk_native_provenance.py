"""Audit direct Maa SDK native groups against pinned notices and source recipes.

This developer-only command reads inventories, manifests, retained source archives,
and retained notices.  It does not extract archives, execute SDK code, build, fetch,
install, publish, or change SDK publication policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile
from typing import Any

from tools import fetch_sdk_sources
from tools.sdk_build_dependencies import _parse_manifest


LABELS = ("macos-arm64", "macos-x64", "windows-x64")
MAX_INVENTORY_BYTES = 4 * 1024 * 1024
MAX_MAPPING_BYTES = 256 * 1024
MAX_NOTICE_MANIFEST_BYTES = 512 * 1024
MAX_SOURCE_MANIFEST_BYTES = 64 * 1024
MAX_BUILD_MANIFEST_BYTES = 64 * 1024
MAX_NOTICE_BYTES = 1024 * 1024
MAX_NATIVE_GROUPS = 512
MAX_GROUP_PATHS = 16
MAX_GROUP_BYTES = 128 * 1024 * 1024
MAX_TOTAL_GROUP_BYTES = 512 * 1024 * 1024
MAX_COMPONENTS = 16
MAX_TARGET_GROUPS = 64
_SCOPE = "direct-sdk-native-notice-traceability"
_SDK_VERSION = "5.14.3"
_EVIDENCE_SCOPE = "Direct SDK native/notice/recipe traceability only; not legal compliance or complete transitive source."
_SOURCE_EVIDENCE = {"pinned-source-archive", "recipe-only", "vendor-binary-source-unresolved"}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _hex(value: object, length: int) -> bool:
    return isinstance(value, str) and len(value) == length and all(item in "0123456789abcdef" for item in value)


def _strict_json(path: Path, limit: int, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        mode = path.lstat()
    except OSError as error:
        raise ValueError(f"{label} cannot be read.") from error
    _require(stat.S_ISREG(mode.st_mode) and mode.st_nlink == 1 and mode.st_size <= limit,
             f"{label} must be a bounded non-linked regular file.")

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            _require(isinstance(key, str) and key not in result, f"{label} contains duplicate JSON keys.")
            result[key] = value
        return result

    def finite(value: str) -> float:
        parsed = float(value)
        _require(math.isfinite(parsed), f"{label} contains a non-finite number.")
        return parsed

    try:
        data = path.read_bytes()
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_float=finite,
                           parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        raise ValueError(f"{label} must be strict JSON.") from None
    _require(type(value) is dict, f"{label} must be a JSON object.")
    return value, data


def _safe_relative(value: object, label: str) -> str:
    _require(isinstance(value, str) and 0 < len(value) <= 512, f"{label} path is invalid.")
    path = PurePosixPath(value)
    _require("\\" not in value and "\x00" not in value and ":" not in value
             and path.as_posix() == value and not path.is_absolute() and path.parts
             and all(part not in {"", ".", ".."} for part in path.parts), f"{label} path is unsafe.")
    return value


def _safe_flat_name(value: object, label: str) -> str:
    name = _safe_relative(value, label)
    _require("/" not in name and "\\" not in name, f"{label} filename must be flat.")
    return name


def _repo_file(repo: Path, relative: str, limit: int, label: str) -> tuple[dict[str, Any], bytes]:
    _require(repo.is_dir() and not repo.is_symlink(), "Repository root must be a real directory.")
    return _strict_json(repo / relative, limit, label)


def _mapping(raw: dict[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version", "scope", "sdk_version", "reference_inventory_commit", "source_manifest_sha256",
        "build_dependency_manifest_sha256", "components", "targets",
    }
    _require(set(raw) == fields, "SDK native provenance mapping has unexpected fields.")
    _require(type(raw["schema_version"]) is int and raw["schema_version"] == 1,
             "SDK native provenance mapping schema version is unsupported.")
    _require(raw["scope"] == _SCOPE and raw["sdk_version"] == _SDK_VERSION,
             "SDK native provenance mapping identity is invalid.")
    for field in ("reference_inventory_commit",):
        _require(_hex(raw[field], 40), "SDK native provenance mapping commit is invalid.")
    for field in ("source_manifest_sha256", "build_dependency_manifest_sha256"):
        _require(_hex(raw[field], 64), "SDK native provenance mapping manifest SHA-256 is invalid.")

    components = raw["components"]
    _require(type(components) is dict and 1 <= len(components) <= MAX_COMPONENTS,
             "SDK native provenance mapping components are invalid.")
    parsed_components: dict[str, dict[str, Any]] = {}
    expected_component = {"source_component", "source_evidence", "identity", "recipes", "notices", "limitations"}
    source_names = {"MaaFramework", "MaaUtils", "MaaDeps", "vcpkg"}
    for component_id, entry in components.items():
        _require(isinstance(component_id, str) and component_id and len(component_id) <= 128,
                 "SDK native provenance mapping component id is invalid.")
        _require(type(entry) is dict and set(entry) == expected_component,
                 "SDK native provenance mapping component has unexpected fields.")
        _require(entry["source_component"] in source_names and entry["source_evidence"] in _SOURCE_EVIDENCE,
                 "SDK native provenance mapping component source evidence is invalid.")
        _require(isinstance(entry["identity"], str) and 0 < len(entry["identity"]) <= 256,
                 "SDK native provenance mapping component identity is invalid.")
        recipes = entry["recipes"]
        _require(type(recipes) is list and 1 <= len(recipes) <= 4,
                 "SDK native provenance mapping recipes are invalid.")
        parsed_recipes: list[dict[str, str]] = []
        seen_recipes: set[str] = set()
        for recipe in recipes:
            _require(type(recipe) is dict and set(recipe) == {"path", "sha256"},
                     "SDK native provenance mapping recipe has unexpected fields.")
            recipe_path = _safe_relative(recipe["path"], "SDK native provenance mapping recipe")
            _require(recipe_path not in seen_recipes and _hex(recipe["sha256"], 64),
                     "SDK native provenance mapping recipe is invalid.")
            seen_recipes.add(recipe_path)
            parsed_recipes.append({"path": recipe_path, "sha256": recipe["sha256"]})
        notices = entry["notices"]
        _require(type(notices) is list and 1 <= len(notices) <= 8,
                 "SDK native provenance mapping notices are invalid.")
        parsed_notices = [_safe_flat_name(notice, "SDK native provenance mapping notice") for notice in notices]
        _require(len(parsed_notices) == len(set(parsed_notices)), "SDK native provenance mapping notices are duplicate.")
        limitations = entry["limitations"]
        _require(type(limitations) is list and len(limitations) <= 16
                 and all(isinstance(item, str) and 0 < len(item) <= 256 for item in limitations),
                 "SDK native provenance mapping limitations are invalid.")
        parsed_components[component_id] = {**entry, "recipes": parsed_recipes, "notices": parsed_notices}

    targets = raw["targets"]
    _require(type(targets) is dict and set(targets) == set(LABELS),
             "SDK native provenance mapping target labels are invalid.")
    parsed_targets: dict[str, list[dict[str, Any]]] = {}
    entry_fields = {"component", "paths", "sha256", "size_bytes"}
    for label in LABELS:
        records = targets[label]
        _require(type(records) is list and 1 <= len(records) <= MAX_TARGET_GROUPS,
                 "SDK native provenance mapping target records are invalid.")
        parsed: list[dict[str, Any]] = []
        for record in records:
            _require(type(record) is dict and set(record) == entry_fields,
                     "SDK native provenance mapping target record has unexpected fields.")
            _require(record["component"] in parsed_components and _hex(record["sha256"], 64),
                     "SDK native provenance mapping target component or SHA-256 is invalid.")
            _require(type(record["size_bytes"]) is int and 0 < record["size_bytes"] <= MAX_GROUP_BYTES,
                     "SDK native provenance mapping target size is invalid.")
            _require(type(record["paths"]) is list, "SDK native provenance mapping target paths are invalid.")
            paths = [_safe_relative(path, "SDK native provenance mapping target") for path in record["paths"]]
            _require(1 <= len(paths) <= MAX_GROUP_PATHS and paths == sorted(paths) and len(paths) == len(set(paths)),
                     "SDK native provenance mapping target paths are invalid.")
            parsed.append({**record, "paths": paths})
        parsed_targets[label] = parsed
    return {**raw, "components": parsed_components, "targets": parsed_targets}


def _inventory(raw: dict[str, Any], label: str, commit: str) -> list[dict[str, Any]]:
    fields = {"schema_version", "source", "evidence_scope", "executable", "embedded_modules", "native_files", "legal_files", "sdk_presence"}
    _require(set(raw) == fields and raw["schema_version"] == "sdk-inventory.v2", "SDK inventory schema is invalid.")
    source = raw["source"]
    _require(type(source) is dict and set(source) == {"commit", "label"} and source["label"] == label
             and source["commit"] == commit, "SDK inventory label or commit does not match request.")
    presence = raw["sdk_presence"]
    _require(type(presence) is dict and set(presence) == {"required", "maa_modules", "maaframework_native_paths", "maaagentbinary_present"}
             and presence["required"] is True and presence["maaagentbinary_present"] is False
             and type(presence["maa_modules"]) is list and "maa" in presence["maa_modules"]
             and type(presence["maaframework_native_paths"]) is list and presence["maaframework_native_paths"],
             "SDK inventory SDK presence is invalid.")
    native = raw["native_files"]
    _require(type(native) is list and len(native) <= MAX_NATIVE_GROUPS, "SDK inventory native groups are invalid.")
    parsed: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    total_bytes = 0
    for record in native:
        _require(type(record) is dict and set(record) == {"paths", "sha256", "size_bytes"},
                 "SDK inventory native group has unexpected fields.")
        _require(type(record["size_bytes"]) is int and 0 < record["size_bytes"] <= MAX_GROUP_BYTES and _hex(record["sha256"], 64),
                 "SDK inventory native group hash or size is invalid.")
        _require(type(record["paths"]) is list, "SDK inventory native group paths are invalid.")
        paths = [_safe_relative(path, "SDK inventory native group") for path in record["paths"]]
        _require(1 <= len(paths) <= MAX_GROUP_PATHS and paths == sorted(paths) and len(paths) == len(set(paths))
                 and not seen_paths.intersection(paths), "SDK inventory native group paths are invalid.")
        seen_paths.update(paths)
        total_bytes += record["size_bytes"]
        _require(total_bytes <= MAX_TOTAL_GROUP_BYTES, "SDK inventory native groups exceed byte limit.")
        parsed.append({**record, "paths": paths})
    return parsed


def _direct_group(record: dict[str, Any]) -> bool:
    for path in record["paths"]:
        folded = path.casefold()
        name = PurePosixPath(path).name.casefold()
        if "/maa/bin/" in f"/{folded}" or name.startswith(("libmaa", "maa")):
            return True
    return False


def _notice_hashes(raw: dict[str, Any]) -> dict[str, str]:
    _require(set(raw) == {"notice_inventory_only", "files"} and raw["notice_inventory_only"] is True
             and type(raw["files"]) is list, "Notice provenance manifest schema is invalid.")
    result: dict[str, str] = {}
    for record in raw["files"]:
        _require(type(record) is dict and set(record).issuperset({"file", "sha256"}),
                 "Notice provenance manifest entry is invalid.")
        name = _safe_flat_name(record["file"], "Notice provenance manifest")
        _require(name not in result and _hex(record["sha256"], 64), "Notice provenance manifest entry is invalid.")
        result[name] = record["sha256"]
    return result


def _hash_regular(path: Path, limit: int, label: str) -> str:
    try:
        mode = path.lstat()
    except OSError as error:
        raise ValueError(f"{label} is missing.") from error
    _require(stat.S_ISREG(mode.st_mode) and mode.st_nlink == 1 and mode.st_size <= limit,
             f"{label} must be a bounded non-linked regular file.")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _archive_recipes(sources: Path, components: dict[str, dict[str, Any]], source_manifest: list[fetch_sdk_sources.SourceComponent]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]]]:
    _require(sources.is_dir() and not sources.is_symlink(), "Sources directory must be a real directory.")
    archives = sources / "archives"
    _require(archives.is_dir() and not archives.is_symlink(), "Sources archives directory must be a real directory.")
    by_name = {item.name: item for item in source_manifest}
    needed = {entry["source_component"] for entry in components.values()}
    inspected: dict[str, dict[str, tarfile.TarInfo]] = {}
    pins: list[dict[str, Any]] = []
    remaining_bytes = fetch_sdk_sources.MAX_UNPACKED_BYTES
    remaining_members = fetch_sdk_sources.MAX_UNPACKED_MEMBERS
    for source in source_manifest:
        archive = archives / f"{source.name}-{source.commit}.tar.gz"
        _hash_regular(archive, fetch_sdk_sources.MAX_ARCHIVE_BYTES, f"{source.name} source archive")
        fetch_sdk_sources._verify_archive(archive, source)
        entries, bytes_used = fetch_sdk_sources._inspect_archive(archive, source, remaining_bytes, remaining_members)
        remaining_bytes -= bytes_used
        remaining_members -= len(entries)
        inspected[source.name] = {"/".join(parts[1:]): member for member, parts in entries if member.isreg()}
        pins.append({"name": source.name, "commit": source.commit, "sha256": source.sha256, "size_bytes": source.size,
                     "archive_verified": True})
    verified: dict[str, list[dict[str, str]]] = {}
    for component_id, entry in components.items():
        source_name = entry["source_component"]
        _require(source_name in needed and source_name in by_name, "SDK native provenance mapping source component is invalid.")
        recipes: list[dict[str, str]] = []
        archive = archives / f"{by_name[source_name].name}-{by_name[source_name].commit}.tar.gz"
        try:
            with tarfile.open(archive, "r:gz") as opened:
                for recipe in entry["recipes"]:
                    member = inspected[source_name].get(recipe["path"])
                    _require(member is not None and member.size <= 128 * 1024,
                             "SDK native provenance recipe is missing or exceeds size limit.")
                    stream = opened.extractfile(member)
                    _require(stream is not None, "SDK native provenance recipe cannot be read.")
                    with stream:
                        digest = hashlib.sha256(stream.read(128 * 1024 + 1)).hexdigest()
                    _require(digest == recipe["sha256"], "SDK native provenance recipe SHA-256 did not match.")
                    recipes.append({"path": recipe["path"], "sha256": recipe["sha256"]})
        except (tarfile.TarError, OSError) as error:
            raise ValueError("SDK native provenance source archive cannot be inspected.") from error
        verified[component_id] = recipes
    return pins, verified


def _required_notices(components: dict[str, dict[str, Any]], records: list[dict[str, Any]]) -> dict[str, str]:
    required: set[str] = set()
    for record in records:
        required.update(components[record["component"]]["notices"])
    return {name: "" for name in sorted(required)}


def audit(inventory: Path | str, sources: Path | str, label: str, commit: str, *, repo: Path | str | None = None) -> dict[str, Any]:
    """Return a deterministic, data-only direct SDK native provenance report."""
    _require(label in LABELS, "Label must be macos-arm64, macos-x64, or windows-x64.")
    _require(_hex(commit, 40), "Commit must be exactly 40 lowercase hexadecimal characters.")
    root = Path(repo) if repo is not None else Path(__file__).resolve().parents[1]
    mapping_raw, mapping_bytes = _repo_file(root, "tools/sdk_native_provenance.json", MAX_MAPPING_BYTES, "SDK native provenance mapping")
    mapping = _mapping(mapping_raw)
    source_raw, source_bytes = _repo_file(root, "tools/sdk_sources.json", MAX_SOURCE_MANIFEST_BYTES, "SDK source manifest")
    build_raw, build_bytes = _repo_file(root, "tools/sdk_build_dependencies.json", MAX_BUILD_MANIFEST_BYTES, "SDK build dependency manifest")
    _require(hashlib.sha256(source_bytes).hexdigest() == mapping["source_manifest_sha256"],
             "SDK source manifest SHA-256 does not match mapping.")
    _require(hashlib.sha256(build_bytes).hexdigest() == mapping["build_dependency_manifest_sha256"],
             "SDK build dependency manifest SHA-256 does not match mapping.")
    source_manifest = fetch_sdk_sources._validate_manifest(source_raw)
    dependencies = _parse_manifest(build_raw)
    inventory_raw, inventory_bytes = _strict_json(Path(inventory), MAX_INVENTORY_BYTES, "SDK inventory")
    native_groups = _inventory(inventory_raw, label, commit)
    target_records = mapping["targets"][label]
    direct = [record for record in native_groups if _direct_group(record)]
    _require(direct, "SDK inventory has no direct SDK native groups.")
    mapped_paths: set[tuple[str, ...]] = set()
    for record in target_records:
        key = tuple(record["paths"])
        _require(key not in mapped_paths, "SDK native provenance mapping contains duplicate target group paths.")
        mapped_paths.add(key)
    direct_by_paths = {tuple(record["paths"]): record for record in direct}
    _require(set(direct_by_paths) == mapped_paths, "SDK native provenance mapping does not exactly cover direct SDK native groups.")
    matched: list[dict[str, Any]] = []
    for expected in target_records:
        actual = direct_by_paths[tuple(expected["paths"])]
        _require(actual["sha256"] == expected["sha256"] and actual["size_bytes"] == expected["size_bytes"],
                 "SDK inventory direct SDK native group hash or size does not match mapping.")
        component = mapping["components"][expected["component"]]
        matched.append({"component": expected["component"], "paths": expected["paths"], "sha256": expected["sha256"],
                        "size_bytes": expected["size_bytes"], "notices": component["notices"],
                        "source_evidence": component["source_evidence"]})
    _require(len(matched) == len(direct), "SDK native provenance mapping contains a partial alias group.")

    provenance_raw, _provenance_bytes = _repo_file(root, "licenses/provenance.json", MAX_NOTICE_MANIFEST_BYTES, "Notice provenance manifest")
    provenance = _notice_hashes(provenance_raw)
    required = _required_notices(mapping["components"], target_records)
    notice_root = root / "licenses"
    _require(notice_root.is_dir() and not notice_root.is_symlink(), "Retained notices directory must be a real directory.")
    legal = inventory_raw["legal_files"]
    _require(type(legal) is list, "SDK inventory legal files are invalid.")
    legal_hashes: dict[str, str] = {}
    for record in legal:
        _require(type(record) is dict and set(record) == {"path", "sha256"} and _hex(record["sha256"], 64),
                 "SDK inventory legal file is invalid.")
        legal_path = _safe_relative(record["path"], "SDK inventory legal file")
        _require(legal_path not in legal_hashes, "SDK inventory legal files are duplicate.")
        legal_hashes[legal_path] = record["sha256"]
    prefix = "_internal/legal/licenses" if label == "windows-x64" else "Contents/Frameworks/legal/licenses"
    prefixes = [prefix] if label == "windows-x64" else [prefix, "Contents/Resources/legal/licenses"]
    notices: list[dict[str, str]] = []
    for name in required:
        _require(name in provenance, "SDK native provenance notice is missing from notice manifest.")
        expected_hash = provenance[name]
        actual_hash = _hash_regular(notice_root / name, MAX_NOTICE_BYTES, "Retained notice")
        _require(actual_hash == expected_hash, "Retained notice SHA-256 does not match notice manifest.")
        for notice_prefix in prefixes:
            _require(legal_hashes.get(f"{notice_prefix}/{name}") == expected_hash,
                     "SDK inventory is missing a required bundled notice alias.")
        notices.append({"file": name, "sha256": expected_hash})

    pins, recipes = _archive_recipes(Path(sources), mapping["components"], list(source_manifest))
    components_report = [{"component": component_id, "identity": entry["identity"], "source_component": entry["source_component"],
                          "source_evidence": entry["source_evidence"], "notices": entry["notices"],
                          "limitations": entry["limitations"], "recipes_verified": recipes[component_id]}
                         for component_id, entry in sorted(mapping["components"].items())]
    baseline_count = len(native_groups) - len(direct)
    return {
        "schema_version": 1,
        "label": label,
        "commit": commit,
        "reference_inventory_commit": mapping["reference_inventory_commit"],
        "input_manifests": {
            "sdk_native_provenance_sha256": hashlib.sha256(mapping_bytes).hexdigest(),
            "sdk_sources_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "sdk_build_dependencies_sha256": hashlib.sha256(build_bytes).hexdigest(),
            "inventory_sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        },
        "source_pins": pins,
        "target_build_prerequisite": {"label": label, "archive_name": dependencies[label].archive_name,
                                      "sha256": dependencies[label].sha256, "size_bytes": dependencies[label].size,
                                      "triplet": dependencies[label].triplet},
        "matched_native_groups": matched,
        "components": components_report,
        "notices_verified": notices,
        "baseline_excluded_native_group_count": baseline_count,
        "sdk_publication_gate": "closed",
        "source_coverage_complete": False,
        "vendor_archives_verified": False,
        "evidence_scope": _EVIDENCE_SCOPE,
    }


def _write_new(path: Path, report: dict[str, Any]) -> None:
    payload = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        with path.open("xb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
    except FileExistsError as error:
        raise ValueError("Output already exists; refusing to overwrite it.") from error
    except OSError as error:
        raise ValueError("Output cannot be created.") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", required=True, type=Path)
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--label", required=True, choices=LABELS)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(argv)
    try:
        report = audit(arguments.inventory, arguments.sources, arguments.label, arguments.commit)
        _write_new(arguments.output, report)
    except ValueError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
