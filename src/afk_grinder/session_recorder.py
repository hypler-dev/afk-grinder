"""Bounded replay observer for an explicitly started live session.

This worker never sends input. Stop/focus/Escape cancel observation, and all
encoding/storage stays in the separate bounded replay service.
"""

import threading
import time
import uuid

from .popup_session import PopupSession
from .session import BoundedSession


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
        operation = budget = None
        target = self._calibration.source_layout.target
        ending = "stopped"
        enforce_focus = False

        def guard():
            if self._cancel.is_set() or not self._active():
                raise RuntimeError("Replay observation stopped.")
            if enforce_focus and (self._backend.foreground() != target
                                  or self._backend.escape_pressed() or self._backend.readiness()):
                raise RuntimeError("Replay observation stopped.")

        try:
            budget = BoundedSession(guard, self._cancel.wait, clock=self._clock)
            # Match the live runner's focus countdown without capturing another
            # app. The countdown consumes the same thirty-second outer budget.
            phase = budget.phase("countdown", 5)
            phase.wait(3)
            enforce_focus = True
            phase.guard()
            operation = self._operation_factory(self._calibration, report=lambda *_: None,
                                                clock=self._clock)
            phase.guard()
            phase = budget.phase("warmup", 15)
            self._service.observer_status("warming")
            phase.guard()
            # Pass stable outer callbacks. Passing a phase callback here would
            # leave the nested operation bound to a revoked warmup phase.
            operation._warm(budget.guard, budget.wait)
            phase.guard()
            while True:
                phase = budget.phase("observation", 11)
                phase.guard()
                frame, evidence = operation._observe(budget.guard, budget.wait)
                phase.guard()
                if evidence.state == "protected":
                    privacy = getattr(evidence, "privacy", "restricted")
                    self._service.submit(frame, session_id, "redacted_" + privacy)
                    ending = "blocked"
                    self._cancel.set()
                    return
                if evidence.state in {"bank_reward", "disconnected"}:
                    self._service.submit(frame, session_id, evidence.state)
                    phase.guard()
                    self._service.observer_status("recording")
                elif evidence.state == "unknown":
                    self._service.submit(frame, session_id, "redacted_unknown")
                    phase.guard()
                    self._service.observer_status("skipping_unknown")
                phase.guard()
                settings = self._service.poll()
                phase.guard()
                phase = budget.phase("interval", 30)
                phase.wait(settings["settings"]["interval_seconds"])
        except Exception:
            # Failed or late observations cannot become gameplay labels.
            if not self._cancel.is_set() and self._active():
                ending = "error"
                self._cancel.set()
        finally:
            if budget is not None:
                budget.close()
            try:
                if operation is not None:
                    operation.close()
            except Exception:
                ending = "error"
                self._cancel.set()
            finally:
                try:
                    self._service.stop_session(session_id)
                finally:
                    self._service.observer_status(ending)
