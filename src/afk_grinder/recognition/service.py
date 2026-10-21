"""Warm, disposable OCR recognition worker with memory-only BGR IPC."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import multiprocessing
from multiprocessing.connection import Connection
from pathlib import Path
import queue
import re
import threading
import time
from typing import Any, Callable

from .matcher import LabelHit, LabelMatcher

MAX_FRAME_BYTES = 64 * 1024 * 1024
MAX_FRAME_PIXELS = 16_000_000
MAX_HEADER_BYTES = 16_384
MAX_LABEL_HITS = 512
WARMUP_TIMEOUT = 15.0
MATCH_TIMEOUT = 2.0
WORKER_ERROR = "Recognition label check failed. No input was sent."
WARMUP_ERROR = "Recognition worker could not warm. No input was sent."
TIMEOUT_ERROR = "Recognition label check timed out. No input was sent."
_LABEL_ID = re.compile(r"[a-z][a-z0-9_]{0,31}\Z")


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class Observation:
    width: int
    height: int
    pixels: bytes
    timeout: float
    request_id: int
    deadline: float


@dataclass(frozen=True)
class RecognitionResult:
    hits: tuple[LabelHit, ...] = ()
    error: str = ""


def _validate_frame(width: Any, height: Any, pixels: Any) -> None:
    if (not _integer(width) or not _integer(height) or width <= 0 or height <= 0
            or width * height > MAX_FRAME_PIXELS):
        raise ValueError("Recognition frame dimensions are invalid.")
    if not isinstance(pixels, bytes) or len(pixels) != width * height * 3 or len(pixels) > MAX_FRAME_BYTES:
        raise ValueError("Recognition frame must be bounded immutable BGR bytes matching its dimensions.")


def _validate_labels(labels: Any) -> dict[str, str]:
    if not isinstance(labels, dict) or not 0 < len(labels) <= 32:
        raise ValueError("Recognition worker requires between one and thirty-two fixed labels.")
    if not all(isinstance(label, str) and _LABEL_ID.fullmatch(label)
               and isinstance(pattern, str) and 0 < len(pattern) <= 128
               for label, pattern in labels.items()):
        raise ValueError("Recognition worker labels are invalid.")
    return dict(labels)


def _send(connection: Connection, payload: dict[str, Any]) -> None:
    connection.send_bytes(json.dumps(payload, allow_nan=False, separators=(",", ":")).encode("utf-8"))


def _read_observation(connection: Connection) -> Observation | None:
    header = json.loads(connection.recv_bytes(MAX_HEADER_BYTES).decode("utf-8"))
    if not isinstance(header, dict) or header.get("kind") == "close":
        if isinstance(header, dict) and set(header) == {"kind"} and header["kind"] == "close":
            return None
        raise ValueError("Invalid recognition request.")
    if set(header) != {"kind", "request_id", "width", "height", "timeout"} or header.get("kind") != "match":
        raise ValueError("Invalid recognition request.")
    request_id, width, height, timeout = (header["request_id"], header["width"], header["height"], header["timeout"])
    if not _integer(request_id) or request_id <= 0 or not _finite_number(timeout) or not 0 < timeout <= MATCH_TIMEOUT:
        raise ValueError("Invalid recognition request.")
    pixels = connection.recv_bytes(MAX_FRAME_BYTES)
    _validate_frame(width, height, pixels)
    return Observation(width, height, pixels, float(timeout), request_id, time.monotonic() + float(timeout))


def _serialize_hits(request_id: int, hits: tuple[LabelHit, ...]) -> dict[str, Any]:
    if not _integer(request_id) or request_id <= 0 or len(hits) > MAX_LABEL_HITS:
        raise ValueError("Invalid recognition result.")
    serialized = []
    for hit in hits:
        if (not isinstance(hit, LabelHit) or not _LABEL_ID.fullmatch(hit.label_id)
                or not _finite_number(hit.score) or not 0 <= hit.score <= 1
                or not isinstance(hit.box, tuple) or len(hit.box) != 4
                or not all(_integer(value) for value in hit.box)):
            raise ValueError("Invalid recognition result.")
        serialized.append({"label_id": hit.label_id, "score": hit.score, "box": list(hit.box)})
    return {"kind": "result", "request_id": request_id, "hits": serialized}


def _worker(connection: Connection, model_directory: Path, labels: dict[str, str], start_gate: Any,
            matcher_factory: Callable[[Path, dict[str, str]], LabelMatcher] = LabelMatcher) -> None:
    """Run native OCR only after the parent grants a one-way startup gate."""
    matcher: LabelMatcher | None = None
    try:
        if not start_gate.wait(WARMUP_TIMEOUT):
            return
        try:
            matcher = matcher_factory(model_directory, labels)
            matcher.warmup()
            _send(connection, {"kind": "ready"})
        except Exception:
            _send(connection, {"kind": "error", "error": WARMUP_ERROR})
            return
        while True:
            try:
                observation = _read_observation(connection)
            except (OSError, EOFError, BrokenPipeError):
                return
            except Exception:
                _send(connection, {"kind": "error", "error": WORKER_ERROR})
                continue
            if observation is None:
                return
            try:
                hits = matcher.match_labels(
                    observation.width, observation.height, observation.pixels, timeout=observation.timeout
                )
                _send(connection, _serialize_hits(observation.request_id, hits))
            except Exception:
                _send(connection, {"kind": "error", "error": WORKER_ERROR,
                                   "request_id": observation.request_id})
    finally:
        if matcher is not None:
            try:
                matcher.close()
            except Exception:
                pass
        connection.close()


def _read_message(connection: Connection, labels: set[str], width: int | None = None,
                  height: int | None = None, request_id: int | None = None) -> RecognitionResult | str:
    header = json.loads(connection.recv_bytes(MAX_HEADER_BYTES).decode("utf-8"))
    if not isinstance(header, dict):
        raise ValueError("Invalid recognition response.")
    if header.get("kind") == "ready" and set(header) == {"kind"}:
        return "ready"
    if header.get("kind") == "error":
        expected = {"kind", "error"} if request_id is None else {"kind", "error", "request_id"}
        if set(header) != expected or header.get("error") not in {WORKER_ERROR, WARMUP_ERROR, TIMEOUT_ERROR}:
            raise ValueError("Invalid recognition error.")
        if request_id is not None and header["request_id"] != request_id:
            raise ValueError("Invalid recognition error.")
        return RecognitionResult(error=header["error"])
    if request_id is None or width is None or height is None:
        raise ValueError("Invalid recognition response.")
    if set(header) != {"kind", "request_id", "hits"} or header.get("kind") != "result" or header["request_id"] != request_id:
        raise ValueError("Invalid recognition result.")
    raw_hits = header["hits"]
    if not isinstance(raw_hits, list) or len(raw_hits) > MAX_LABEL_HITS:
        raise ValueError("Invalid recognition result.")
    hits: list[LabelHit] = []
    for raw in raw_hits:
        if not isinstance(raw, dict) or set(raw) != {"label_id", "score", "box"}:
            raise ValueError("Invalid recognition result.")
        label_id, score, box = raw["label_id"], raw["score"], raw["box"]
        if (not isinstance(label_id, str) or label_id not in labels or not _finite_number(score)
                or not 0 <= score <= 1 or not isinstance(box, list) or len(box) != 4
                or not all(_integer(value) for value in box)):
            raise ValueError("Invalid recognition result.")
        x, y, box_width, box_height = box
        if box_width <= 0 or box_height <= 0 or x < 0 or y < 0 or x + box_width > width or y + box_height > height:
            raise ValueError("Invalid recognition result.")
        hits.append(LabelHit(label_id, float(score), tuple(box)))
    return RecognitionResult(hits=tuple(hits))


class RecognitionService:
    """One warmed subprocess. Calls stay nonblocking on the UI and input threads."""

    def __init__(self, model_directory: Path, labels: dict[str, str], *, _context: Any = None,
                 _worker_target: Callable[..., None] = _worker, warmup_timeout: float = WARMUP_TIMEOUT) -> None:
        if not isinstance(model_directory, Path):
            raise ValueError("Recognition model directory must be a Path.")
        if not _finite_number(warmup_timeout) or not 0 < warmup_timeout <= WARMUP_TIMEOUT:
            raise ValueError("Recognition warmup timeout is invalid.")
        self._model_directory = model_directory
        self._labels = _validate_labels(labels)
        self._label_ids = set(self._labels)
        self._warmup_timeout = float(warmup_timeout)
        self._context = _context or multiprocessing.get_context("spawn")
        self._parent, child = self._context.Pipe(duplex=True)
        self._child = child
        self._start_gate = self._context.Event()
        self._process = self._context.Process(target=_worker_target,
                                              args=(child, model_directory, self._labels, self._start_gate),
                                              daemon=True)
        self._requests: queue.Queue[Observation] = queue.Queue(maxsize=1)
        self._results: queue.Queue[RecognitionResult] = queue.Queue(maxsize=1)
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
        if not _finite_number(timeout) or not 0 < timeout <= MATCH_TIMEOUT:
            raise ValueError("Recognition timeout must be finite and at most two seconds.")
        with self._lock:
            if self._state != "ready" or self._pending or self._stopped.is_set():
                raise RuntimeError("Recognition worker is not ready for another frame.")
            self._request_id += 1
            observation = Observation(
                width, height, pixels, float(timeout), self._request_id,
                time.monotonic() + float(timeout),
            )
            self._pending = True
            self._active_request_id = observation.request_id
            timer = threading.Timer(float(timeout), self._expire, args=(observation.request_id,))
            timer.daemon = True
            self._deadline_timer = timer
            # Stop drains this queue while holding the same state lock. Keep
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

    def poll(self) -> RecognitionResult | None:
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
            # Child creation and cancellation share one lifecycle lock. A
            # cancellation that wins before this section cannot leave a child
            # alive after its cleanup has already inspected the process.
            with self._close_lock:
                if self._stopped.is_set():
                    return
                self._launch_active = True
                self._process.start()
                self._child.close()
                self._start_gate.set()
            if not self._await_ready():
                return
            self._serve()
        except Exception:
            self._publish(RecognitionResult(error=WARMUP_ERROR))
        finally:
            self._stop(drop_results=False)
            # The launch thread is the only parent writer. Stop terminates
            # the child but leaves this endpoint open until a blocked write
            # has unwound, avoiding a concurrent close/send race.
            self._close_connections()

    def _await_ready(self) -> bool:
        deadline = time.monotonic() + self._warmup_timeout
        while not self._stopped.is_set() and time.monotonic() < deadline:
            if self._parent.poll(min(0.02, max(0, deadline - time.monotonic()))):
                try:
                    message = _read_message(self._parent, self._label_ids)
                except Exception:
                    self._publish(RecognitionResult(error=WARMUP_ERROR))
                    return False
                if message == "ready":
                    with self._lock:
                        if not self._stopped.is_set():
                            self._state = "ready"
                            return True
                    return False
                self._publish(message if isinstance(message, RecognitionResult) else RecognitionResult(error=WARMUP_ERROR))
                return False
        if not self._stopped.is_set():
            self._publish(RecognitionResult(error=WARMUP_ERROR))
        return False

    def _serve(self) -> None:
        while not self._stopped.is_set():
            try:
                observation = self._requests.get(timeout=0.02)
            except queue.Empty:
                continue
            try:
                # Claim the live request immediately before write. Stop may
                # then kill a non-reading child, which unblocks this writer
                # without waiting on a lifecycle lock.
                with self._lock:
                    permitted = (not self._stopped.is_set() and self._pending
                                 and self._active_request_id == observation.request_id)
                if not permitted:
                    continue
                _send(self._parent, {"kind": "match", "request_id": observation.request_id,
                                     "width": observation.width, "height": observation.height,
                                     "timeout": observation.timeout})
                # Header send can block. Do not send pixels once cancellation
                # has won while it was blocked.
                if self._stopped.is_set():
                    continue
                self._parent.send_bytes(observation.pixels)
                result = self._await_result(observation)
            except Exception:
                result = RecognitionResult(error=WORKER_ERROR)
            completed = self._complete_request(observation.request_id, result)
            if result.error == TIMEOUT_ERROR:
                if completed:
                    self._stop(drop_results=False)
                return

    def _complete_request(self, request_id: int, result: RecognitionResult) -> bool:
        """Publish exactly one current request result; stale or cancelled work is dropped."""
        with self._lock:
            if (self._stopped.is_set() or not self._pending
                    or self._active_request_id != request_id):
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
        """Enforce the caller deadline even when a pipe operation is blocked."""
        if self._complete_request(request_id, RecognitionResult(error=TIMEOUT_ERROR)):
            self._stop(drop_results=False)

    def _await_result(self, observation: Observation) -> RecognitionResult:
        deadline = observation.deadline
        while not self._stopped.is_set() and time.monotonic() < deadline:
            if self._parent.poll(min(0.02, max(0, deadline - time.monotonic()))):
                try:
                    result = _read_message(self._parent, self._label_ids, observation.width,
                                           observation.height, observation.request_id)
                except Exception:
                    return RecognitionResult(error=WORKER_ERROR)
                return result if isinstance(result, RecognitionResult) else RecognitionResult(error=WORKER_ERROR)
            if not self._process.is_alive():
                return RecognitionResult(error=WORKER_ERROR)
        return RecognitionResult(error=TIMEOUT_ERROR)

    def _publish(self, result: RecognitionResult) -> None:
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
