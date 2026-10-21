"""Explicit-consent, offline training-crop export in a bounded worker.

The candidate is recognition data, never an approved routine. Only selected
train crops are persisted. No model, capture, input or network API is used.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from . import __version__
from .recognition import packs
from .training_packet import MAX_JSON_BYTES, _canonical_packet_json, parse_training_packet

COMPILE_TIMEOUT = 60.0
MAX_RECIPE_BYTES = 128 * 1024
MAX_REPORT_BYTES = 64 * 1024
REPORT_FORMAT = "afk-grinder-training-compilation"
ERROR_CODES = frozenset({
    "consent_required", "dataset_invalid", "recipe_invalid", "fixture_invalid",
    "output_invalid", "worker_failed", "report_invalid", "timeout",
})


class CompilationError(ValueError):
    """A fixed code containing no image, native text or filesystem details."""

    def __init__(self, code: str):
        self.code = code if code in ERROR_CODES else "worker_failed"
        super().__init__(self.code)


def _consent(consent: bool) -> None:
    if consent is not True:
        raise CompilationError("consent_required")


def _read(path: Path, limit: int) -> bytes:
    """Pin a selected regular file and recheck its directory lineage."""
    from .training_fixtures import _capture_lineage, _ensure_lineage_unchanged

    path = Path(path)
    parent = path.parent.resolve(strict=True)
    root = packs._open_root(parent, None)
    try:
        lineage = _capture_lineage(parent, path.name)
        result = packs._read_regular(root, path.name, limit)
        packs._ensure_root_unchanged(root)
        _ensure_lineage_unchanged(lineage)
        return result
    finally:
        root.close()


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":"), sort_keys=True) + "\n").encode("utf-8")


def _packet(path: Path):
    try:
        return parse_training_packet(_read(path, MAX_JSON_BYTES).decode("utf-8"))
    except (OSError, TypeError, ValueError, RecursionError):
        raise CompilationError("dataset_invalid") from None


def _recipe(path: Path, packet) -> str:
    from .recognition.training_proposal import selected_train_ids

    try:
        text = _read(path, MAX_RECIPE_BYTES).decode("utf-8")
        selected_train_ids(packet, text)
        return text
    except (OSError, TypeError, ValueError, RecursionError):
        raise CompilationError("recipe_invalid") from None


def validate_output(path: Path) -> Path:
    """Resolve the chosen parent and require an absent final directory."""
    try:
        path = Path(path)
        if path.name in {"", ".", ".."}:
            raise ValueError("Missing new directory name.")
        parent = path.parent.resolve(strict=True)
        if not parent.is_dir():
            raise ValueError("Missing parent.")
        destination = parent / path.name
        try:
            destination.lstat()
        except FileNotFoundError:
            return destination
        raise ValueError("Output already exists.")
    except (OSError, TypeError, ValueError, RecursionError):
        raise CompilationError("output_invalid") from None


def _write_new(path: Path, data: bytes) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                         | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)


def _receipt(packet, recipe: str, manifest: bytes, pack) -> dict[str, Any]:
    from .recognition.training_proposal import selected_train_ids

    examples = {example.id: example for example in packet.examples}
    selected = selected_train_ids(packet, recipe)
    return {
        "format": REPORT_FORMAT, "schema_version": 1, "status": "draft",
        "dataset_sha256": hashlib.sha256(_canonical_packet_json(packet).encode("utf-8")).hexdigest(),
        "recipe_sha256": hashlib.sha256(recipe.encode("utf-8")).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest).hexdigest(),
        "pack_id": pack.id, "pack_version": pack.version,
        "selected_examples": [{"id": item, "sha256": examples[item].sha256} for item in selected],
        "assets": [{"id": asset.id, "sha256": asset.sha256} for asset in pack.assets],
        "approved": False, "live_readiness": False, "native_input": False,
        "screen_capture": False, "persistent_images": True, "held_out_used": False,
        "model_training": False, "recognition_only": True,
    }


def _write_candidate(destination: Path, manifest: bytes, assets, receipt=None) -> None:
    """Create only fixed generated paths; completion receipt is written last.

    POSIX directory descriptors pin the output objects. Windows rechecks path
    identities and cannot offer the same descriptor-relative path guarantee.
    Failures may leave an incomplete private directory without a receipt.
    """
    from .training_fixtures import _capture_lineage, _ensure_lineage_unchanged

    try:
        destination = validate_output(destination)
        lineage = _capture_lineage(destination.parent, destination.name)
        parent = packs._open_root(destination.parent, None)
    except (OSError, TypeError, ValueError, RecursionError):
        raise CompilationError("output_invalid") from None
    created = []
    try:
        if parent.descriptor is not None and os.mkdir in os.supports_dir_fd:
            os.mkdir(destination.name, 0o700, dir_fd=parent.descriptor)
        else:
            destination.mkdir(mode=0o700)
        _ensure_lineage_unchanged(lineage)
        output = packs._open_root(destination, None)
        created.append(output)

        def mkdir(root, name):
            packs._ensure_root_unchanged(root)
            if root.descriptor is not None and os.mkdir in os.supports_dir_fd:
                os.mkdir(name, 0o700, dir_fd=root.descriptor)
            else:
                (root.path / name).mkdir(mode=0o700)
            packs._ensure_root_unchanged(root)
            child = packs._open_root(root.path / name, None)
            created.append(child)
            return child

        def write(root, name, data):
            _ensure_lineage_unchanged(lineage)
            for directory in created:
                packs._ensure_root_unchanged(directory)
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
            if root.descriptor is not None and os.open in os.supports_dir_fd:
                descriptor = os.open(name, flags, 0o600, dir_fd=root.descriptor)
            else:
                descriptor = os.open(root.path / name, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
            for directory in created:
                packs._ensure_root_unchanged(directory)
            _ensure_lineage_unchanged(lineage)

        candidate = mkdir(output, "candidate")
        asset_root = mkdir(candidate, "assets")
        for asset in assets:
            # These objects have already passed the pure candidate validator.
            if asset.path != f"assets/{asset.id}.png" or "/" in asset.id or "\\" in asset.id:
                raise ValueError("Unexpected generated asset.")
            write(asset_root, f"{asset.id}.png", asset.data)
        write(candidate, "pack.json", manifest)
        if receipt is not None:
            write(output, "proposal.json", _json_bytes(receipt))
    except (OSError, TypeError, ValueError, RecursionError):
        raise CompilationError("output_invalid") from None
    finally:
        for root in reversed(created):
            root.close()
        parent.close()


def _from_sources(packet, recipe: str, fixture_directory: Path):
    """Derive bytes from exact hash-checked sources, never a child assertion."""
    from .recognition.training_proposal import build_candidate, selected_train_ids
    from .training_fixtures import FixtureError, load_fixture

    examples = {example.id: example for example in packet.examples}
    try:
        fixtures = {item: load_fixture(fixture_directory, examples[item], consent=True)
                    for item in selected_train_ids(packet, recipe)}
    except FixtureError:
        raise CompilationError("fixture_invalid") from None
    try:
        return build_candidate(packet, recipe, fixtures, consent=True)
    except (TypeError, ValueError, RecursionError):
        raise CompilationError("recipe_invalid") from None


def worker(packet_path: Path, recipe_path: Path, fixture_directory: Path,
           output: Path, report_path: Path, *, consent: bool = False) -> None:
    """Read only selected train files, then export to private parent staging."""
    try:
        _consent(consent)
        packet = _packet(packet_path)
        recipe = _recipe(recipe_path, packet)
        built = _from_sources(packet, recipe, fixture_directory)
        report = _receipt(packet, recipe, built.manifest, built.pack)
        _write_candidate(output, built.manifest, built.assets)
        payload = {"ok": True, "report": report}
    except CompilationError as error:
        payload = {"ok": False, "error": error.code}
    except Exception:
        payload = {"ok": False, "error": "worker_failed"}
    try:
        _write_new(report_path, _json_bytes(payload))
    except (OSError, TypeError, ValueError, RecursionError):
        raise CompilationError("output_invalid") from None


def run_compile(packet_path: Path, recipe_path: Path, fixture_directory: Path,
                output: Path, *, consent: bool = False) -> dict[str, Any]:
    """Bound decoding/export in a child, validate its result, publish a draft."""
    try:
        return _run_compile(packet_path, recipe_path, fixture_directory, output, consent=consent)
    except CompilationError:
        raise
    except (OSError, TypeError, ValueError, RecursionError, MemoryError):
        raise CompilationError("worker_failed") from None


def _run_compile(packet_path: Path, recipe_path: Path, fixture_directory: Path,
                 output: Path, *, consent: bool = False) -> dict[str, Any]:
    _consent(consent)
    destination = validate_output(output)
    packet = _packet(packet_path)
    recipe = _recipe(recipe_path, packet)
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command += ["-m", "afk_grinder"]
    with tempfile.TemporaryDirectory(prefix="afk-grinder-compile-") as directory:
        root = Path(directory)
        snapshot = root / "packet.json"
        crop_recipe = root / "recipe.json"
        report_path = root / "result.json"
        staging = root / "export"
        _write_new(snapshot, _canonical_packet_json(packet).encode("utf-8"))
        _write_new(crop_recipe, recipe.encode("utf-8"))
        command += ["--compile-worker", str(snapshot), "--crop-recipe", str(crop_recipe),
                    "--fixture-directory", str(fixture_directory), "--compile-output", str(staging),
                    "--compile-report", str(report_path), "--compile-consent"]
        try:
            result = subprocess.run(command, timeout=COMPILE_TIMEOUT, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, check=False)
        except subprocess.TimeoutExpired:
            raise CompilationError("timeout") from None
        except OSError:
            raise CompilationError("worker_failed") from None
        if result.returncode != 0:
            raise CompilationError("worker_failed")
        try:
            payload = packs._parse_manifest(_read(report_path, MAX_REPORT_BYTES))
            if (set(payload) == {"ok", "error"} and payload["ok"] is False
                    and type(payload["error"]) is str and payload["error"] in ERROR_CODES):
                raise CompilationError(payload["error"])
            if set(payload) != {"ok", "report"} or payload["ok"] is not True:
                raise ValueError("Invalid worker envelope.")
            pack = packs.load_pack(staging / "candidate", app_version=__version__)
            manifest = _read(staging / "candidate" / "pack.json", packs.MAX_JSON_BYTES)
            from .recognition.training_proposal import validate_candidate

            pack = validate_candidate(packet, recipe, manifest, pack.assets)
            # A self-consistent child asset/hash/report cannot prove where its
            # pixels came from. Rebuild from selected, hash-checked train files
            # and publish only the independently derived parent bytes.
            rebuilt = _from_sources(packet, recipe, fixture_directory)
            if manifest != rebuilt.manifest or pack.assets != rebuilt.assets:
                raise ValueError("Worker pixels differ from selected sources.")
            expected = _receipt(packet, recipe, rebuilt.manifest, rebuilt.pack)
            if _json_bytes(payload["report"]) != _json_bytes(expected):
                raise ValueError("Worker report differs from validated metadata.")
        except CompilationError:
            raise
        except (OSError, TypeError, ValueError, RecursionError):
            raise CompilationError("report_invalid") from None
        _write_candidate(destination, rebuilt.manifest, rebuilt.assets, expected)
        return expected
