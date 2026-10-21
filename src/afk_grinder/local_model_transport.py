"""Strict loopback-only transport for an already-installed local model.

This module deliberately has no server discovery, proxy support, authentication,
model lifecycle operations, or retry/fallback behavior.  Callers own the
process-level deadline; this transport applies the remaining monotonic budget
to each socket operation and never follows redirects.
"""

from __future__ import annotations

from dataclasses import dataclass
import base64
import http.client
import json
import math
import re
import socket
import time
from typing import Any, Final


_MAX_REQUEST_BYTES: Final = 8 * 1024 * 1024
_MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
_MAX_RESPONSE_TEXT_BYTES: Final = 128 * 1024
_MAX_IMAGE_B64_BYTES: Final = 1_400_000
_MAX_IMAGES: Final = 4
_MAX_MODEL_BYTES: Final = 8 * 1024 * 1024 * 1024
_MAX_JSON_DEPTH: Final = 32
_MAX_JSON_ITEMS: Final = 20_000
_MAX_SEMVER_BYTES: Final = 64
_PROFILE_NAME_RE: Final = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9._-]{0,62})/)?[a-z0-9](?:[a-z0-9._-]{0,62}):[a-z0-9][a-z0-9._-]{0,62}$"
)
_DIGEST_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_SEMVER_RE: Final = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
_ERROR_CODES: Final = frozenset({
    "model_invalid", "cloud_required", "model_changed", "model_unavailable", "response_invalid", "timeout",
})
_REMOTE_FIELDS: Final = frozenset({"remote_model", "remote_host"})


