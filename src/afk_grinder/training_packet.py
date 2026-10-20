"""Strict, data-only parser for local model training proposals.

Training packets are separate from runtime recognition packs. A valid packet is
still only a draft: this module never loads image bytes, calls a model,
executes an action, approves a packet, or creates a runtime routine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
import unicodedata
from typing import Any, Final


MAX_JSON_BYTES: Final = 1_000_000
MAX_DEPTH: Final = 12
MAX_STATES: Final = 64
MAX_EXAMPLES: Final = 2_048
MAX_DEMONSTRATIONS: Final = 128
MAX_IMAGE_PIXELS: Final = 16_000_000
MAX_GENERIC_COLLECTION: Final = MAX_EXAMPLES

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SEMVER_RE = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_PATH_RE = re.compile(r"^examples/([a-z0-9]+(?:-[a-z0-9]+)*)\.(webp|jpg|png)$")
_LOGIN_RE = re.compile(r"login|log(?:[ -]?in)|sign(?:[ -]?in)|authenticat|password|credential", re.IGNORECASE)
_BLOCKED_REQUEST_TOKENS: Final = frozenset({
    "click", "code", "command", "execute", "exec", "input", "key", "keyboard",
    "maa", "mouse", "press", "script", "shell", "tap", "xy",
})
_STATE_KINDS: Final = frozenset({"gameplay", "popup", "transaction", "loading", "disconnected", "unknown"})
_ROOT_KEYS: Final = frozenset({
    "format", "schema_version", "status", "id", "version", "game", "locale",
    "reference_size", "states", "examples", "demonstrations",
})


class TrainingPacketError(ValueError):
    """Raised when untrusted training proposal data violates the contract."""


@dataclass(frozen=True, slots=True)
class Game:
    id: str
    title: str
    place_id: str | None


@dataclass(frozen=True, slots=True)
class State:
    id: str
    kind: str
    description: str


@dataclass(frozen=True, slots=True)
class Example:
    id: str
    path: str
    sha256: str
    width: int
    height: int
    state_id: str
    split: str
    origin: str


@dataclass(frozen=True, slots=True)
class Demonstration:
    id: str
    from_state: str
    to_state: str
    capability_request: str
    example_ids: tuple[str, ...]
    max_duration_ms: int
    retry_limit: int


@dataclass(frozen=True, slots=True)
class TrainingPacket:
    id: str
    version: str
    game: Game
    locale: str
    reference_size: tuple[int, int]
    states: tuple[State, ...]
    examples: tuple[Example, ...]
    demonstrations: tuple[Demonstration, ...]
    format: str = "afk-grinder-training"
    schema_version: int = 1
    status: str = "draft"
    _validated_digest: str = field(init=False, default="", repr=False, compare=False)


def parse_training_packet(text: str) -> TrainingPacket:
    """Parse untrusted JSON proposal without opening any referenced path."""
    payload = _parse_json(text)
    _check_json_shape(payload)
    packet = _validate_packet(payload)
    object.__setattr__(packet, "_validated_digest", _packet_digest(packet))
    return packet


def fine_tuning_records(packet: TrainingPacket, *, consent: bool = False) -> tuple[str, ...]:
    """Return consent-gated JSON text records for a later fine-tuning process."""
    if not isinstance(packet, TrainingPacket):
        raise TrainingPacketError("packet must be a TrainingPacket")
    if consent is not True:
        raise TrainingPacketError("explicit consent is required for training export")
    canonical_packet = _canonical_packet_json(packet)
    validated_packet = parse_training_packet(canonical_packet)
    if packet._validated_digest != _packet_digest(packet):
        raise TrainingPacketError("packet was not sealed by strict validation")
    descriptions = {state.id: state.description for state in validated_packet.states}
    records: list[str] = []
    for example in validated_packet.examples:
        if example.split == "held_out":
            continue
        record = {
            "format": "afk-grinder-fine-tuning-record",
            "schema_version": 1,
            "split": example.split,
            "image_ref": {"path": example.path, "sha256": example.sha256, "width": example.width, "height": example.height},
            "label": {"state_id": example.state_id, "description": descriptions[example.state_id]},
        }
        records.append(json.dumps(record, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return tuple(records)


def _packet_digest(packet: TrainingPacket) -> str:
    return hashlib.sha256(_canonical_packet_json(packet).encode("utf-8")).hexdigest()


def _canonical_packet_json(packet: TrainingPacket) -> str:
    core = {
        "format": packet.format,
        "schema_version": packet.schema_version,
        "status": packet.status,
        "id": packet.id,
        "version": packet.version,
        "game": {"id": packet.game.id, "title": packet.game.title, "place_id": packet.game.place_id},
        "locale": packet.locale,
        "reference_size": list(packet.reference_size),
        "states": [
            {"id": state.id, "kind": state.kind, "description": state.description}
            for state in packet.states
        ],
        "examples": [
            {
                "id": example.id,
                "path": example.path,
                "sha256": example.sha256,
                "width": example.width,
                "height": example.height,
                "state_id": example.state_id,
                "split": example.split,
                "origin": example.origin,
            }
            for example in packet.examples
        ],
        "demonstrations": [
            {
                "id": demonstration.id,
                "from_state": demonstration.from_state,
                "to_state": demonstration.to_state,
                "capability_request": demonstration.capability_request,
                "example_ids": list(demonstration.example_ids),
                "max_duration_ms": demonstration.max_duration_ms,
                "retry_limit": demonstration.retry_limit,
            }
            for demonstration in packet.demonstrations
        ],
    }
    try:
        return json.dumps(core, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise TrainingPacketError("packet cannot be canonically serialized") from exc


def _parse_json(text: str) -> Any:
    if not isinstance(text, str):
        raise TrainingPacketError("packet JSON must be text")
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise TrainingPacketError("packet JSON must be UTF-8 encodable") from exc
    if len(encoded) > MAX_JSON_BYTES:
        raise TrainingPacketError("packet JSON exceeds 1 MB")
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_reject_nonfinite, parse_float=_reject_float, parse_int=_parse_integer)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        if isinstance(exc, TrainingPacketError):
            raise
        raise TrainingPacketError("packet JSON is invalid") from exc


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TrainingPacketError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise TrainingPacketError(f"non-finite JSON number: {value}")


def _reject_float(value: str) -> None:
    raise TrainingPacketError(f"floating JSON number is not allowed: {value}")


def _parse_integer(value: str) -> int:
    if len(value.lstrip("-")) > 20:
        raise TrainingPacketError("JSON integer is too large")
    return int(value)


def _check_json_shape(value: Any, depth: int = 1) -> None:
    if depth > MAX_DEPTH:
        raise TrainingPacketError("packet JSON exceeds maximum depth")
    if isinstance(value, dict):
        if len(value) > MAX_GENERIC_COLLECTION:
            raise TrainingPacketError("packet object has too many members")
        for item in value.values():
            _check_json_shape(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_GENERIC_COLLECTION:
            raise TrainingPacketError("packet list has too many items")
        for item in value:
            _check_json_shape(item, depth + 1)


def _validate_packet(value: Any) -> TrainingPacket:
    root = _object(value, "packet")
    _exact_keys(root, _ROOT_KEYS, "packet")
    if root["format"] != "afk-grinder-training":
        raise TrainingPacketError("packet format must be afk-grinder-training")
    if root["schema_version"] != 1 or type(root["schema_version"]) is not int:
        raise TrainingPacketError("schema_version must be integer 1")
    if root["status"] != "draft":
        raise TrainingPacketError("training packets must remain draft")
    packet_id = _slug(root["id"], "packet id")
    version = _text(root["version"], "version", 32)
    if not _SEMVER_RE.fullmatch(version):
        raise TrainingPacketError("version must use X.Y.Z")
    game = _validate_game(root["game"])
    if root["locale"] != "en":
        raise TrainingPacketError("locale must be en")
    reference_size = _size(root["reference_size"], "reference_size")
    states = _validate_states(root["states"])
    state_ids = {state.id for state in states}
    examples = _validate_examples(root["examples"], state_ids)
    demonstrations = _validate_demonstrations(root["demonstrations"], state_ids, examples, states)
    return TrainingPacket(packet_id, version, game, "en", reference_size, states, examples, demonstrations)


def _validate_game(value: Any) -> Game:
    game = _object(value, "game")
    _exact_keys(game, frozenset({"id", "title", "place_id"}), "game")
    game_id = _slug(game["id"], "game id")
    title = _semantic_text(game["title"], "game title", 128)
    place_id = game["place_id"]
    if place_id is not None and (not isinstance(place_id, str) or not re.fullmatch(r"[0-9]{1,20}", place_id)):
        raise TrainingPacketError("game place_id must be null or 1-20 digits")
    return Game(game_id, title, place_id)


def _validate_states(value: Any) -> tuple[State, ...]:
    items = _list(value, "states", MAX_STATES)
    states: list[State] = []
    ids: set[str] = set()
    for index, item in enumerate(items):
        state = _object(item, f"states[{index}]")
        _exact_keys(state, frozenset({"id", "kind", "description"}), f"states[{index}]")
        state_id = _slug(state["id"], f"states[{index}].id")
        if state_id in ids:
            raise TrainingPacketError(f"duplicate state id: {state_id}")
        kind = state["kind"]
        if not isinstance(kind, str) or kind not in _STATE_KINDS:
            raise TrainingPacketError(f"states[{index}].kind is unsupported")
        states.append(State(state_id, kind, _semantic_text(state["description"], f"states[{index}].description", 256)))
        ids.add(state_id)
    return tuple(states)


def _validate_examples(value: Any, state_ids: set[str]) -> tuple[Example, ...]:
    items = _list(value, "examples", MAX_EXAMPLES)
    examples: list[Example] = []
    ids: set[str] = set()
    hash_splits: dict[str, str] = {}
    expected = frozenset({"id", "path", "sha256", "width", "height", "state_id", "split", "origin"})
    for index, item in enumerate(items):
        example = _object(item, f"examples[{index}]")
        _exact_keys(example, expected, f"examples[{index}]")
        example_id = _slug(example["id"], f"examples[{index}].id")
        if example_id in ids:
            raise TrainingPacketError(f"duplicate example id: {example_id}")
        path = example["path"]
        if not isinstance(path, str) or not path.isascii():
            raise TrainingPacketError(f"examples[{index}].path must be ASCII")
        path_match = _IMAGE_PATH_RE.fullmatch(path)
        if path_match is None or path_match.group(1) != example_id:
            raise TrainingPacketError(f"examples[{index}].path must be canonical for its id")
        sha256 = example["sha256"]
        if not isinstance(sha256, str) or _SHA256_RE.fullmatch(sha256) is None:
            raise TrainingPacketError(f"examples[{index}].sha256 must be lowercase SHA-256")
        width = _positive_int(example["width"], f"examples[{index}].width")
        height = _positive_int(example["height"], f"examples[{index}].height")
        if width * height > MAX_IMAGE_PIXELS:
            raise TrainingPacketError(f"examples[{index}] exceeds 16 megapixels")
        state_id = example["state_id"]
        if not isinstance(state_id, str) or state_id not in state_ids:
            raise TrainingPacketError(f"examples[{index}].state_id is unknown")
        split = example["split"]
        if split not in {"train", "validation", "held_out"}:
            raise TrainingPacketError(f"examples[{index}].split is unsupported")
        existing_split = hash_splits.get(sha256)
        if existing_split is not None and existing_split != split:
            raise TrainingPacketError("same image hash cannot cross dataset splits")
        hash_splits[sha256] = split
        origin = example["origin"]
        if origin not in {"synthetic", "manual"}:
            raise TrainingPacketError(f"examples[{index}].origin is unsupported")
        examples.append(Example(example_id, path, sha256, width, height, state_id, split, origin))
        ids.add(example_id)
    return tuple(examples)


def _validate_demonstrations(value: Any, state_ids: set[str], examples: tuple[Example, ...], states: tuple[State, ...]) -> tuple[Demonstration, ...]:
    items = _list(value, "demonstrations", MAX_DEMONSTRATIONS)
    example_ids = {example.id for example in examples}
    state_kinds = {state.id: state.kind for state in states}
    demonstrations: list[Demonstration] = []
    ids: set[str] = set()
    expected = frozenset({"id", "from_state", "to_state", "capability_request", "example_ids", "max_duration_ms", "retry_limit"})
    for index, item in enumerate(items):
        demonstration = _object(item, f"demonstrations[{index}]")
        _exact_keys(demonstration, expected, f"demonstrations[{index}]")
        demonstration_id = _slug(demonstration["id"], f"demonstrations[{index}].id")
        if demonstration_id in ids:
            raise TrainingPacketError(f"duplicate demonstration id: {demonstration_id}")
        from_state = _known_state(demonstration["from_state"], f"demonstrations[{index}].from_state", state_ids)
        to_state = _known_state(demonstration["to_state"], f"demonstrations[{index}].to_state", state_ids)
        if state_kinds[from_state] in {"transaction", "unknown"} or state_kinds[to_state] in {"transaction", "unknown"}:
            raise TrainingPacketError("transaction and unknown states cannot request capabilities")
        request = _slug(demonstration["capability_request"], f"demonstrations[{index}].capability_request")
        if _LOGIN_RE.search(request) or _BLOCKED_REQUEST_TOKENS.intersection(request.split("-")):
            raise TrainingPacketError("capability_request must be a non-executable semantic slug")
        refs = _list(demonstration["example_ids"], f"demonstrations[{index}].example_ids", MAX_EXAMPLES, minimum=1)
        parsed_refs: list[str] = []
        for reference in refs:
            if not isinstance(reference, str) or reference not in example_ids:
                raise TrainingPacketError(f"demonstrations[{index}].example_ids contains unknown example")
            if reference in parsed_refs:
                raise TrainingPacketError(f"demonstrations[{index}].example_ids must not repeat references")
            parsed_refs.append(reference)
        duration = _positive_int(demonstration["max_duration_ms"], f"demonstrations[{index}].max_duration_ms")
        if duration > 30_000:
            raise TrainingPacketError(f"demonstrations[{index}].max_duration_ms exceeds limit")
        retry_limit = demonstration["retry_limit"]
        if type(retry_limit) is not int or not 0 <= retry_limit <= 2:
            raise TrainingPacketError(f"demonstrations[{index}].retry_limit must be 0-2")
        demonstrations.append(Demonstration(demonstration_id, from_state, to_state, request, tuple(parsed_refs), duration, retry_limit))
        ids.add(demonstration_id)
    return tuple(demonstrations)


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TrainingPacketError(f"{label} must be an object")
    return value


def _exact_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    if frozenset(value) != expected:
        raise TrainingPacketError(f"{label} has unknown or missing fields")


def _list(value: Any, label: str, maximum: int, *, minimum: int = 0) -> list[Any]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise TrainingPacketError(f"{label} must contain {minimum}-{maximum} items")
    return value


def _slug(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) > 64 or _SLUG_RE.fullmatch(value) is None:
        raise TrainingPacketError(f"{label} must be a lowercase slug")
    if _LOGIN_RE.search(value):
        raise TrainingPacketError(f"{label} must not describe login training")
    return value


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= maximum:
        raise TrainingPacketError(f"{label} must be 1-{maximum} characters")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise TrainingPacketError(f"{label} must not contain control characters")
    return value


def _semantic_text(value: Any, label: str, maximum: int) -> str:
    text = _text(value, label, maximum)
    if _LOGIN_RE.search(text):
        raise TrainingPacketError(f"{label} must not describe login training")
    return text


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 1:
        raise TrainingPacketError(f"{label} must be a positive integer")
    return value


def _size(value: Any, label: str) -> tuple[int, int]:
    dimensions = _list(value, label, 2, minimum=2)
    width = _positive_int(dimensions[0], f"{label}[0]")
    height = _positive_int(dimensions[1], f"{label}[1]")
    if width * height > MAX_IMAGE_PIXELS:
        raise TrainingPacketError(f"{label} exceeds 16 megapixels")
    return (width, height)


def _known_state(value: Any, label: str, state_ids: set[str]) -> str:
    if not isinstance(value, str) or value not in state_ids:
        raise TrainingPacketError(f"{label} is unknown")
    return value
