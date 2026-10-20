"""Daemon-backed, local replay-store facade for controller threads.

The public methods only enqueue bounded work or return cached metadata.  Image
encoding and every disk operation remain on one daemon worker. The worker
restores settings before history reads and persists settings only after an
explicit controller command succeeds.
"""

from __future__ import annotations

import base64
from dataclasses import asdict, dataclass
import queue
import re
import threading
from pathlib import Path
from typing import Any, Callable

from afk_grinder.recognition.observation import Observation
from afk_grinder.replay import ReplayFrame, ReplaySettings, ReplayStats, ReplayStore


_COMMAND_CAPACITY = 16
_SESSION_ID = re.compile(r"[0-9a-f]{32}\Z")


@dataclass(frozen=True, slots=True)
class _Command:
    kind: str
    payload: Any


@dataclass(frozen=True, slots=True)
class _FrameTask:
    observation: Observation
    session_id: str
    state: str
    epoch: int


class ReplayService:
    """Async facade with one frame slot and no UI-thread image or disk work."""

    def __init__(self, root: Path, *, store_factory: Callable[..., ReplayStore] = ReplayStore) -> None:
        if not isinstance(root, Path) or not callable(store_factory):
            raise ValueError("Replay service requires a pathlib replay root and store factory.")
        self._store = store_factory(root, ReplaySettings())
        self._commands: queue.PriorityQueue[tuple[int, int, _Command]] = queue.PriorityQueue(_COMMAND_CAPACITY)
        self._frames: queue.Queue[_FrameTask] = queue.Queue(1)
        self._lock = threading.RLock()
        self._closed = False
        self._stop = threading.Event()
        self._done = threading.Event()
        self._serial = 0
        self._epochs: dict[str, int] = {}
        self._deleted_sessions: set[str] = set()
        self._settings = ReplaySettings()
        self._settings_ready = False
        self._selected_session: str | None = None
        self._frame_before = None
        self._session_before = None
        self._has_older_frames = False
        self._has_older_sessions = False
        self._sessions: list[dict[str, object]] = []
        self._frames_for_selected: list[dict[str, object]] = []
        self._stats = ReplayStats(0, 0, 0, False)
        self._frame: dict[str, str] | None = None
        self._phase = "loading"
        self._message = "Replay history loading."
        self._observer_phase = "idle"
        self._worker = threading.Thread(target=self._run, name="afk-replay-store", daemon=True)
        self._worker.start()
        self.command("refresh", None)

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def submit(self, observation: Observation, session_id: str, state: str) -> bool:
        """Queue one frame without encoding, disk access, or blocking the caller."""
        if type(observation) is not Observation or not _valid_id(session_id) or type(state) is not str:
            return False
        with self._lock:
            if (self._closed or not self._settings_ready or not self._settings.enabled
                    or session_id in self._deleted_sessions):
                return False
            epoch = self._epochs.get(session_id, 0)
        try:
            self._frames.put_nowait(_FrameTask(observation, session_id, state, epoch))
        except queue.Full:
            return False
        return True

    def stop_session(self, session_id: str) -> bool:
        """Invalidate queued frames for one session; an in-flight write may finish."""
        if not _valid_id(session_id):
            return False
        with self._lock:
            if self._closed:
                return False
            self._epochs[session_id] = self._epochs.get(session_id, 0) + 1
        return True

    def command(self, kind: Any, payload: Any) -> bool:
        """Queue one strict controller operation; completion appears through ``poll``."""
        if not self._valid_command(kind, payload):
            return False
        with self._lock:
            if self._closed:
                return False
            self._serial += 1
            serial = self._serial
        priority = 0 if kind == "settings" else 1
        try:
            self._commands.put_nowait((priority, serial, _Command(kind, payload)))
        except queue.Full:
            return False
        return True

    def poll(self) -> dict[str, object]:
        """Return fixed-shape cached controller state without filesystem access."""
        with self._lock:
            observer_messages = {
                "warming": "Preparing local session recognition.",
                "recording": "Recording eligible selected-window frames.",
                "skipping_unknown": "Unclassified screens recorded as opaque privacy frames; no original image saved.",
                "blocked": "Recording stopped: protected screen detected.",
                "error": "Recording paused: check capture, calibration and local recognition setup.",
                "stopped": "Recording session ended. Start a fresh supervised session to record again.",
            }
            observer = self._observer_phase
            paused = observer in {"skipping_unknown", "blocked", "error"}
            return {
                "phase": "paused" if paused and self._phase != "error" else self._phase,
                "message": observer_messages.get(observer, self._message) if self._phase != "error" else self._message,
                "settings": asdict(self._settings),
                "sessions": [dict(session) for session in self._sessions],
                "selected_session": self._selected_session,
                "has_older_frames": self._has_older_frames,
                "has_older_sessions": self._has_older_sessions,
                "frames": [dict(frame) for frame in self._frames_for_selected],
                "stats": asdict(self._stats),
                "frame": dict(self._frame) if self._frame is not None else None,
            }

    def observer_status(self, phase: str) -> None:
        if phase not in {"warming", "recording", "skipping_unknown", "blocked", "error", "stopped"}:
            raise ValueError("Replay observer phase is invalid.")
        with self._lock:
            if not self._closed:
                self._observer_phase = phase

    def close(self) -> None:
        """Cancel queued work and return without waiting for daemon worker shutdown."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._phase = "closed"
            self._message = "Replay service closed."
        self._stop.set()
        _drain(self._frames)
        _drain(self._commands)

    @staticmethod
    def _valid_command(kind: Any, payload: Any) -> bool:
        if type(kind) is not str:
            return False
        if kind == "settings":
            return type(payload) is ReplaySettings
        if kind in {"select", "delete", "older"}:
            return _valid_id(payload)
        if kind == "frame":
            return _valid_id(payload)
        return (kind == "refresh" and payload is None) or (kind == "sessions" and type(payload) is bool)

    def _run(self) -> None:
        try:
            self._restore_settings()
            while not self._stop.is_set():
                command = self._next_command()
                if command is not None:
                    self._handle_command(command)
                    continue
                try:
                    frame = self._frames.get(timeout=0.05)
                except queue.Empty:
                    continue
                self._handle_frame(frame)
        finally:
            self._done.set()

    def _next_command(self) -> _Command | None:
        try:
            return self._commands.get_nowait()[2]
        except queue.Empty:
            return None

    def _handle_command(self, command: _Command) -> None:
        try:
            if command.kind == "settings":
                settings = self._store.update_settings(command.payload)
                self._drain_frames_after_settings(settings)
                with self._lock:
                    self._settings = settings
                    self._settings_ready = True
                    self._frame = None
                self._refresh("Replay settings updated.")
            elif not self._settings_available():
                self._safe_error()
            elif command.kind == "select":
                self._select(command.payload)
            elif command.kind == "older":
                if command.payload != self._selected_session or not self._frames_for_selected:
                    return
                first = self._frames_for_selected[0]
                self._frame_before = (first["recorded_at"], first["frame_id"])
                self._select(command.payload, older=True)
            elif command.kind == "sessions":
                if command.payload and self._sessions:
                    last = self._sessions[-1]
                    self._session_before = (last["started_at"], last["id"])
                else:
                    self._session_before = None
                self._refresh("Replay session page ready.")
            elif command.kind == "frame":
                self._read_frame(command.payload)
            elif command.kind == "delete":
                with self._lock:
                    self._deleted_sessions.add(command.payload)
                self._store.delete_session(command.payload)
                with self._lock:
                    if self._selected_session == command.payload:
                        self._selected_session = None
                        self._frames_for_selected = []
                    self._frame = None
                self._refresh("Replay session deleted.")
            else:
                if not self._settings_available():
                    self._safe_error()
                    return
                self._refresh("Replay history ready.")
        except Exception:
            self._safe_error(invalidate_settings=command.kind == "settings")

    def _handle_frame(self, task: _FrameTask) -> None:
        with self._lock:
            valid = (
                not self._closed
                and self._settings_ready
                and self._settings.enabled
                and task.session_id not in self._deleted_sessions
                and (task.epoch == self._epochs.get(task.session_id, 0)
                     or task.state in {"redacted_login", "redacted_unknown", "redacted_restricted",
                                       "redacted_purchase", "redacted_trade"})
            )
        if not valid:
            return
        try:
            self._store.record(task.observation, task.session_id, task.state)
            self._refresh("Replay history ready.")
        except Exception:
            self._safe_error()

    def _drain_frames_after_settings(self, settings: ReplaySettings) -> None:
        _drain(self._frames)
        if not settings.enabled:
            with self._lock:
                self._epochs = {session_id: epoch + 1 for session_id, epoch in self._epochs.items()}

    def _select(self, session_id: str, *, older=False) -> None:
        if not older:
            self._frame_before = None
        frames = (self._store.list_frames(session_id, before=self._frame_before)
                  if self._frame_before is not None else self._store.list_frames(session_id))
        with self._lock:
            if not frames and older:
                self._has_older_frames = False
                return
            self._selected_session = session_id
            self._frames_for_selected = [_frame_payload(frame) for frame in frames]
            self._has_older_frames = len(frames) == 4096
            self._frame = None
            self._phase = "ready"
            self._message = "Replay session selected." if frames else "Replay session is unavailable."

    def _read_frame(self, frame_id: str) -> None:
        mime_type, payload = self._store.get_frame(frame_id)
        data_url = f"data:{mime_type};base64,{base64.b64encode(payload).decode('ascii')}"
        with self._lock:
            self._frame = {"frame_id": frame_id, "data_url": data_url}
            self._phase = "ready"
            self._message = "Replay frame ready."

    def _refresh(self, message: str) -> None:
        if not self._settings_available():
            self._safe_error()
            return
        summaries = getattr(self._store, "session_summaries", None)
        frames = (self._store.list_frames(self._selected_session, before=self._frame_before) if self._selected_session else ()) if callable(summaries) else self._store.list_frames()
        stats = self._store.stats()
        sessions = list(summaries(before=self._session_before)) if callable(summaries) else _session_payloads(frames)
        with self._lock:
            selected = self._selected_session
            self._sessions = sessions
            self._has_older_sessions = len(sessions) == 100
            self._has_older_frames = len(frames) == 4096
            self._frames_for_selected = [
                _frame_payload(frame) for frame in frames if frame.session_id == selected
            ] if selected is not None else []
            self._stats = stats
            self._phase = "ready"
            self._message = message

    def _safe_error(self, *, invalidate_settings: bool = False) -> None:
        with self._lock:
            if invalidate_settings:
                self._settings_ready = False
            self._frame = None
            self._phase = "error"
            self._message = "Replay operation failed."

    def _restore_settings(self) -> None:
        restore = getattr(self._store, "restore_settings", None)
        if not callable(restore):
            with self._lock:
                self._settings_ready = True
            return
        try:
            settings = restore()
        except Exception:
            self._safe_error(invalidate_settings=True)
            return
        if type(settings) is not ReplaySettings:
            self._safe_error(invalidate_settings=True)
            return
        with self._lock:
            self._settings = settings
            self._settings_ready = True

    def _settings_available(self) -> bool:
        with self._lock:
            return not self._closed and self._settings_ready


def _valid_id(value: Any) -> bool:
    return type(value) is str and _SESSION_ID.fullmatch(value) is not None


def _drain(items: queue.Queue[Any] | queue.PriorityQueue[Any]) -> None:
    while True:
        try:
            items.get_nowait()
        except queue.Empty:
            return


def _frame_payload(frame: ReplayFrame) -> dict[str, object]:
    return asdict(frame)


def _session_payloads(frames: tuple[ReplayFrame, ...]) -> list[dict[str, object]]:
    grouped: dict[str, list[ReplayFrame]] = {}
    for frame in frames:
        grouped.setdefault(frame.session_id, []).append(frame)
    return [
        {"id": session_id, "started_at": min(frame.recorded_at for frame in entries), "frame_count": len(entries)}
        for session_id, entries in sorted(grouped.items(), key=lambda item: (min(frame.recorded_at for frame in item[1]), item[0]))
    ]
