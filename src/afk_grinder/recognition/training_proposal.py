"""Pure, consent-gated conversion from a training draft to a pack candidate.

This module receives only an already decoded, explicitly selected set of train
fixtures.  It never opens a path, discovers data, calls a model, captures a
screen, or performs an input action.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import math
import struct
from typing import Any, Final
import zlib

from PIL import Image

from afk_grinder import __version__
from afk_grinder.training_fixtures import FixturePixels
from afk_grinder.training_packet import TrainingPacket, validate_training_packet
from .pack_compiler import compile_pack
from .packs import Asset, PackError, ResourcePack, _validate_manifest


MAX_RECIPE_BYTES: Final = 128 * 1024
MAX_RECIPE_DEPTH: Final = 12
MAX_RECIPE_NODES: Final = 4096
MAX_ANCHORS: Final = 16
MAX_TRAIN_SOURCES: Final = 4
MAX_SOURCE_PIXELS: Final = 16_000_000
_ROOT_KEYS: Final = frozenset({
    "format", "schema_version", "pack_id", "pack_version", "provenance", "setup", "anchors", "states",
})
_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_PNG_CHUNKS: Final = frozenset({b"IHDR", b"IDAT", b"IEND"})


class ProposalError(ValueError):
    """Raised when an unapproved local candidate cannot be formed safely."""


@dataclass(frozen=True, slots=True)
class Candidate:
    """Deterministic, in-memory pack candidate awaiting separate review."""

    manifest: bytes
    assets: tuple[Asset, ...]
    pack: ResourcePack


def selected_train_ids(packet: TrainingPacket, recipe_text: str) -> tuple[str, ...]:
    """Return exact selected train examples after sealed-packet and recipe checks."""
    try:
        canonical = validate_training_packet(packet)
        recipe = _parse_recipe(recipe_text, canonical)
        return tuple(dict.fromkeys(anchor["example_id"] for anchor in recipe["anchors"]))
    except ProposalError:
        raise
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError) as error:
        raise ProposalError("training proposal is invalid") from error


def build_candidate(
    packet: TrainingPacket,
    recipe_text: str,
    fixtures: Mapping[str, FixturePixels],
    *,
    consent: bool = False,
) -> Candidate:
    """Build a metadata-stripped candidate from selected in-memory train pixels."""
    if consent is not True:
        raise ProposalError("explicit training-crop consent is required")
    try:
        canonical = validate_training_packet(packet)
        recipe = _parse_recipe(recipe_text, canonical)
        selected = tuple(anchor["example_id"] for anchor in recipe["anchors"])
        pixels = _selected_pixels(canonical, selected, fixtures)
        assets = _build_assets(canonical, recipe, pixels)
        manifest = _manifest_bytes(canonical, recipe, assets)
        pack = validate_candidate(canonical, recipe_text, manifest, assets)
        return Candidate(manifest, assets, pack)
    except ProposalError:
        raise
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError, MemoryError) as error:
        raise ProposalError("training proposal is invalid") from error


def validate_candidate(
    packet: TrainingPacket,
    recipe_text: str,
    manifest: bytes,
    assets: tuple[Asset, ...],
) -> ResourcePack:
    """Validate candidate bytes without fixture IO or consent-authorized reads."""
    try:
        canonical = validate_training_packet(packet)
        recipe = _parse_recipe(recipe_text, canonical)
        if type(manifest) is not bytes or type(assets) is not tuple:
            raise ProposalError("training proposal is invalid")
        selected = tuple(anchor["example_id"] for anchor in recipe["anchors"])
        expected_ids = tuple(anchor["id"] for anchor in recipe["anchors"])
        if len(assets) != len(expected_ids):
            raise ProposalError("training proposal is invalid")
        by_id: dict[str, Asset] = {}
        dimensions: dict[str, tuple[int, int]] = {}
        for asset, anchor_id, example_id in zip(assets, expected_ids, selected, strict=True):
            if type(asset) is not Asset or asset.id != anchor_id or asset.path != f"assets/{anchor_id}.png":
                raise ProposalError("training proposal is invalid")
            if type(asset.sha256) is not str or type(asset.data) is not bytes:
                raise ProposalError("training proposal is invalid")
            if sha256(asset.data).hexdigest() != asset.sha256:
                raise ProposalError("training proposal is invalid")
            dimensions[anchor_id] = _png_dimensions(asset.data)
            expected = _output_dimensions(canonical, _example(canonical, example_id), _anchor(recipe, anchor_id)["crop"])
            if dimensions[anchor_id] != expected:
                raise ProposalError("training proposal is invalid")
            by_id[asset.id] = asset
        if len(by_id) != len(assets):
            raise ProposalError("training proposal is invalid")
        expected_manifest = _manifest_bytes(canonical, recipe, assets)
        if manifest != expected_manifest:
            raise ProposalError("training proposal is invalid")
        payload = _strict_json(manifest)
        pack = _validate_manifest(payload, __version__)
        loaded = ResourcePack(
            pack.id, pack.version, pack.min_app_version, pack.provenance, pack.reference_size, pack.setup,
            tuple(Asset(asset.id, asset.path, asset.sha256, by_id[asset.id].data) for asset in pack.assets),
            pack.anchors, pack.states,
        )
        compile_pack(loaded, canonical.reference_size)
        return loaded
    except ProposalError:
        raise
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError, MemoryError, PackError) as error:
        raise ProposalError("training proposal is invalid") from error


def _parse_recipe(text: str, packet: TrainingPacket) -> dict[str, Any]:
    payload = _strict_json(text)
    if not isinstance(payload, dict) or frozenset(payload) != _ROOT_KEYS:
        raise ProposalError("training proposal is invalid")
    if payload.get("format") != "afk-training-pack-recipe" or type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        raise ProposalError("training proposal is invalid")
    if type(payload["pack_id"]) is not str or type(payload["pack_version"]) is not str:
        raise ProposalError("training proposal is invalid")
    if not isinstance(payload["provenance"], dict) or frozenset(payload["provenance"]) != {"source", "revision", "license", "attribution"}:
        raise ProposalError("training proposal is invalid")
    if not isinstance(payload["setup"], dict) or frozenset(payload["setup"]) != {"instructions", "min_content_size"}:
        raise ProposalError("training proposal is invalid")
    anchors = payload["anchors"]
    states = payload["states"]
    if not isinstance(anchors, list) or not 1 <= len(anchors) <= MAX_ANCHORS:
        raise ProposalError("training proposal is invalid")
    if not isinstance(states, list) or len(states) != len(packet.states) or len(states) > 32:
        raise ProposalError("training proposal is invalid")
    examples = {example.id: example for example in packet.examples}
    anchors_seen: set[str] = set()
    source_ids: set[str] = set()
    for anchor in anchors:
        if not isinstance(anchor, dict) or frozenset(anchor) != {"id", "example_id", "crop", "roi", "threshold", "scale_range"}:
            raise ProposalError("training proposal is invalid")
        anchor_id = anchor.get("id")
        example_id = anchor.get("example_id")
        if type(anchor_id) is not str or anchor_id in anchors_seen or type(example_id) is not str:
            raise ProposalError("training proposal is invalid")
        example = examples.get(example_id)
        if example is None or example.split != "train":
            raise ProposalError("training proposal is invalid")
        _rectangle(anchor["crop"], example.width, example.height)
        _rectangle(anchor["roi"], packet.reference_size[0], packet.reference_size[1])
        _number(anchor["threshold"])
        _pair(anchor["scale_range"])
        _output_dimensions(packet, example, anchor["crop"])
        anchors_seen.add(anchor_id)
        source_ids.add(example_id)
    if len(source_ids) > MAX_TRAIN_SOURCES:
        raise ProposalError("training proposal is invalid")
    selected_pixels = sum(examples[item].width * examples[item].height for item in source_ids)
    if selected_pixels > MAX_SOURCE_PIXELS:
        raise ProposalError("training proposal is invalid")
    original_states = {state.id: state for state in packet.states}
    seen_states: set[str] = set()
    by_anchor = {anchor["id"]: anchor for anchor in anchors}
    for state in states:
        if not isinstance(state, dict) or frozenset(state) != {"id", "positive", "exclude", "stable_frames"}:
            raise ProposalError("training proposal is invalid")
        state_id = state.get("id")
        if type(state_id) is not str or state_id in seen_states or state_id not in original_states:
            raise ProposalError("training proposal is invalid")
        positive = _references(state["positive"], anchors_seen, True)
        exclude = _references(state["exclude"], anchors_seen, False)
        if set(positive) & set(exclude) or type(state["stable_frames"]) is not int:
            raise ProposalError("training proposal is invalid")
        for anchor_id in positive:
            if examples[by_anchor[anchor_id]["example_id"]].state_id != state_id:
                raise ProposalError("training proposal is invalid")
        seen_states.add(state_id)
    if seen_states != set(original_states):
        raise ProposalError("training proposal is invalid")
    _validate_recipe_as_manifest(packet, payload)
    return payload


def _validate_recipe_as_manifest(packet: TrainingPacket, recipe: dict[str, Any]) -> None:
    """Reuse runtime schema rules without accepting untrusted asset bytes."""
    placeholders = tuple(
        Asset(anchor["id"], f"assets/{anchor['id']}.png", "0" * 64, b"") for anchor in recipe["anchors"]
    )
    _validate_manifest(_manifest_payload(packet, recipe, placeholders), __version__)


def _selected_pixels(packet: TrainingPacket, selected: tuple[str, ...], fixtures: Mapping[str, FixturePixels]) -> dict[str, FixturePixels]:
    if not isinstance(fixtures, Mapping) or set(fixtures) != set(selected):
        raise ProposalError("training proposal is invalid")
    result: dict[str, FixturePixels] = {}
    for example_id in set(selected):
        fixture = fixtures.get(example_id)
        example = _example(packet, example_id)
        if (type(fixture) is not FixturePixels or type(fixture.width) is not int or type(fixture.height) is not int
                or type(fixture.pixels) is not bytes or fixture.width != example.width or fixture.height != example.height
                or fixture.width < 1 or fixture.height < 1 or fixture.width * fixture.height > MAX_SOURCE_PIXELS
                or len(fixture.pixels) != fixture.width * fixture.height * 3):
            raise ProposalError("training proposal is invalid")
        result[example_id] = fixture
    return result


def _build_assets(packet: TrainingPacket, recipe: dict[str, Any], fixtures: Mapping[str, FixturePixels]) -> tuple[Asset, ...]:
    result: list[Asset] = []
    for anchor in recipe["anchors"]:
        example = _example(packet, anchor["example_id"])
        fixture = fixtures[example.id]
        width, height = _output_dimensions(packet, example, anchor["crop"])
        x, y, crop_width, crop_height = anchor["crop"]
        source = Image.frombytes("RGB", (fixture.width, fixture.height), fixture.pixels, "raw", "BGR")
        crop = source.crop((x, y, x + crop_width, y + crop_height))
        if crop.size != (width, height):
            crop = crop.resize((width, height), Image.Resampling.LANCZOS)
        stream = BytesIO()
        crop.save(stream, format="PNG", compress_level=9, optimize=False)
        data = stream.getvalue()
        _png_dimensions(data)
        result.append(Asset(anchor["id"], f"assets/{anchor['id']}.png", sha256(data).hexdigest(), data))
    return tuple(result)


def _manifest_bytes(packet: TrainingPacket, recipe: dict[str, Any], assets: tuple[Asset, ...]) -> bytes:
    return json.dumps(_manifest_payload(packet, recipe, assets), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _manifest_payload(packet: TrainingPacket, recipe: dict[str, Any], assets: tuple[Asset, ...]) -> dict[str, Any]:
    return {
        "format": "afk-resource-pack", "schema_version": 1,
        "id": recipe["pack_id"], "version": recipe["pack_version"], "min_app_version": __version__,
        "provenance": recipe["provenance"], "reference_size": list(packet.reference_size),
        "setup": {"language": packet.locale, **recipe["setup"]},
        "assets": [{"id": asset.id, "path": asset.path, "sha256": asset.sha256} for asset in assets],
        "anchors": [{"id": anchor["id"], "asset": anchor["id"], "roi": anchor["roi"], "threshold": anchor["threshold"], "scale_range": anchor["scale_range"]} for anchor in recipe["anchors"]],
        "states": [{"id": state["id"], "positive": state["positive"], "exclude": state["exclude"], "stable_frames": state["stable_frames"], "kind": next(original.kind for original in packet.states if original.id == state["id"])} for state in recipe["states"]],
        "routines": [],
    }


def _strict_json(text: str | bytes) -> Any:
    if type(text) not in {str, bytes}:
        raise ProposalError("training proposal is invalid")
    try:
        encoded = text.encode("utf-8") if type(text) is str else text
    except UnicodeEncodeError as error:
        raise ProposalError("training proposal is invalid") from error
    if len(encoded) > MAX_RECIPE_BYTES:
        raise ProposalError("training proposal is invalid")
    try:
        value = json.loads(encoded, object_pairs_hook=_unique_object, parse_constant=_invalid_constant, parse_int=_integer_token)
    except (UnicodeDecodeError, TypeError, ValueError, json.JSONDecodeError) as error:
        if isinstance(error, ProposalError):
            raise
        raise ProposalError("training proposal is invalid") from error
    _tree(value)
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProposalError("training proposal is invalid")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ProposalError("training proposal is invalid")


def _integer_token(value: str) -> int:
    if len(value.lstrip("-")) > 20:
        raise ProposalError("training proposal is invalid")
    return int(value)


def _tree(value: Any, depth: int = 1, nodes: list[int] | None = None) -> None:
    active = [0] if nodes is None else nodes
    active[0] += 1
    if depth > MAX_RECIPE_DEPTH or active[0] > MAX_RECIPE_NODES:
        raise ProposalError("training proposal is invalid")
    if isinstance(value, dict):
        for child in value.values():
            _tree(child, depth + 1, active)
    elif isinstance(value, list):
        for child in value:
            _tree(child, depth + 1, active)


def _rectangle(value: Any, width: int, height: int) -> tuple[int, int, int, int]:
    if not isinstance(value, list) or len(value) != 4 or any(type(item) is not int for item in value):
        raise ProposalError("training proposal is invalid")
    x, y, box_width, box_height = value
    if x < 0 or y < 0 or box_width <= 0 or box_height <= 0 or x + box_width > width or y + box_height > height:
        raise ProposalError("training proposal is invalid")
    return x, y, box_width, box_height


def _number(value: Any) -> None:
    if type(value) not in {int, float} or not math.isfinite(value):
        raise ProposalError("training proposal is invalid")


def _pair(value: Any) -> None:
    if not isinstance(value, list) or len(value) != 2:
        raise ProposalError("training proposal is invalid")
    _number(value[0])
    _number(value[1])


def _references(value: Any, anchors: set[str], required: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (required and not value) or len(value) > MAX_ANCHORS:
        raise ProposalError("training proposal is invalid")
    if any(type(item) is not str for item in value) or len(set(value)) != len(value) or any(item not in anchors for item in value):
        raise ProposalError("training proposal is invalid")
    return tuple(value)


def _example(packet: TrainingPacket, example_id: str):
    for example in packet.examples:
        if example.id == example_id:
            return example
    raise ProposalError("training proposal is invalid")


def _anchor(recipe: dict[str, Any], anchor_id: str) -> dict[str, Any]:
    for anchor in recipe["anchors"]:
        if anchor["id"] == anchor_id:
            return anchor
    raise ProposalError("training proposal is invalid")


def _output_dimensions(packet: TrainingPacket, example: Any, crop: Any) -> tuple[int, int]:
    if example.width * packet.reference_size[1] != example.height * packet.reference_size[0]:
        raise ProposalError("training proposal is invalid")
    _, _, width, height = _rectangle(crop, example.width, example.height)
    output = (
        math.floor(width * packet.reference_size[0] / example.width + 0.5),
        math.floor(height * packet.reference_size[1] / example.height + 0.5),
    )
    if not all(8 <= dimension <= 512 for dimension in output):
        raise ProposalError("training proposal is invalid")
    return output


def _png_dimensions(data: bytes) -> tuple[int, int]:
    """Accept only deterministic, metadata-free RGB PNG output."""
    if not data.startswith(_PNG_SIGNATURE):
        raise ProposalError("training proposal is invalid")
    offset = len(_PNG_SIGNATURE)
    seen: list[bytes] = []
    dimensions: tuple[int, int] | None = None
    while offset < len(data):
        if offset + 12 > len(data):
            raise ProposalError("training proposal is invalid")
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        end = offset + 12 + length
        if end > len(data):
            raise ProposalError("training proposal is invalid")
        kind = data[offset + 4:offset + 8]
        payload = data[offset + 8:offset + 8 + length]
        crc = struct.unpack(">I", data[offset + 8 + length:end])[0]
        if zlib.crc32(payload, zlib.crc32(kind)) & 0xffffffff != crc or kind not in _PNG_CHUNKS:
            raise ProposalError("training proposal is invalid")
        if kind == b"IHDR":
            if length != 13 or seen:
                raise ProposalError("training proposal is invalid")
            width, height, depth, colour, compression, filter_method, interlace = struct.unpack(">IIBBBBB", payload)
            if not (8 <= width <= 512 and 8 <= height <= 512 and depth == 8 and colour == 2 and compression == 0 and filter_method == 0 and interlace == 0):
                raise ProposalError("training proposal is invalid")
            dimensions = (width, height)
        elif kind == b"IDAT" and (not seen or seen[0] != b"IHDR" or b"IEND" in seen):
            raise ProposalError("training proposal is invalid")
        elif kind == b"IEND" and (length != 0 or b"IDAT" not in seen or end != len(data)):
            raise ProposalError("training proposal is invalid")
        seen.append(kind)
        offset = end
    if dimensions is None or not seen or seen[-1] != b"IEND":
        raise ProposalError("training proposal is invalid")
    return dimensions