class LocalModelError(RuntimeError):
    """Sanitized failure from the local model boundary."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("invalid local model error code")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """A user-selected installed local model identity."""

    name: str
    digest: str

    def __post_init__(self) -> None:
        _validate_profile_fields(self.name, self.digest)


def generate_local(
    profile: ModelProfile,
    prompt: str,
    images: tuple[str, ...],
    schema: dict[str, Any],
    *,
    port: int = 11434,
    deadline: float,
) -> tuple[str, dict[str, str | int | bool]]:
    """Generate one structured local draft using a relative deadline budget in seconds."""
    _validate_arguments(profile, prompt, images, schema, port, deadline)
    deadline_at = time.monotonic() + deadline

    status = _request("GET", "/api/status", None, port, deadline_at)
    _require_cloud_disabled(status)
    model_size = _require_selected_tag(_request("GET", "/api/tags", None, port, deadline_at), profile)
    _require_selected_show(_request("POST", "/api/show", {"model": profile.name}, port, deadline_at), profile)
    runtime_version = _require_version(_request("GET", "/api/version", None, port, deadline_at))

    body = {
        "model": profile.name,
        "prompt": prompt,
        "images": list(images),
        "format": schema,
        "stream": False,
        "keep_alive": 0,
        "options": {
            "temperature": 0,
            "num_ctx": 4096,
            "num_predict": 1024,
            "num_thread": 2,
        },
    }
    response = _request("POST", "/api/generate", body, port, deadline_at)
    text = _require_generate_response(response, profile)

    # Retagging or enabling cloud while a request ran invalidates its output.
    _require_cloud_disabled(_request("GET", "/api/status", None, port, deadline_at))
    _require_selected_tag(_request("GET", "/api/tags", None, port, deadline_at), profile)
    return text, {
        "name": profile.name,
        "digest": profile.digest,
        "runtime_version": runtime_version,
        "model_size_bytes": model_size,
        "cloud_disabled": True,
        "vision": True,
        "digest_checked_before_after": True,
    }


def _validate_profile_fields(name: str, digest: str) -> None:
    if type(name) is not str or len(name.encode("ascii", "ignore")) != len(name):
        _fail("model_invalid")
    if len(name) > 128 or not _PROFILE_NAME_RE.fullmatch(name):
        _fail("model_invalid")
    if name.rsplit(":", 1)[1] == "latest" or any(token in name for token in ("cloud", "remote", "ollama.com")):
        _fail("model_invalid")
    if type(digest) is not str or not _DIGEST_RE.fullmatch(digest):
        _fail("model_invalid")


def _validate_arguments(
    profile: ModelProfile,
    prompt: str,
    images: tuple[str, ...],
    schema: dict[str, Any],
    port: int,
    deadline: float,
) -> None:
    if type(profile) is not ModelProfile:
        _fail("model_invalid")
    _validate_profile_fields(profile.name, profile.digest)
    if type(port) is not int or not 1024 <= port <= 65535:
        _fail("response_invalid")
    if type(deadline) not in (int, float) or not math.isfinite(deadline) or not 0 < deadline <= 50:
        _fail("timeout")
    try:
        prompt_bytes = prompt.encode("utf-8") if isinstance(prompt, str) else None
    except UnicodeEncodeError:
        _fail("response_invalid")
    if prompt_bytes is None or len(prompt_bytes) > _MAX_RESPONSE_TEXT_BYTES:
        _fail("response_invalid")
    if type(images) is not tuple or len(images) > _MAX_IMAGES:
        _fail("response_invalid")
    for image in images:
        if not isinstance(image, str) or len(image.encode("ascii", "ignore")) != len(image) or len(image) > _MAX_IMAGE_B64_BYTES:
            _fail("response_invalid")
        try:
            raw = base64.b64decode(image, validate=True)
        except (ValueError, TypeError):
            _fail("response_invalid")
        if len(raw) < 4 or not raw.startswith(b"\xff\xd8") or not raw.endswith(b"\xff\xd9"):
            _fail("response_invalid")
    if type(schema) is not dict:
        _fail("response_invalid")
    _validate_json_tree(schema)
    try:
        encoded = _encode_json({"prompt": prompt, "images": list(images), "format": schema})
    except (TypeError, ValueError, OverflowError):
        _fail("response_invalid")
    if len(encoded) > _MAX_REQUEST_BYTES:
        _fail("response_invalid")


def _request(method: str, path: str, payload: dict[str, Any] | None, port: int, deadline_at: float) -> Any:
    if (method, path) not in {
        ("GET", "/api/status"), ("GET", "/api/tags"), ("GET", "/api/version"),
        ("POST", "/api/show"), ("POST", "/api/generate"),
    }:
        _fail("model_unavailable")
    body = None if payload is None else _encode_json(payload)
    if body is not None and len(body) > _MAX_REQUEST_BYTES:
        _fail("response_invalid")
    connection: http.client.HTTPConnection | None = None
    try:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=_remaining(deadline_at))
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        connection.request(method, path, body=body, headers=headers)
        _set_timeout(connection, deadline_at)
        response = connection.getresponse()
        if response.status < 200 or response.status >= 300:
            _fail("response_invalid")
        declared = response.getheader("Content-Length")
        if declared is not None:
            try:
                if int(declared) < 0 or int(declared) > _MAX_RESPONSE_BYTES:
                    _fail("response_invalid")
            except ValueError:
                _fail("response_invalid")
        _set_timeout(connection, deadline_at)
        raw = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(raw) > _MAX_RESPONSE_BYTES:
            _fail("response_invalid")
        return _decode_json(raw)
    except LocalModelError:
        raise
    except (socket.timeout, TimeoutError):
        _fail("timeout")
    except (OSError, http.client.HTTPException, ValueError):
        _fail("model_unavailable")
    finally:
        if connection is not None:
            connection.close()


def _set_timeout(connection: http.client.HTTPConnection, deadline_at: float) -> None:
    remaining = _remaining(deadline_at)
    if connection.sock is not None:
        connection.sock.settimeout(remaining)


def _remaining(deadline_at: float) -> float:
    remaining = deadline_at - time.monotonic()
    if remaining <= 0:
        _fail("timeout")
    return remaining


def _decode_json(raw: bytes) -> Any:
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_no_duplicate_object,
            parse_constant=_reject_nonfinite,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        _fail("response_invalid")
    _validate_json_tree(value)
    return value


def _no_duplicate_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            _fail("response_invalid")
        value[key] = item
    return value


def _reject_nonfinite(_: str) -> None:
    _fail("response_invalid")


def _validate_json_tree(value: Any, depth: int = 0, counter: list[int] | None = None) -> None:
    if counter is None:
        counter = [0]
    if depth > _MAX_JSON_DEPTH:
        _fail("response_invalid")
    counter[0] += 1
    if counter[0] > _MAX_JSON_ITEMS:
        _fail("response_invalid")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                _fail("response_invalid")
            _validate_json_tree(item, depth + 1, counter)
    elif isinstance(value, list):
        for item in value:
            _validate_json_tree(item, depth + 1, counter)
    elif isinstance(value, float) and not math.isfinite(value):
        _fail("response_invalid")
    elif type(value) not in (str, int, float, bool, type(None)):
        _fail("response_invalid")


def _encode_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


def _require_cloud_disabled(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {"cloud"}:
        _fail("cloud_required")
    cloud = value["cloud"]
    if not isinstance(cloud, dict) or cloud.get("disabled") is not True:
        _fail("cloud_required")


def _require_selected_tag(value: Any, profile: ModelProfile) -> int:
    if not isinstance(value, dict) or set(value) != {"models"} or not isinstance(value["models"], list):
        _fail("model_unavailable")
    selected = [item for item in value["models"] if isinstance(item, dict) and item.get("name") == profile.name]
    if len(selected) != 1:
        _fail("model_unavailable")
    item = selected[0]
    if item.get("model") != profile.name:
        _fail("model_invalid")
    if item.get("digest") != profile.digest:
        _fail("model_changed")
    size = item.get("size")
    if type(size) is not int or not 0 < size <= _MAX_MODEL_BYTES:
        _fail("model_invalid")
    details = item.get("details")
    if not isinstance(details, dict) or details.get("format") != "gguf":
        _fail("model_invalid")
    _require_no_remote_metadata(item, "model_invalid")
    return size


def _require_selected_show(value: Any, profile: ModelProfile) -> None:
    if not isinstance(value, dict):
        _fail("model_invalid")
    details = value.get("details")
    capabilities = value.get("capabilities")
    if not isinstance(details, dict) or details.get("format") != "gguf":
        _fail("model_invalid")
    if not isinstance(value.get("model_info"), dict) or not value["model_info"]:
        _fail("model_invalid")
    if not isinstance(capabilities, list) or any(not isinstance(capability, str) for capability in capabilities):
        _fail("model_invalid")
    if not {"completion", "vision"}.issubset(capabilities):
        _fail("model_invalid")
    _require_no_remote_metadata(value, "model_invalid")


def _require_version(value: Any) -> str:
    if not isinstance(value, dict) or set(value) != {"version"} or not isinstance(value["version"], str):
        _fail("response_invalid")
    version = value["version"]
    if len(version.encode("ascii", "ignore")) != len(version) or len(version) > _MAX_SEMVER_BYTES or not _SEMVER_RE.fullmatch(version):
        _fail("response_invalid")
    return version


def _require_generate_response(value: Any, profile: ModelProfile) -> str:
    if not isinstance(value, dict) or value.get("model") != profile.name or value.get("done") is not True:
        _fail("response_invalid")
    if "done_reason" in value and value["done_reason"] != "stop":
        _fail("response_invalid")
    _require_no_remote_metadata(value, "response_invalid")
    text = value.get("response")
    if not isinstance(text, str) or len(text.encode("utf-8")) > _MAX_RESPONSE_TEXT_BYTES:
        _fail("response_invalid")
    return text


def _require_no_remote_metadata(value: Any, code: str) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if key in _REMOTE_FIELDS and (not isinstance(item, str) or item != ""):
                _fail(code)
            _require_no_remote_metadata(item, code)
    elif isinstance(value, list):
        for item in value:
            _require_no_remote_metadata(item, code)


def _fail(code: str) -> None:
    raise LocalModelError(code)
