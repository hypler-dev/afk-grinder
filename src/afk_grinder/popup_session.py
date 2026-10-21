"""Bounded local recognition and approved popup response coordination."""

import threading
import time
from typing import Callable

from .capture.service import BackgroundJob
from .engine import GuardedInput
from .recognition.adopt_me import LABELS, PopupEvidence, Stability, inspect
from .recognition.content_calibration import ContentCalibration
from .recognition.frame_geometry import layout_from_capture
from .recognition.native_geometry import require_unchanged
from .recognition.observation import Calibration, Observation
from .recognition.ocr_models import model_directory, validate_models
from .recognition.service import RecognitionService
from .session import BoundedSession, SessionError


class PopupSession:
    """One supervised operation; old movement queues are never resumed."""

    def __init__(self, calibration: ContentCalibration, *,
                 report: Callable[[str, str], None],
                 record: Callable[[Observation, str], None] = lambda *_: None,
                 capture_factory=BackgroundJob, recognition_factory=RecognitionService,
                 clock=time.monotonic, geometry_check=require_unchanged,
                 models: Callable = lambda: validate_models(model_directory())):
        self.calibration = calibration
        self.report, self.record = report, record
        self.capture_factory, self.recognition_factory = capture_factory, recognition_factory
        self.clock, self.geometry_check, self.models = clock, geometry_check, models
        self.sequence = 0
        self._recognition = None
        self._capture = None
        self._session = None
        self._closed = False
        self._started = False
        self._lifecycle_lock = threading.RLock()

    def close(self):
        """Irrevocably stop this operation and detach both disposable workers."""
        with self._lifecycle_lock:
            self._closed = True
            if self._session is not None:
                self._session.close()
            capture, recognition = self._capture, self._recognition
            self._capture = self._recognition = None
        for resource, method in ((capture, "cancel"), (recognition, "close")):
            if resource is not None:
                try:
                    getattr(resource, method)()
                except Exception:
                    pass

    def _begin(self):
        with self._lifecycle_lock:
            if self._closed or self._started:
                raise SessionError("closed")
            self._started = True

    def _budget(self, guard, wait):
        with self._lifecycle_lock:
            if self._closed:
                raise SessionError("closed")
            if self._session is None:
                def guarded():
                    with self._lifecycle_lock:
                        if self._closed:
                            raise SessionError("closed")
                    guard()
                self._session = BoundedSession(guarded, wait, clock=self.clock)
            return self._session

    def _attach(self, name, resource, method, phase):
        with self._lifecycle_lock:
            accepted = not self._closed
            if accepted:
                setattr(self, name, resource)
        if not accepted:
            try:
                getattr(resource, method)()
            finally:
                phase.guard()
        phase.guard()

    def _release_capture(self, capture):
        with self._lifecycle_lock:
            owned = self._capture is capture
            if owned:
                self._capture = None
        if owned:
            capture.cancel()

    def _report(self, state, message):
        self._session.guard()
        self.report(state, message)
        self._session.guard()

    def _warm(self, guard, wait):
        budget = self._budget(guard, wait)
        phase = budget.phase("warmup", 15)
        phase.guard()
        self._report("checking", "Warming local recognition; no input sent.")
        models = self.models()
        phase.guard()
        recognition = self.recognition_factory(models, LABELS)
        self._attach("_recognition", recognition, "close", phase)
        # Admission and close are serialized. RecognitionService owns the
        # subprocess lifecycle; no native initialization runs on this thread.
        with self._lifecycle_lock:
            phase.guard()
            recognition.start()
        phase.guard()
        while True:
            phase.guard()
            ready = recognition.ready
            phase.guard()
            if ready:
                return
            result = recognition.poll()
            phase.guard()
            if result is not None:
                raise RuntimeError("Local popup recognition is unavailable.")
            phase.wait(.02)

    def _fresh(self, frame):
        self._session.guard()
        if not 0 <= self.clock() - frame.captured_at <= .5:
            raise RuntimeError("Recognition evidence expired; no input authorized.")

    def _observe(self, guard, wait) -> tuple[Observation, PopupEvidence]:
        budget = self._budget(guard, wait)
        phase = budget.phase("capture", 8)
        phase.guard()
        recognition = self._recognition
        if recognition is None:
            raise RuntimeError("Local popup recognition is unavailable.")
        capture = self.capture_factory("capture", self.calibration.source_layout.target, timeout=8)
        try:
            self._attach("_capture", capture, "cancel", phase)
            while True:
                phase.guard()
                result = capture.poll()
                phase.guard()
                if result is not None:
                    break
                phase.wait(.02)
            if result.error or result.frame is None:
                raise RuntimeError("Selected-window capture failed; no popup action authorized.")
            self.sequence += 1
            raw = Observation(layout_from_capture(result.frame), result.frame.captured_at,
                              1, self.sequence, result.frame.pixels)
            frame = self.calibration.crop(raw)
            self._fresh(frame)
        finally:
            self._release_capture(capture)
        phase = budget.phase("recognition", 2)
        self._fresh(frame)
        timeout = min(2, .5 - (self.clock() - frame.captured_at))
        if timeout <= 0:
            raise RuntimeError("Recognition evidence expired; no input authorized.")
        with self._lifecycle_lock:
            phase.guard()
            recognition.submit(*frame.layout.physical_size, frame.pixels, timeout=timeout)
        while True:
            self._fresh(frame)
            result = recognition.poll()
            self._fresh(frame)
            if result is not None:
                break
            phase.wait(.02)
        if result.error:
            raise RuntimeError("Local popup recognition failed.")
        evidence = inspect(frame, result.hits, now=self.clock())
        self._fresh(frame)
        self._report(evidence.state, evidence.reason)
        self._fresh(frame)
        if evidence.state in {"bank_reward", "disconnected"}:
            self.record(frame, evidence.state)
        elif evidence.state == "protected":
            self.record(frame, "redacted_" + evidence.privacy)
        else:
            self.record(frame, "redacted_unknown")
        self._fresh(frame)
        # Observation has finished. A recorder may wait between frames; that
        # idle time consumes the outer budget rather than the completed match.
        budget.phase("idle", 30).guard()
        return frame, evidence

    def _pause(self, seconds):
        phase = self._session.phase("settle", 1)
        phase.wait(seconds)

    def check(self, guard, wait) -> None:
        """Read-only, including when a known popup is found."""
        self._begin()
        try:
            self._warm(guard, wait)
            stability = Stability()
            for _ in range(2):
                _, evidence = self._observe(guard, wait)
                if evidence.button is None:
                    return
                if stability.accept(evidence):
                    self._report(evidence.state, "Stable approved popup found; supervised response available.")
                    return
                self._pause(.05)
            self._report("unknown", "Popup did not stabilize; no input authorized.")
        finally:
            self.close()

    def resolve(self, capability: GuardedInput, *, allow_reconnect: bool) -> None:
        self._begin()
        try:
            self._warm(capability.guard, capability.wait)
            stability = Stability()
            last = None
            for _ in range(2):
                frame, evidence = self._observe(capability.guard, capability.wait)
                if evidence.button is None:
                    return
                if evidence.state == "disconnected" and not allow_reconnect:
                    self._report("blocked", "Enable known-dialog reconnect recovery before this response.")
                    return
                if stability.accept(evidence):
                    last = evidence
                    break
                self._pause(.05)
            if last is None:
                self._report("unknown", "Popup did not stabilize; no input authorized.")
                return
            calibration = Calibration.create(frame, frame.layout.physical_size)
            point = calibration.pixel_to_native(*last.point)
            phase = self._session.phase("response", 1)
            phase.guard()

            def authorize():
                phase.guard()
                self.geometry_check(self.calibration.source_layout)
                phase.guard()
                now = self.clock()
                if not 0 <= now - last.captured_at <= .5 or last.layout != frame.layout:
                    raise RuntimeError("Popup evidence expired before input; no click authorized.")

            # One click maximum. A failed response never retries stale coordinates.
            capability.click(point, authorize)
            phase.guard()
            self._report("verifying", "Response sent; checking fresh frames for disappearance.")
            self._pause(.4)
            absent = 0
            for _ in range(3):
                _, after = self._observe(capability.guard, capability.wait)
                if after.state == "protected":
                    return
                if after.state == last.state or after.button is not None:
                    self._report("blocked", "Popup remains or changed; handle it manually before another response.")
                    return
                absent += 1
                if absent == 2:
                    self._report("reconnect_requested" if last.state == "disconnected" else "popup_dismissed",
                                 "Previous dialog is no longer recognized. New screen needs fresh checks; input stays stopped.")
                    return
                self._pause(.2)
        finally:
            self.close()
