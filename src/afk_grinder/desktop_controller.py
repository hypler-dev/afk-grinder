"""Local-only controller for the three-method desktop launcher bridge.

This module deliberately imports no UI toolkit, WebView package, or native
platform module. Native backend work is confined to short-lived daemon jobs.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import math
import queue
import secrets
import struct
import threading
import time
from typing import Any, Callable
import zlib

from afk_grinder.capture import CaptureDiagnostic, CapturedWindow, capture_error_type
from afk_grinder.capture.service import BackgroundJob, JobResult
from afk_grinder.engine import Runner
from afk_grinder.models import Target, Workflow
from afk_grinder.recognition.frame_geometry import layout_from_capture
from afk_grinder.recognition.observation import Layout, ObservationTracker, Rect
from afk_grinder.templates import DEFAULT_TEMPLATE, parse_template


_GAMES = (
    {"id": "adopt", "name": "Adopt Me", "genre": "Social roleplay", "supported": True,
     "art": "assets/pet-world.png"},
    {"id": "bee", "name": "Bee Swarm Simulator", "genre": "Collection adventure", "supported": False,
     "art": "assets/bee-fields.png"},
    {"id": "blox", "name": "Blox Fruits", "genre": "Action adventure", "supported": False,
     "art": "assets/ocean-adventure.png"},
)
_GAME_IDS = frozenset(game["id"] for game in _GAMES)
_SCAN_TIMEOUT = 2.0
_MAX_EVENT_DRAIN = 16
_MAX_PNG_WIDTH = 640
_MAX_PNG_HEIGHT = 360


@dataclass(frozen=True)
class _ScanResult:
    generation: int
    targets: tuple[Target, ...]
    readiness: tuple[str, ...]
    error: bool = False


@dataclass(frozen=True)
class _JobContext:
    generation: int
    operation: str
    target: Target | None
    area: Rect | None = None
    source_layout: Layout | None = None


def _error(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _is_int(value: Any) -> bool:
    return type(value) is int


def _safe_diagnostic(diagnostic: CaptureDiagnostic | None) -> dict[str, str]:
    if not isinstance(diagnostic, CaptureDiagnostic):
        return {"code": "unexpected", "stage": "worker", "error_type": "unexpected",
                "message": "Preview failed. No input was sent."}
    return {
        "code": diagnostic.code,
        "stage": diagnostic.stage,
        "error_type": diagnostic.error_type,
        "message": (
            "Capture permission is missing for this build. On macOS, enable Screen Recording "
            "in Privacy & Security, then reopen this app. No input was sent."
            if diagnostic.code == "permission" else "Preview failed. No input was sent."
        ),
    }


class DesktopController:
    """Thread-safe, local controller behind the trusted launcher facade."""

    def __init__(
        self,
        *,
        backend: Any,
        runner: Runner | None = None,
        job_factory: Callable[..., Any] = BackgroundJob,
        clock: Callable[[], float] = time.monotonic,
        buildmetadata: dict[str, Any] | None = None,
    ) -> None:
        self._backend = backend
        self._runner = runner if runner is not None else Runner(backend)
        self._job_factory = job_factory
        self._clock = clock
        self._lock = threading.RLock()
        self._closing = False
        self._mode = "dry"
        self._game_id = "adopt"
        self._workflow: Workflow | None = parse_template(DEFAULT_TEMPLATE)
        self._template_json = DEFAULT_TEMPLATE
        self._template_error = ""
        self._acknowledged = False
        self._starting = False
        self._start_cancel: threading.Event | None = None
        self._message = "Ready for a dry run."
        self._run_phase = "idle"
        self._close_stop_started = False
        self._close_stop_done = threading.Event()
        self._scan_queue: queue.Queue[_ScanResult] = queue.Queue(maxsize=1)
        self._scan_thread: threading.Thread | None = None
        self._scan_started_at = 0.0
        self._scan_completed_at = 0.0
        self._scan_generation = 0
        self._targets: dict[str, Target] = {}
        self._selected_id: str | None = None
        self._explicit_target: Target | None = None
        self._binding_phase = "searching" if backend is not None else "unsupported"
        self._binding_message = "Looking for Roblox." if backend is not None else "Native backend is unavailable."
        self._readiness_phase = "unknown"
        self._readiness_issues: list[str] = []
        self._job: Any | None = None
        self._job_context: _JobContext | None = None
        self._job_generation = 0
        self._preview_id = 0
        self._preview_phase = "empty"
        self._preview_width = 0
        self._preview_height = 0
        self._preview_region_kind = "none"
        self._preview_verified = False
        self._preview_error: dict[str, str] | None = None
        self._preview_frame: CapturedWindow | None = None
        self._preview_layout: Layout | None = None
        self._preview_png: str | None = None
        self._png_queue: queue.Queue[tuple[int, str | CaptureDiagnostic]] = queue.Queue(maxsize=1)
        self._sdk_phase = "unchecked"
        self._sdk_message = "Recognition has not been checked."
        self._area: Rect | None = None
        self._area_layout: Layout | None = None
        self._tracker = ObservationTracker()
        metadata = dict(buildmetadata or {})
        self._app = {
            "version": str(metadata.get("version", "0.2.0")),
            "commit": str(metadata.get("commit", "development")),
            "platform": str(metadata.get("platform", "unknown")),
            "limit_seconds": 30,
            "countdown_seconds": 3,
        }
        self._start_scan()

    def get_state(self) -> dict[str, Any]:
        """Return a snapshot with no pixels, native calls, or exception text."""
        self._poll()
        with self._lock:
            selected = self._selected_id if self._selected_id in self._targets else None
            candidates = [
                {"id": target_id, "label": f"Roblox player {index}"}
                for index, target_id in enumerate(sorted(self._targets), 1)
            ]
            cleanup_failed = bool(getattr(self._runner, "cleanup_failed", False))
            input_locked = bool(getattr(self._runner, "running", False)) or self._job is not None
            phase = self._session_phase(cleanup_failed, input_locked)
            return {
                "schema_version": 1,
                "app": dict(self._app),
                "games": [dict(game) for game in _GAMES],
                "game_id": self._game_id,
                "mode": self._mode,
                "binding": {
                    "phase": self._binding_phase,
                    "label": "Roblox selected." if selected else "",
                    "message": self._binding_message,
                    "selected_id": selected,
                    "candidates": candidates,
                },
                "readiness": {"phase": self._readiness_phase, "issues": list(self._readiness_issues)},
                "session": {
                    "phase": phase,
                    "message": self._message,
                    "can_start": self._can_start(cleanup_failed, input_locked),
                    "acknowledged": self._acknowledged,
                    "input_locked": input_locked,
                    "cleanup_failed": cleanup_failed,
                },
                "preview": {
                    "phase": self._preview_phase,
                    "id": self._preview_id,
                    "width": self._preview_width,
                    "height": self._preview_height,
                    "content_verified": self._preview_verified,
                    "region_kind": self._preview_region_kind,
                    "area": self._area_payload(),
                    "geometry": self._geometry_phase(),
                    "error": dict(self._preview_error) if self._preview_error else None,
                },
                "sdk": {"phase": self._sdk_phase, "message": self._sdk_message},
                "template": {
                    "json": self._template_json,
                    "valid": self._workflow is not None,
                    "error": self._template_error,
                    "name": self._workflow.name if self._workflow else "",
                    "steps": len(self._workflow.steps) if self._workflow else 0,
                    "duration_ms": sum(step.duration_ms for step in self._workflow.steps) if self._workflow else 0,
                },
            }

    def get_preview(self, preview_id: Any) -> dict[str, str] | None:
        """Return only the current bounded in-memory PNG after daemon encoding."""
        self._poll()
        if not _is_int(preview_id):
            return None
        with self._lock:
            if preview_id != self._preview_id or self._preview_png is None:
                return None
            return {"id": preview_id, "data_url": self._preview_png}

    def command(self, name: Any, payload: Any) -> dict[str, Any]:
        """Apply one strict bridge command and always include the new state."""
        self._poll()
        if not isinstance(name, str) or not isinstance(payload, dict):
            return self._response(False, "invalid_command", "Command is malformed.")
        allowed = {
            "select_game", "set_mode", "refresh_targets", "select_target", "refresh_readiness",
            "set_ack", "set_template", "start", "stop", "capture", "clear_preview", "set_area",
            "reset_area", "check_area", "sdk_check",
        }
        if name not in allowed:
            return self._response(False, "unknown_command", "Command is not supported.")
        with self._lock:
            closing = self._closing
        if closing and name != "stop":
            return self._response(False, "closing", "Application is closing.")
        try:
            if name == "stop":
                self._require_payload(payload, set())
                self._stop()
            elif name == "select_game":
                self._select_game(payload)
            elif name == "set_mode":
                self._set_mode(payload)
            elif name == "refresh_targets":
                self._require_payload(payload, set())
                self._start_scan()
            elif name == "select_target":
                self._select_target(payload)
            elif name == "refresh_readiness":
                self._require_payload(payload, set())
                self._start_scan()
            elif name == "set_ack":
                self._set_ack(payload)
            elif name == "set_template":
                self._set_template(payload)
            elif name == "start":
                self._start(payload)
            elif name == "capture":
                self._require_payload(payload, set())
                self._start_capture()
            elif name == "clear_preview":
                self._require_payload(payload, set())
                self._clear_preview()
            elif name == "set_area":
                self._set_area(payload)
            elif name == "reset_area":
                self._require_payload(payload, set())
                self._reset_area()
            elif name == "check_area":
                self._check_area(payload)
            else:
                self._require_payload(payload, set())
                self._start_sdk_check()
        except ValueError as error:
            return self._response(False, "invalid_payload", str(error))
        except RuntimeError as error:
            return self._response(False, "blocked", str(error))
        except Exception:
            return self._response(False, "failed", "Command could not be completed.")
        return self._response(True)

    def close(self) -> bool:
        """Begin close without joining or calling native APIs while locked."""
        job = None
        with self._lock:
            self._closing = True
            self._acknowledged = False
            if self._start_cancel is not None:
                self._start_cancel.set()
            job = self._detach_job_locked()
            self._clear_preview_locked()
        if job is not None:
            job.cancel()
        with self._lock:
            if not self._close_stop_started:
                self._close_stop_started = True
                threading.Thread(target=self._close_stop, daemon=True, name="close-stop").start()
            return (self._close_stop_done.is_set() and not self._starting
                    and not bool(getattr(self._runner, "running", False)))

    def _close_stop(self) -> None:
        try:
            self._runner.stop()
        finally:
            self._close_stop_done.set()

    def _response(self, ok: bool, code: str | None = None, message: str | None = None) -> dict[str, Any]:
        return {"ok": ok, "error": None if ok else _error(code or "blocked", message or "Blocked."),
                "state": self.get_state()}

    @staticmethod
    def _require_payload(payload: dict[str, Any], keys: set[str]) -> None:
        if set(payload) != keys:
            raise ValueError("Payload fields are invalid.")

    def _select_game(self, payload: dict[str, Any]) -> None:
        self._require_payload(payload, {"game_id"})
        game_id = payload["game_id"]
        if not isinstance(game_id, str) or game_id not in _GAME_IDS:
            raise ValueError("Game selection is invalid.")
        with self._lock:
            if self._busy_locked():
                raise RuntimeError("Stop active work before changing games.")
            self._game_id = game_id
            self._scan_generation += 1
            self._clear_target_locked()
            self._clear_preview_locked()
            self._acknowledged = False
            self._message = "Game changed. Select setup again."
            self._readiness_phase = "unknown"
            self._readiness_issues = []
            self._binding_phase = "searching" if game_id == "adopt" else "unsupported"
            self._binding_message = "Looking for Roblox." if game_id == "adopt" else "This profile is not supported yet."
        self._start_scan()

    def _set_mode(self, payload: dict[str, Any]) -> None:
        self._require_payload(payload, {"mode"})
        mode = payload["mode"]
        if mode not in {"dry", "live"}:
            raise ValueError("Mode is invalid.")
        with self._lock:
            if self._busy_locked():
                raise RuntimeError("Stop active work before changing mode.")
            self._mode = mode
            self._acknowledged = False

    def _select_target(self, payload: dict[str, Any]) -> None:
        self._require_payload(payload, {"target_id"})
        target_id = payload["target_id"]
        if not isinstance(target_id, str):
            raise ValueError("Target selection is invalid.")
        with self._lock:
            if self._busy_locked() or target_id not in self._targets:
                raise RuntimeError("Target is no longer available.")
            self._selected_id = target_id
            self._explicit_target = self._targets[target_id]
            self._binding_phase = "bound"
            self._binding_message = "Roblox selected."
            self._acknowledged = False
            self._clear_preview_locked()

    def _set_ack(self, payload: dict[str, Any]) -> None:
        self._require_payload(payload, {"acknowledged"})
        if not isinstance(payload["acknowledged"], bool):
            raise ValueError("Acknowledgment must be a boolean.")
        with self._lock:
            if self._busy_locked() or self._game_id != "adopt":
                raise RuntimeError("Acknowledgment is unavailable.")
            self._acknowledged = payload["acknowledged"]

    def _set_template(self, payload: dict[str, Any]) -> None:
        self._require_payload(payload, {"json"})
        source = payload["json"]
        if not isinstance(source, str):
            raise ValueError("Template must be text.")
        with self._lock:
            if self._busy_locked() or self._game_id != "adopt":
                raise RuntimeError("Stop active work before changing the template.")
        try:
            workflow = parse_template(source)
        except ValueError:
            with self._lock:
                self._workflow = None
                self._template_json = source
                self._template_error = "Template is invalid."
            return
        with self._lock:
            self._workflow = workflow
            self._template_json = source
            self._template_error = ""
            self._acknowledged = False

    def _start(self, payload: dict[str, Any]) -> None:
        with self._lock:
            dry_run = self._mode == "dry"
            acknowledged = self._acknowledged
            if not dry_run:
                self._acknowledged = False
            self._require_payload(payload, set())
            if self._closing:
                raise RuntimeError("Application is closing.")
            if self._starting or self._busy_locked():
                raise RuntimeError("A run or observation is already active.")
            if self._game_id != "adopt" or self._workflow is None:
                raise RuntimeError("This game profile cannot start input.")
            if bool(getattr(self._runner, "cleanup_failed", False)):
                raise RuntimeError("Input cleanup needs manual attention before another run.")
            target = self._targets.get(self._selected_id or "")
            if not dry_run:
                if not acknowledged or target is None or self._readiness_phase != "ready":
                    raise RuntimeError("Live input needs a selected target, readiness, and fresh acknowledgment.")
            self._starting = True
            self._run_phase = "countdown"
            cancel_event = threading.Event()
            self._start_cancel = cancel_event
            workflow = self._workflow
        try:
            self._runner.start(workflow, target=target, dry_run=dry_run, armed=not dry_run,
                               cancel_event=cancel_event)
        except Exception:
            with self._lock:
                self._message = "Run could not start."
            raise RuntimeError("Run could not start.") from None
        finally:
            with self._lock:
                self._starting = False

    def _stop(self) -> None:
        with self._lock:
            self._acknowledged = False
            if self._start_cancel is not None:
                self._start_cancel.set()
            active = self._starting or bool(getattr(self._runner, "running", False))
            self._message = "Stopping input." if active else "Input stopped."
            self._run_phase = "stopping" if active else "stopped"
        self._runner.stop()

    def _start_capture(self) -> None:
        with self._lock:
            if (self._game_id != "adopt" or self._busy_locked()
                    or bool(getattr(self._runner, "cleanup_failed", False))):
                raise RuntimeError("Capture is unavailable while input is active or for this game.")
            target = self._targets.get(self._selected_id or "")
            if target is None:
                raise RuntimeError("Select a verified Roblox target first.")
            self._acknowledged = False
            self._clear_preview_locked()
            self._begin_job_locked("capture", target)

    def _start_sdk_check(self) -> None:
        with self._lock:
            if self._busy_locked() or self._game_id != "adopt" or bool(getattr(self._runner, "cleanup_failed", False)):
                raise RuntimeError("Stop active work before checking recognition.")
            self._sdk_phase = "checking"
            self._sdk_message = "Checking optional recognition with synthetic data."
            self._begin_job_locked("sdk", None)

    def _begin_job_locked(self, operation: str, target: Target | None,
                          area: Rect | None = None, source_layout: Layout | None = None) -> None:
        self._job_generation += 1
        self._job = self._job_factory(operation, target)
        self._job_context = _JobContext(self._job_generation, operation, target, area, source_layout)
        if operation == "capture":
            self._preview_phase = "capturing"
            self._preview_error = None

    def _clear_preview(self) -> None:
        job = None
        with self._lock:
            if self._starting or bool(getattr(self._runner, "running", False)):
                raise RuntimeError("Stop input before clearing the preview.")
            job = self._detach_job_locked()
            self._clear_preview_locked()
        if job is not None:
            job.cancel()

    def _clear_preview_locked(self) -> None:
        self._preview_id += 1
        self._preview_phase = "empty"
        self._preview_width = self._preview_height = 0
        self._preview_region_kind = "none"
        self._preview_verified = False
        self._preview_error = None
        self._preview_frame = None
        self._preview_layout = None
        self._preview_png = None
        self._clear_geometry_locked()

    def _clear_geometry_locked(self) -> None:
        self._area = None
        self._area_layout = None
        self._tracker.invalidate()

    def _reset_area(self) -> None:
        with self._lock:
            self._require_reference_mutation_locked()
            self._area = None
            self._area_layout = None
            self._tracker.invalidate()

    def _set_area(self, payload: dict[str, Any]) -> None:
        self._require_payload(payload, {"preview_id", "rect"})
        with self._lock:
            self._require_reference_mutation_locked()
            if (not _is_int(payload["preview_id"]) or payload["preview_id"] != self._preview_id
                    or self._preview_layout is None):
                raise RuntimeError("Preview is no longer current.")
            rect = payload["rect"]
            if not isinstance(rect, dict) or set(rect) != {"x", "y", "width", "height"}:
                raise ValueError("Area is invalid.")
            values = tuple(rect[key] for key in ("x", "y", "width", "height"))
            if not all(_is_int(value) and value >= 0 for value in values):
                raise ValueError("Area must use non-negative whole pixels.")
            x, y, width, height = values
            image_width, image_height = self._preview_layout.physical_size
            if width <= 0 or height <= 0 or width * 9 != height * 16:
                raise ValueError("Area must be 16:9.")
            if x + width > image_width or y + height > image_height:
                raise ValueError("Area is outside the preview.")
            self._area = Rect(x, y, width, height)
            self._area_layout = self._preview_layout
            self._tracker.invalidate()

    def _check_area(self, payload: dict[str, Any]) -> None:
        self._require_payload(payload, {"preview_id"})
        with self._lock:
            self._require_reference_mutation_locked()
            if (not _is_int(payload["preview_id"]) or payload["preview_id"] != self._preview_id
                    or self._area is None or self._area_layout is None):
                raise RuntimeError("A current area is required.")
            if self._busy_locked():
                raise RuntimeError("Stop active work before checking the area.")
            target = self._targets.get(self._selected_id or "")
            if target is None:
                raise RuntimeError("Select a verified Roblox target first.")
            area, layout = self._area, self._area_layout
            self._preview_id += 1
            self._preview_frame = None
            self._preview_layout = None
            self._preview_png = None
            self._preview_width = self._preview_height = 0
            self._tracker.invalidate()
            self._begin_job_locked("capture", target, area, layout)

    def _start_scan(self) -> None:
        with self._lock:
            if (self._backend is None or self._closing or self._game_id != "adopt"
                    or self._starting or bool(getattr(self._runner, "running", False))):
                return
            if self._scan_thread is not None and self._scan_thread.is_alive():
                return
            self._scan_generation += 1
            self._scan_started_at = self._clock()
            if self._binding_phase in {"error", "searching", "unsupported"}:
                self._binding_phase = "searching"
                self._binding_message = "Looking for Roblox."
            generation = self._scan_generation
            thread = threading.Thread(target=self._scan_worker, args=(generation,), daemon=True,
                                      name="target-discovery")
            self._scan_thread = thread
        thread.start()

    def _scan_worker(self, generation: int) -> None:
        try:
            targets = tuple(self._backend.discover_targets())
            readiness = tuple(self._backend.readiness())
            result = _ScanResult(generation, targets, readiness)
        except Exception:
            result = _ScanResult(generation, (), (), error=True)
        try:
            self._scan_queue.put_nowait(result)
        except queue.Full:
            try:
                self._scan_queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._scan_queue.put_nowait(result)
            except queue.Full:
                pass

    def _poll(self) -> None:
        stop_runner = False
        cancel_job = None
        rescan = False
        with self._lock:
            if self._scan_thread is not None and self._scan_thread.is_alive() and self._clock() - self._scan_started_at > _SCAN_TIMEOUT:
                self._scan_generation += 1
                self._clear_target_locked()
                self._clear_preview_locked()
                self._binding_phase = "error"
                self._binding_message = "Target discovery timed out."
                self._readiness_phase = "unknown"
                self._acknowledged = False
                stop_runner = self._mode == "live"
                if stop_runner and self._start_cancel is not None:
                    self._start_cancel.set()
            while True:
                try:
                    scan = self._scan_queue.get_nowait()
                except queue.Empty:
                    break
                if scan.generation != self._scan_generation:
                    continue
                if self._apply_scan_locked(scan):
                    stop_runner = True
            self._drain_runner_events_locked()
            if self._job is not None:
                result = self._job.poll()
                if result is not None:
                    cancel_job = self._complete_job_locked(result)
            self._drain_png_locked()
            if self._preview_frame is not None and self._preview_phase == "available":
                now = self._clock()
                if now < self._preview_frame.captured_at or now - self._preview_frame.captured_at > 0.5:
                    self._tracker.invalidate()
                    self._preview_phase = "historical"
            rescan = (
                not self._closing
                and self._backend is not None
                and (self._scan_thread is None or not self._scan_thread.is_alive())
                and self._clock() - self._scan_completed_at >= 1.0
                and not self._busy_locked()
            )
        if cancel_job is not None:
            cancel_job.cancel()
        if stop_runner:
            self._runner.stop()
        if rescan:
            self._start_scan()

    def _apply_scan_locked(self, scan: _ScanResult) -> bool:
        self._scan_completed_at = self._clock()
        if scan.error:
            self._clear_target_locked()
            self._clear_preview_locked()
            self._acknowledged = False
            self._binding_phase = "error"
            self._binding_message = "Target discovery failed."
            self._readiness_phase = "unavailable"
            if self._mode == "live" and self._start_cancel is not None:
                self._start_cancel.set()
            return self._mode == "live"
        old = self._targets.get(self._selected_id or "")
        ordered = sorted(set(scan.targets), key=lambda target: (target.pid, target.token, target.executable, target.identifier))
        old_ids = {target: target_id for target_id, target in self._targets.items()}
        self._targets = {old_ids.get(target) or secrets.token_hex(12): target for target in ordered}
        matching = next((target_id for target_id, target in self._targets.items() if target == old), None)
        self._selected_id = matching
        if len(self._targets) == 1:
            self._selected_id = next(iter(self._targets))
            self._binding_phase = "bound"
            self._binding_message = "One verified Roblox player found."
        elif not self._targets:
            self._binding_phase = "missing"
            self._binding_message = "No verified Roblox player found."
        elif matching is None or old != self._explicit_target:
            self._selected_id = None
            self._binding_phase = "multiple"
            self._binding_message = "Choose a verified Roblox player."
        else:
            self._binding_phase = "bound"
            self._binding_message = "Selected Roblox player remains available."
        changed = old != self._targets.get(self._selected_id or "")
        if changed:
            self._acknowledged = False
            if self._mode == "live" and self._start_cancel is not None:
                self._start_cancel.set()
            if old is not None or self._preview_frame is not None or self._area is not None:
                self._clear_preview_locked()
        if scan.readiness:
            self._acknowledged = False
            self._readiness_phase = "blocked"
            self._readiness_issues = []
            if any(issue in scan.readiness for issue in (
                "Accessibility permission is required for native input control.",
                "Accessibility permission is required to post native input events.",
            )):
                self._readiness_issues.append("Enable Accessibility for this app in macOS Privacy & Security.")
            if "Input Monitoring permission is required to read Escape emergency stop." in scan.readiness:
                self._readiness_issues.append("Enable Input Monitoring for this app, then reopen it.")
            if not self._readiness_issues:
                self._readiness_issues = ["Native permissions or input monitoring need attention."]
        else:
            self._readiness_phase = "ready"
            self._readiness_issues = []
        return self._mode == "live" and (changed or bool(scan.readiness))

    def _drain_runner_events_locked(self) -> None:
        events = getattr(self._runner, "events", None)
        if events is None:
            return
        for _ in range(_MAX_EVENT_DRAIN):
            try:
                status = events.get_nowait()
            except queue.Empty:
                return
            state = getattr(status, "state", "error")
            if state in {"countdown", "running"}:
                self._run_phase = state
                self._message = ("Switch to the selected Roblox window now. Escape stops."
                                 if state == "countdown" and self._mode == "live" else
                                 "Dry run countdown. No native input."
                                 if state == "countdown" else "Supervised run is active. Escape stops.")
            elif state in {"stopped", "completed", "error"}:
                self._run_phase = state
                self._acknowledged = False
                self._message = {"stopped": "Run stopped.", "completed": "Run completed.",
                                 "error": "Run stopped with an error."}[state]

    def _complete_job_locked(self, result: JobResult) -> Any | None:
        context = self._job_context
        job = self._detach_job_locked()
        if context is None or context.generation != self._job_generation:
            return job
        if context.operation == "sdk":
            if result.error or not isinstance(result.report, dict) or result.report.get("native_input") is not False:
                self._sdk_phase = "unavailable"
                self._sdk_message = "Optional recognition is unavailable."
            else:
                self._sdk_phase = "available"
                self._sdk_message = "Optional recognition is available for synthetic checks only."
            return job
        if result.error or result.frame is None or context.target != self._targets.get(self._selected_id or ""):
            self._preview_phase = "error"
            self._preview_error = _safe_diagnostic(result.diagnostic)
            self._preview_frame = None
            self._clear_geometry_locked()
            return job
        stage = "preview_geometry"
        try:
            layout = layout_from_capture(result.frame)
            if layout.target != context.target:
                raise ValueError("Target changed.")
            now = self._clock()
            if not math.isfinite(now) or result.frame.captured_at > now:
                raise ValueError("Observation timestamp is invalid.")
            fresh = now - result.frame.captured_at <= 0.5
            if context.area is not None:
                if layout != context.source_layout:
                    raise ValueError("Layout changed.")
                self._tracker.accept(layout, result.frame.pixels, result.frame.captured_at, now)
                self._tracker.calibrate((1280, 720), context.area, now=now)
            elif fresh:
                self._tracker.accept(layout, result.frame.pixels, result.frame.captured_at, now)
            else:
                self._tracker.invalidate()
            self._preview_id += 1
            self._preview_phase = "available" if fresh else "historical"
            self._preview_width, self._preview_height = result.frame.physical_size
            self._preview_region_kind = result.frame.region_kind
            self._preview_verified = result.frame.content_verified
            self._preview_error = None
            self._preview_frame = result.frame
            self._preview_layout = layout
            self._preview_png = None
            stage = "preview_encoding"
            self._encode_preview_async(self._preview_id, result.frame)
        except Exception as error:
            self._preview_phase = "error"
            self._preview_error = _safe_diagnostic(CaptureDiagnostic(
                code="unexpected", stage=stage, error_type=capture_error_type(error),
            ))
            self._preview_frame = None
            self._preview_layout = None
            self._preview_png = None
            self._clear_geometry_locked()
        return job

    def _detach_job_locked(self) -> Any | None:
        job, self._job = self._job, None
        self._job_context = None
        return job

    def _clear_target_locked(self) -> None:
        self._targets = {}
        self._selected_id = None
        self._explicit_target = None

    def _busy_locked(self) -> bool:
        return self._starting or bool(getattr(self._runner, "running", False)) or self._job is not None

    def _require_reference_mutation_locked(self) -> None:
        if self._game_id != "adopt" or self._busy_locked() or bool(getattr(self._runner, "cleanup_failed", False)):
            raise RuntimeError("Reference editing is unavailable while input or cleanup is active.")

    def _session_phase(self, cleanup_failed: bool, input_locked: bool) -> str:
        if cleanup_failed:
            return "cleanup_blocked"
        if self._starting:
            return "countdown"
        if input_locked and bool(getattr(self._runner, "running", False)):
            return self._run_phase if self._run_phase in {"countdown", "stopping"} else "running"
        return self._run_phase if self._run_phase in {"stopped", "completed", "error"} else "idle"

    def _can_start(self, cleanup_failed: bool, input_locked: bool) -> bool:
        if self._closing or cleanup_failed or input_locked or self._starting or self._game_id != "adopt" or self._workflow is None:
            return False
        if self._mode == "dry":
            return True
        return bool(self._selected_id and self._acknowledged and self._readiness_phase == "ready")

    def _area_payload(self) -> dict[str, int] | None:
        if self._area is None:
            return None
        return {"x": int(self._area.x), "y": int(self._area.y),
                "width": int(self._area.width), "height": int(self._area.height)}

    def _geometry_phase(self) -> str:
        if self._tracker.calibration is not None:
            return "matched"
        if self._area is not None:
            return "historical"
        return "none"

    def _encode_preview_async(self, preview_id: int, frame: CapturedWindow) -> None:
        def encode() -> None:
            try:
                value = _png_data_url(frame)
            except Exception as error:
                value = CaptureDiagnostic(code="conversion", stage="preview_encoding",
                                          error_type=capture_error_type(error))
            with self._lock:
                if self._closing or preview_id != self._preview_id:
                    return
                try:
                    self._png_queue.get_nowait()
                except queue.Empty:
                    pass
                self._png_queue.put_nowait((preview_id, value))
        threading.Thread(target=encode, daemon=True, name="preview-png").start()

    def _drain_png_locked(self) -> None:
        while True:
            try:
                preview_id, value = self._png_queue.get_nowait()
            except queue.Empty:
                return
            if preview_id != self._preview_id:
                continue
            if isinstance(value, CaptureDiagnostic):
                self._preview_phase = "error"
                self._preview_error = _safe_diagnostic(value)
                self._preview_frame = None
                self._preview_layout = None
                self._preview_png = None
                self._clear_geometry_locked()
            else:
                self._preview_png = value


def _png_data_url(frame: CapturedWindow) -> str:
    """Encode a bounded BGR8 frame to PNG without third-party image libraries."""
    source_width, source_height = frame.physical_size
    scale = max(1, math.ceil(source_width / _MAX_PNG_WIDTH), math.ceil(source_height / _MAX_PNG_HEIGHT))
    width, height = max(1, source_width // scale), max(1, source_height // scale)
    raw = bytearray()
    pixels = frame.pixels
    for y in range(height):
        raw.append(0)
        source_y = min(source_height - 1, y * scale)
        for x in range(width):
            source_x = min(source_width - 1, x * scale)
            offset = (source_y * source_width + source_x) * 3
            raw.extend((pixels[offset + 2], pixels[offset + 1], pixels[offset]))
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    encoded = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    encoded += chunk(b"IDAT", zlib.compress(bytes(raw), level=6)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(encoded).decode("ascii")
