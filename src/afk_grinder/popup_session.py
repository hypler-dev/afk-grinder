"""Bounded local recognition and approved popup response coordination."""

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

    def close(self):
        if self._capture:
            self._capture.cancel()
        if self._recognition:
            self._recognition.close()
        self._capture = self._recognition = None

    def _warm(self, guard, wait):
        self.report("checking", "Warming local recognition; no input sent.")
        self._recognition = self.recognition_factory(self.models(), LABELS)
        self._recognition.start()
        deadline = self.clock() + 15
        while not self._recognition.ready:
            guard()
            result = self._recognition.poll()
            if result is not None or self.clock() >= deadline:
                raise RuntimeError("Local popup recognition is unavailable.")
            wait(.02)

    def _observe(self, guard, wait) -> tuple[Observation, PopupEvidence]:
        guard()
        self._capture = self.capture_factory("capture", self.calibration.source_layout.target,
                                             timeout=8)
        try:
            while True:
                guard()
                result = self._capture.poll()
                if result is not None:
                    break
                wait(.02)
            if result.error or result.frame is None:
                raise RuntimeError("Selected-window capture failed; no popup action authorized.")
            self.sequence += 1
            raw = Observation(layout_from_capture(result.frame), result.frame.captured_at,
                              1, self.sequence, result.frame.pixels)
            frame = self.calibration.crop(raw)
            if not 0 <= self.clock() - frame.captured_at <= .5:
                raise RuntimeError("Capture is too old for popup recognition.")
        finally:
            self._capture.cancel()
            self._capture = None
        self._recognition.submit(*frame.layout.physical_size, frame.pixels, timeout=2)
        while True:
            guard()
            result = self._recognition.poll()
            if result is not None:
                break
            wait(.02)
        if result.error:
            raise RuntimeError("Local popup recognition failed.")
        if not 0 <= self.clock() - frame.captured_at <= .5:
            raise RuntimeError("Recognition evidence expired; no input authorized.")
        evidence = inspect(frame, result.hits, now=self.clock())
        self.report(evidence.state, evidence.reason)
        if evidence.state in {"bank_reward", "disconnected"}:
            self.record(frame, evidence.state)
        elif evidence.state == "protected":
            self.record(frame, "redacted_" + evidence.privacy)
        else:
            self.record(frame, "redacted_unknown")
        return frame, evidence

    def check(self, guard, wait) -> None:
        """Read-only, including when a known popup is found."""
        try:
            self._warm(guard, wait)
            stability = Stability()
            for _ in range(2):
                _, evidence = self._observe(guard, wait)
                if evidence.button is None:
                    return
                if stability.accept(evidence):
                    self.report(evidence.state, "Stable approved popup found; supervised response available.")
                    return
                wait(.05)
            self.report("unknown", "Popup did not stabilize; no input authorized.")
        finally:
            self.close()

    def resolve(self, capability: GuardedInput, *, allow_reconnect: bool) -> None:
        try:
            self._warm(capability.guard, capability.wait)
            stability = Stability()
            last = None
            for _ in range(2):
                frame, evidence = self._observe(capability.guard, capability.wait)
                if evidence.button is None:
                    return
                if evidence.state == "disconnected" and not allow_reconnect:
                    self.report("blocked", "Enable known-dialog reconnect recovery before this response.")
                    return
                if stability.accept(evidence):
                    last = evidence
                    break
                capability.wait(.05)
            if last is None:
                self.report("unknown", "Popup did not stabilize; no input authorized.")
                return
            calibration = Calibration.create(frame, frame.layout.physical_size)
            point = calibration.pixel_to_native(*last.point)

            def authorize():
                self.geometry_check(self.calibration.source_layout)
                now = self.clock()
                if not 0 <= now - last.captured_at <= .5 or last.layout != frame.layout:
                    raise RuntimeError("Popup evidence expired before input; no click authorized.")

            # One click maximum. A failed response never retries stale coordinates.
            capability.click(point, authorize)
            self.report("verifying", "Response sent; checking fresh frames for disappearance.")
            capability.wait(.4)
            absent = 0
            for _ in range(3):
                _, after = self._observe(capability.guard, capability.wait)
                if after.state == "protected":
                    return
                if after.state == last.state or after.button is not None:
                    self.report("blocked", "Popup remains or changed; handle it manually before another response.")
                    return
                absent += 1
                if absent == 2:
                    self.report("reconnect_requested" if last.state == "disconnected" else "popup_dismissed",
                                "Previous dialog is no longer recognized. New screen needs fresh checks; input stays stopped.")
                    return
                capability.wait(.2)
        finally:
            self.close()
