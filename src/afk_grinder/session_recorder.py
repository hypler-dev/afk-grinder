"""Bounded replay observer for an explicitly started live session.

This worker never sends input. Stop/focus/Escape cancel observation, and all
encoding/storage stays in the separate bounded replay service.
"""

import threading
import time
import uuid

from .popup_session import PopupSession


class SessionRecorder:
    def __init__(self, *, backend, calibration, service, active, cancel,
                 operation_factory=PopupSession, clock=time.monotonic):
        self._backend, self._calibration, self._service = backend, calibration, service
        self._active, self._cancel, self._clock = active, cancel, clock
        self._operation_factory = operation_factory
        self._thread = None

    def start(self):
        if self._thread is not None:
            raise RuntimeError("Replay observer already started.")
        self._thread = threading.Thread(target=self._run, daemon=True, name="session-replay-observer")
        self._thread.start()

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def _run(self):
        session_id = uuid.uuid4().hex
        deadline = self._clock() + 30
        operation = self._operation_factory(self._calibration, report=lambda *_: None)
        target = self._calibration.source_layout.target
        ending = "stopped"

        def guard():
            if (self._cancel.is_set() or not self._active() or self._clock() >= deadline
                    or self._backend.foreground() != target or self._backend.escape_pressed()
                    or self._backend.readiness()):
                raise RuntimeError("Replay observation stopped.")
        def wait(seconds):
            until = self._clock() + seconds
            while self._clock() < until:
                guard()
                self._cancel.wait(min(.02, max(0, until - self._clock())))
            guard()
        try:
            # The live runner owns its three-second focus countdown. Wait for
            # that countdown here too; do not record another foreground app.
            self._cancel.wait(3)
            guard()
            self._service.observer_status("warming")
            operation._warm(guard, wait)
            while True:
                guard()
                frame, evidence = operation._observe(guard, wait)
                guard()
                if evidence.state == "protected":
                    privacy = getattr(evidence, "privacy", "restricted")
                    self._service.submit(frame, session_id, "redacted_" + privacy)
                    self._cancel.set()
                    ending = "blocked"
                    return
                if evidence.state in {"bank_reward", "disconnected"}:
                    self._service.submit(frame, session_id, evidence.state)
                    self._service.observer_status("recording")
                elif evidence.state == "unknown":
                    self._service.submit(frame, session_id, "redacted_unknown")
                    self._service.observer_status("skipping_unknown")
                wait(max(1, self._service.poll()["settings"]["interval_seconds"]))
        except Exception:
            # The observer cannot turn a failed capture into a gameplay label.
            if not self._cancel.is_set() and self._active():
                ending = "error"
                self._cancel.set()
        finally:
            operation.close()
            self._service.stop_session(session_id)
            self._service.observer_status(ending)
