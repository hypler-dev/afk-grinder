"""Pure cooperative deadlines for guarded routine phases.

This module has no input, capture, filesystem, network, or pack authority.
Callers provide their own guard and interruptible wait callbacks.
"""

from __future__ import annotations

import math
import re
import threading
import time
from typing import Callable


_MAX_SECONDS = 30.0
_WAIT_QUANTUM = 0.02
_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._-]{0,63}")
_CODES = frozenset({"closed", "timeout", "clock_invalid", "interrupted", "phase_changed"})


class SessionError(RuntimeError):
    """Safe terminal state for a bounded session."""

    def __init__(self, code: str):
        if code not in _CODES:
            raise ValueError("Unknown session error code.")
        self.code = code
        super().__init__(code)


class Phase:
    """Revocable capability for one active bounded phase."""

    def __init__(self, session: BoundedSession, token: object):
        self._session = session
        self._token = token

    def guard(self) -> None:
        self._session._guard(self._token)

    def wait(self, seconds: float) -> None:
        self._session._wait(seconds, self._token)


class BoundedSession:
    """A 30-second-or-shorter cooperative session with one active phase."""

    def __init__(
        self,
        guard: Callable[[], None],
        wait: Callable[[float], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        session_seconds: float = 30.0,
    ) -> None:
        if not callable(guard) or not callable(wait) or not callable(clock):
            raise TypeError("Session callbacks must be callable.")
        session_seconds = self._validate_seconds(session_seconds, allow_zero=False)
        self._guard_callback = guard
        self._wait_callback = wait
        self._clock = clock
        self._lock = threading.RLock()
        self._terminal: str | None = None
        self._active_token: object | None = None
        self._active_deadline: float | None = None
        self._last_clock: float | None = None
        with self._lock:
            now = self._sample_clock_locked()
            self._deadline = now + session_seconds

    @staticmethod
    def _validate_seconds(seconds: float, *, allow_zero: bool) -> float:
        if type(seconds) not in (int, float):
            raise TypeError("Duration must be a finite number.")
        try:
            value = float(seconds)
        except (OverflowError, ValueError):
            raise ValueError("Duration is outside bounded session limits.") from None
        if not math.isfinite(value) or value > _MAX_SECONDS or value < 0 or (not allow_zero and value == 0):
            raise ValueError("Duration is outside bounded session limits.")
        return value

    @staticmethod
    def _validate_name(name: str) -> None:
        if type(name) is not str:
            raise TypeError("Phase name must be a safe ASCII label.")
        if _LABEL.fullmatch(name) is None:
            raise ValueError("Phase name must be a safe ASCII label.")

    def _terminalize_locked(self, reason: str) -> None:
        if self._terminal is None:
            self._terminal = reason

    def _raise_terminal_locked(self) -> None:
        if self._terminal is not None:
            raise SessionError(self._terminal)

    def _sample_clock_locked(self) -> float:
        try:
            raw_now = self._clock()
        except BaseException:
            self._terminalize_locked("clock_invalid")
            raise SessionError("clock_invalid") from None
        if type(raw_now) not in (int, float):
            self._terminalize_locked("clock_invalid")
            raise SessionError("clock_invalid")
        try:
            now = float(raw_now)
        except (OverflowError, ValueError):
            self._terminalize_locked("clock_invalid")
            raise SessionError("clock_invalid") from None
        if not math.isfinite(now):
            self._terminalize_locked("clock_invalid")
            raise SessionError("clock_invalid")
        if self._last_clock is not None and now < self._last_clock:
            self._terminalize_locked("clock_invalid")
            raise SessionError("clock_invalid")
        self._last_clock = now
        return now

    def _precheck_locked(self, token: object | None) -> float:
        self._raise_terminal_locked()
        now = self._sample_clock_locked()
        if now >= self._deadline:
            self._terminalize_locked("timeout")
            raise SessionError("timeout")
        if token is not None and token is not self._active_token:
            raise SessionError("phase_changed")
        if self._active_deadline is not None and now >= self._active_deadline:
            self._terminalize_locked("timeout")
            raise SessionError("timeout")
        return now

    def _precheck(self, token: object | None) -> float:
        with self._lock:
            return self._precheck_locked(token)

    def _interrupt(self) -> None:
        with self._lock:
            self._terminalize_locked("interrupted")

    def _guard(self, token: object | None) -> float:
        self._precheck(token)
        try:
            self._guard_callback()
        except BaseException:
            self._interrupt()
            raise
        return self._precheck(token)

    def guard(self) -> None:
        """Check session, active phase, and caller-provided cancellation guard."""
        self._guard(None)

    def phase(self, name: str, seconds: float) -> Phase:
        """Start a phase, revoking any prior phase capability."""
        self._validate_name(name)
        seconds = self._validate_seconds(seconds, allow_zero=False)
        with self._lock:
            now = self._precheck_locked(None)
            token = object()
            self._active_token = token
            self._active_deadline = min(self._deadline, now + seconds)
            return Phase(self, token)

    def _wait(self, seconds: float, token: object | None) -> None:
        seconds = self._validate_seconds(seconds, allow_zero=True)
        started = self._guard(token)
        requested_deadline = started + seconds
        if seconds == 0:
            return
        attempts_remaining = math.ceil(seconds / _WAIT_QUANTUM) * 2 + 2
        while True:
            with self._lock:
                now = self._precheck_locked(token)
                if now >= requested_deadline:
                    return
                limits = [requested_deadline, self._deadline]
                if self._active_deadline is not None:
                    limits.append(self._active_deadline)
                duration = min(_WAIT_QUANTUM, min(limits) - now)
                if duration <= 0:
                    # _precheck_locked normally raises first. This handles float edge cases.
                    self._terminalize_locked("timeout")
                    raise SessionError("timeout")
                before_wait = now
            attempts_remaining -= 1
            if attempts_remaining < 0:
                with self._lock:
                    self._terminalize_locked("clock_invalid")
                raise SessionError("clock_invalid")
            try:
                self._wait_callback(duration)
            except BaseException:
                self._interrupt()
                raise
            after_wait = self._guard(token)
            if after_wait <= before_wait:
                with self._lock:
                    self._terminalize_locked("clock_invalid")
                raise SessionError("clock_invalid")
            # The post-callback check above deliberately runs before declaring
            # success: reaching a session or phase deadline is a timeout.
            if after_wait >= requested_deadline:
                return

    def wait(self, seconds: float) -> None:
        """Run the caller wait callback in cancellable 20ms-or-shorter quanta."""
        self._wait(seconds, None)

    def close(self) -> None:
        """Irrevocably close this session; first terminal reason wins."""
        with self._lock:
            self._terminalize_locked("closed")
