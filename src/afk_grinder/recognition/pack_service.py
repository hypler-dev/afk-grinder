"""Warm, disposable read-only resource-pack recognition worker.

The subprocess bounds native matcher lifetime. It is not an OS sandbox. Frames
remain BGR bytes in memory and the child returns only bounded anchor metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import math
import multiprocessing
from multiprocessing.connection import Connection
import queue
import threading
import time
from typing import Any, Callable

from .matcher import TemplateMatcher
from .pack_compiler import (
    MAX_COMPILED_TEMPLATE_PIXELS,
    MAX_COMPILED_TEMPLATES,
    PackCompileError,
    _validated_snapshot,
    compile_pack,
)
from .pack_results import AnchorHit, PackResultError, aggregate_hits, validate_anchor_hits
from .packs import MAX_ASSET_BYTES, MAX_TOTAL_ASSET_BYTES, PackError, ResourcePack, _validate_png


MAX_FRAME_BYTES = 64 * 1024 * 1024
MAX_FRAME_PIXELS = 16_000_000
MAX_HEADER_BYTES = 16_384
MAX_ANCHORS = 64
WARMUP_TIMEOUT = 15.0
MATCH_TIMEOUT = 2.0
WORKER_ERROR = "Recognition template check failed. No input was sent."
WARMUP_ERROR = "Recognition template worker could not warm. No input was sent."
TIMEOUT_ERROR = "Recognition template check timed out. No input was sent."


def _integer(value: object) -> bool:
    return type(value) is int


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


@dataclass(frozen=True, slots=True)
class PackWorkerConfig:
    """Code-owned immutable process arguments; never sent over the pipe."""

    pack: ResourcePack
    frame_size: tuple[int, int]


@dataclass(frozen=True, slots=True)
class PackObservation:
    width: int
    height: int
    pixels: bytes
    timeout: float
    request_id: int
    deadline: float


@dataclass(frozen=True, slots=True)
class PackRecognitionResult:
    """Anchor metadata only; it is not readiness, stability, or action authority."""

    hits: tuple[AnchorHit, ...] = ()
    error: str = ""
    variant_count: int = 0


class PackTemplateMatcher(TemplateMatcher):
    """Engine-owned limits for compiled pack variants, never pack-controlled."""

    _template_limit = MAX_COMPILED_TEMPLATES
    _template_pixel_limit = MAX_COMPILED_TEMPLATE_PIXELS


def _validate_frame_size(frame_size: object) -> tuple[int, int]:
    if (type(frame_size) is not tuple or len(frame_size) != 2
            or any(type(value) is not int or value <= 0 for value in frame_size)
            or frame_size[0] * frame_size[1] > MAX_FRAME_PIXELS):
        raise ValueError("Recognition frame dimensions are invalid.")
    return frame_size


def _validate_frame(width: object, height: object, pixels: object) -> None:
    if (not _integer(width) or not _integer(height) or width <= 0 or height <= 0
            or width * height > MAX_FRAME_PIXELS):
        raise ValueError("Recognition frame dimensions are invalid.")
    if type(pixels) is not bytes or len(pixels) != width * height * 3 or len(pixels) > MAX_FRAME_BYTES:
        raise ValueError("Recognition frame must be bounded immutable BGR bytes matching its dimensions.")


def _validate_pack(pack: object) -> ResourcePack:
    """Validate snapshot and encoded bytes without decoding pixels in parent."""
    try:
        snapshot = _validated_snapshot(pack)
        total_bytes = 0
        for asset in snapshot.assets:
            if len(asset.data) > MAX_ASSET_BYTES:
                raise ValueError
            total_bytes += len(asset.data)
            if total_bytes > MAX_TOTAL_ASSET_BYTES or sha256(asset.data).hexdigest() != asset.sha256:
                raise ValueError
            _validate_png(asset.data, asset.path)
    except (PackCompileError, PackError, ValueError, TypeError):
        raise ValueError("Recognition pack snapshot is invalid.") from None
    return snapshot


def _validate_config(config: object) -> PackWorkerConfig:
    if type(config) is not PackWorkerConfig:
        raise ValueError("Recognition pack worker configuration is invalid.")
    return PackWorkerConfig(_validate_pack(config.pack), _validate_frame_size(config.frame_size))


def _send(connection: Connection, payload: dict[str, object]) -> None:
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_HEADER_BYTES:
        raise ValueError("Recognition IPC response is too large.")
    connection.send_bytes(encoded)


def _decode_json(data: bytes) -> object:
    def unique_pairs(items: list[tuple[object, object]]) -> dict[object, object]:
        result: dict[object, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(
        data.decode("utf-8"),
        object_pairs_hook=unique_pairs,
        parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("non-finite JSON")),
    )


def _read_observation(connection: Connection, frame_size: tuple[int, int]) -> PackObservation | None:
    header = _decode_json(connection.recv_bytes(MAX_HEADER_BYTES))
    if type(header) is not dict:
        raise ValueError("Invalid recognition request.")
    if set(header) == {"kind"} and header["kind"] == "close":
        return None
    if set(header) != {"kind", "request_id", "width", "height", "timeout"} or header["kind"] != "match":
        raise ValueError("Invalid recognition request.")
    request_id, width, height, timeout = (
        header["request_id"], header["width"], header["height"], header["timeout"],
    )
    if (not _integer(request_id) or request_id <= 0 or not _finite_number(timeout)
            or not 0 < timeout <= MATCH_TIMEOUT or (width, height) != frame_size):
        raise ValueError("Invalid recognition request.")
    pixels = connection.recv_bytes(MAX_FRAME_BYTES)
    _validate_frame(width, height, pixels)
    return PackObservation(width, height, pixels, float(timeout), request_id, time.monotonic() + float(timeout))


def _serialize_hits(request_id: int, hits: tuple[AnchorHit, ...], variant_count: int) -> dict[str, object]:
    if (not _integer(request_id) or request_id <= 0 or type(hits) is not tuple or len(hits) > MAX_ANCHORS
            or not _integer(variant_count) or not 0 < variant_count <= MAX_COMPILED_TEMPLATES):
        raise ValueError("Invalid recognition result.")
    anchors = []
    for hit in hits:
        if type(hit) is not AnchorHit or type(hit.id) is not str or not hit.id:
            raise ValueError("Invalid recognition result.")
        if hit.score is not None and (not _finite_number(hit.score) or not 0 <= hit.score <= 1):
            raise ValueError("Invalid recognition result.")
        if hit.box is not None and (type(hit.box) is not tuple or len(hit.box) != 4
                                    or any(not _integer(value) for value in hit.box)):
            raise ValueError("Invalid recognition result.")
        anchors.append({"id": hit.id, "score": hit.score, "box": list(hit.box) if hit.box is not None else None})
    return {"kind": "result", "request_id": request_id, "variant_count": variant_count, "anchors": anchors}


def _worker(connection: Connection, config: PackWorkerConfig, start_gate: Any,
            matcher_factory: Callable[[tuple], TemplateMatcher] = PackTemplateMatcher) -> None:
    """Run native matching only after parent owns a process handle and opens gate."""
    matcher: TemplateMatcher | None = None
    try:
        if not start_gate.wait(WARMUP_TIMEOUT):
            return
        try:
            config = _validate_config(config)
            compiled = compile_pack(config.pack, config.frame_size)
            matcher = matcher_factory(tuple(item.spec for item in compiled.templates))
            matcher.warmup()
            _send(connection, {"kind": "ready"})
        except Exception:
            _send(connection, {"kind": "error", "error": WARMUP_ERROR})
            return
        while True:
            try:
                observation = _read_observation(connection, config.frame_size)
            except (OSError, EOFError, BrokenPipeError):
                return
            except Exception:
                _send(connection, {"kind": "error", "error": WORKER_ERROR})
                continue
            if observation is None:
                return
            try:
                hits = matcher.match(observation.width, observation.height, observation.pixels, timeout=observation.timeout)
                anchors = aggregate_hits(config.pack, compiled, hits)
                _send(connection, _serialize_hits(observation.request_id, anchors, len(compiled.templates)))
            except Exception:
                _send(connection, {"kind": "error", "error": WORKER_ERROR, "request_id": observation.request_id})
    finally:
        if matcher is not None:
            try:
                matcher.close()
            except Exception:
                pass
        connection.close()


def _read_message(connection: Connection, pack: ResourcePack, frame_size: tuple[int, int],
                  request_id: int | None = None) -> PackRecognitionResult | str:
    header = _decode_json(connection.recv_bytes(MAX_HEADER_BYTES))
    if type(header) is not dict:
        raise ValueError("Invalid recognition response.")
    if header.get("kind") == "ready" and set(header) == {"kind"}:
        return "ready"
    if header.get("kind") == "error":
        expected = {"kind", "error"} if request_id is None else {"kind", "error", "request_id"}
        if (set(header) != expected or header.get("error") not in {WORKER_ERROR, WARMUP_ERROR, TIMEOUT_ERROR}
                or request_id is not None and (not _integer(header["request_id"])
                                               or header["request_id"] != request_id)):
            raise ValueError("Invalid recognition error.")
        return PackRecognitionResult(error=header["error"])
    if request_id is None or set(header) != {"kind", "request_id", "variant_count", "anchors"}:
        raise ValueError("Invalid recognition result.")
    if (header.get("kind") != "result" or not _integer(header["request_id"])
            or header["request_id"] != request_id):
        raise ValueError("Invalid recognition result.")
    variant_count, raw_hits = header["variant_count"], header["anchors"]
    if (not _integer(variant_count) or not 0 < variant_count <= MAX_COMPILED_TEMPLATES
            or type(raw_hits) is not list or len(raw_hits) > MAX_ANCHORS):
        raise ValueError("Invalid recognition result.")
    hits: list[AnchorHit] = []
    for raw in raw_hits:
        if type(raw) is not dict or set(raw) != {"id", "score", "box"} or type(raw["id"]) is not str:
            raise ValueError("Invalid recognition result.")
        score, box = raw["score"], raw["box"]
        if score is not None and (not _finite_number(score) or not 0 <= score <= 1):
            raise ValueError("Invalid recognition result.")
        if box is not None and (type(box) is not list or len(box) != 4 or any(not _integer(value) for value in box)):
            raise ValueError("Invalid recognition result.")
        hits.append(AnchorHit(raw["id"], None if score is None else float(score), None if box is None else tuple(box)))
    try:
        validated = validate_anchor_hits(pack, frame_size, tuple(hits))
    except PackResultError:
        raise ValueError("Invalid recognition result.") from None
    return PackRecognitionResult(validated, variant_count=variant_count)


class PackRecognitionService:
    """One warmed disposable child for one immutable pack and exact frame size."""

    def __init__(self, pack: ResourcePack, frame_size: tuple[int, int], *, _context: Any = None,
                 _worker_target: Callable[..., None] = _worker, warmup_timeout: float = WARMUP_TIMEOUT) -> None:
        if not _finite_number(warmup_timeout) or not 0 < warmup_timeout <= WARMUP_TIMEOUT:
            raise ValueError("Recognition warmup timeout is invalid.")
        self._config = PackWorkerConfig(_validate_pack(pack), _validate_frame_size(frame_size))
        self._warmup_timeout = float(warmup_timeout)
        self._context = _context or multiprocessing.get_context("spawn")
        self._parent, child = self._context.Pipe(duplex=True)
        self._child = child
        self._start_gate = self._context.Event()
        self._process = self._context.Process(target=_worker_target, args=(child, self._config, self._start_gate), daemon=True)
        self._requests: queue.Queue[PackObservation] = queue.Queue(maxsize=1)
        self._results: queue.Queue[PackRecognitionResult] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._close_lock = threading.Lock()
        self._connection_close_lock = threading.Lock()
        self._stopped = threading.Event()
        self._thread: threading.Thread | None = None
        self._state = "new"
        self._request_id = 0
        self._pending = False
        self._active_request_id: int | None = None
        self._deadline_timer: threading.Timer | None = None
        self._launch_active = False
        self._connections_closed = False

    @property
    def ready(self) -> bool:
        with self._lock:
            return self._state == "ready" and not self._stopped.is_set()

    def start(self) -> None:
        with self._lock:
            if self._state != "new":
                raise RuntimeError("Recognition worker has already started.")
            self._state = "warming"
            self._thread = threading.Thread(target=self._launch, daemon=True)
            self._thread.start()

    def submit(self, width: int, height: int, pixels: bytes, *, timeout: float = MATCH_TIMEOUT) -> None:
        _validate_frame(width, height, pixels)
        if (width, height) != self._config.frame_size:
            raise ValueError("Recognition frame dimensions do not match this worker.")
        if not _finite_number(timeout) or not 0 < timeout <= MATCH_TIMEOUT:
            raise ValueError("Recognition timeout must be finite and at most two seconds.")
        with self._lock:
            if self._state != "ready" or self._pending or self._stopped.is_set():
                raise RuntimeError("Recognition worker is not ready for another frame.")
            self._request_id += 1
            observation = PackObservation(width, height, pixels, float(timeout), self._request_id,
                                          time.monotonic() + float(timeout))
            self._pending = True
            self._active_request_id = observation.request_id
            timer = threading.Timer(float(timeout), self._expire, args=(observation.request_id,))
            timer.daemon = True
            self._deadline_timer = timer
            # Stop drains this queue while holding the same state lock.  Keep
            # admission and publication together so a frame cannot be added
            # after cancellation has drained the queue.
            try:
                self._requests.put_nowait(observation)
            except queue.Full:
                self._pending = False
                self._active_request_id = None
                self._deadline_timer = None
                raise RuntimeError("Recognition worker is not ready for another frame.") from None
            timer.start()

    def poll(self) -> PackRecognitionResult | None:
        try:
            return self._results.get_nowait()
        except queue.Empty:
            return None

    def cancel(self) -> None:
        self._stop(drop_results=True)

    def close(self) -> None:
        self._stop(drop_results=True)

    def _launch(self) -> None:
        try:
            # Child creation and cancellation share one lifecycle lock.  A
            # cancellation that wins before this section cannot leave a child
            # alive after its cleanup has already inspected the process.
            with self._close_lock:
                if self._stopped.is_set():
                    return
                self._launch_active = True
                self._process.start()
                self._child.close()
                self._start_gate.set()
            if self._await_ready():
                self._serve()
        except Exception:
            self._publish(PackRecognitionResult(error=WARMUP_ERROR))
        finally:
            self._stop(drop_results=False)
            # The launch thread is the only parent writer.  Stop terminates
            # the child but leaves this endpoint open until a blocked write
            # has unwound, avoiding a concurrent close/send race.
            self._close_connections()

    def _await_ready(self) -> bool:
        deadline = time.monotonic() + self._warmup_timeout
        while not self._stopped.is_set() and time.monotonic() < deadline:
            if self._parent.poll(min(0.02, max(0.0, deadline - time.monotonic()))):
                try:
                    message = _read_message(self._parent, self._config.pack, self._config.frame_size)
                except Exception:
                    self._publish(PackRecognitionResult(error=WARMUP_ERROR))
                    return False
                if message == "ready":
                    with self._lock:
                        if not self._stopped.is_set():
                            self._state = "ready"
                            return True
                    return False
                self._publish(message if isinstance(message, PackRecognitionResult) else PackRecognitionResult(error=WARMUP_ERROR))
                return False
        if not self._stopped.is_set():
            self._publish(PackRecognitionResult(error=WARMUP_ERROR))
        return False

    def _serve(self) -> None:
        while not self._stopped.is_set():
            try:
                observation = self._requests.get(timeout=0.02)
            except queue.Empty:
                continue
            try:
                # Claim the live request immediately before write.  The stop
                # path may then kill a non-reading child, which unblocks this
                # writer without waiting on a lifecycle lock.
                with self._lock:
                    permitted = (not self._stopped.is_set() and self._pending
                                 and self._active_request_id == observation.request_id)
                if not permitted:
                    continue
                _send(self._parent, {"kind": "match", "request_id": observation.request_id,
                                     "width": observation.width, "height": observation.height,
                                     "timeout": observation.timeout})
                self._parent.send_bytes(observation.pixels)
                result = self._await_result(observation)
            except Exception:
                result = PackRecognitionResult(error=WORKER_ERROR)
            completed = self._complete_request(observation.request_id, result)
            if result.error == TIMEOUT_ERROR:
                if completed:
                    self._stop(drop_results=False)
                return

    def _await_result(self, observation: PackObservation) -> PackRecognitionResult:
        while not self._stopped.is_set() and time.monotonic() < observation.deadline:
            if self._parent.poll(min(0.02, max(0.0, observation.deadline - time.monotonic()))):
                try:
                    result = _read_message(self._parent, self._config.pack, self._config.frame_size,
                                           observation.request_id)
                except Exception:
                    return PackRecognitionResult(error=WORKER_ERROR)
                return result if isinstance(result, PackRecognitionResult) else PackRecognitionResult(error=WORKER_ERROR)
            if not self._process.is_alive():
                return PackRecognitionResult(error=WORKER_ERROR)
        return PackRecognitionResult(error=TIMEOUT_ERROR)

    def _complete_request(self, request_id: int, result: PackRecognitionResult) -> bool:
        with self._lock:
            if self._stopped.is_set() or not self._pending or self._active_request_id != request_id:
                return False
            timer = self._deadline_timer
            self._deadline_timer = None
            self._active_request_id = None
            self._pending = False
        if timer is not None:
            timer.cancel()
        self._publish(result)
        return True

    def _expire(self, request_id: int) -> None:
        if self._complete_request(request_id, PackRecognitionResult(error=TIMEOUT_ERROR)):
            self._stop(drop_results=False)

    def _publish(self, result: PackRecognitionResult) -> None:
        with self._lock:
            if self._stopped.is_set():
                return
            try:
                self._results.put_nowait(result)
            except queue.Full:
                pass

    def _stop(self, *, drop_results: bool) -> None:
        with self._close_lock:
            already_stopped = self._stopped.is_set()
            self._stopped.set()
            with self._lock:
                self._state = "closed"
                self._pending = False
                self._active_request_id = None
                timer = self._deadline_timer
                self._deadline_timer = None
            if timer is not None:
                timer.cancel()
            while True:
                try:
                    self._requests.get_nowait()
                except queue.Empty:
                    break
            if drop_results:
                while True:
                    try:
                        self._results.get_nowait()
                    except queue.Empty:
                        break
            if not already_stopped:
                try:
                    if self._process.is_alive():
                        self._process.terminate()
                        self._process.join(timeout=0.2)
                    if self._process.is_alive():
                        self._process.kill()
                        self._process.join(timeout=0.2)
                finally:
                    if not self._launch_active:
                        self._close_connections()

    def _close_connections(self) -> None:
        """Close endpoints once no parent pipe write can still be active."""
        with self._connection_close_lock:
            if self._connections_closed:
                return
            self._connections_closed = True
            self._parent.close()
            self._child.close()
