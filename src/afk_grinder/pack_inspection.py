"""Read-only bounded inspection of one calibrated resource-pack frame stream."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable

from afk_grinder.capture import CapturedWindow
from afk_grinder.capture.service import BackgroundJob
from afk_grinder.recognition.content_calibration import ContentCalibration
from afk_grinder.recognition.frame_geometry import layout_from_capture
from afk_grinder.recognition.observation import Observation
from afk_grinder.recognition.pack_results import AnchorHit, PackResultError, validate_anchor_hits
from afk_grinder.recognition.pack_service import PackRecognitionService
from afk_grinder.recognition.packs import ResourcePack
from afk_grinder.recognition.state import StateInspection, StateInspector, classify_scores


_ERROR_CODES = frozenset({
    "capture_failed", "layout_changed", "stale", "recognition_failed", "timeout", "invalid_result",
})
_FRESHNESS_SECONDS = 0.5
_WARMUP_SECONDS = 15.0
_SESSION_SECONDS = 30.0
_CAPTURE_SECONDS = 8.0
_MATCH_SECONDS = 2.0
_MAX_FRAMES = 5


class PackInspectionError(RuntimeError):
    """A fixed, non-sensitive inspection failure code."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_CODES:
            raise ValueError("Unknown inspection error code.")
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class PackInspectionReport:
    """Terminal local evidence from the last accepted raw capture only."""

    state: StateInspection
    anchors: tuple[AnchorHit, ...]
    frame: CapturedWindow
    required_frames: int
    observed_frames: int


class PackInspectionSession:
    """One disposable, input-free inspection session for an immutable pack."""

    def __init__(
        self,
        pack: ResourcePack,
        calibration: ContentCalibration,
        *,
        capture_factory=BackgroundJob,
        recognition_factory=PackRecognitionService,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(pack) is not ResourcePack:
            raise TypeError("Pack inspection requires a validated ResourcePack.")
        if type(calibration) is not ContentCalibration:
            raise TypeError("Pack inspection requires ContentCalibration.")
        self.pack = pack
        self.calibration = calibration
        self.capture_factory = capture_factory
        self.recognition_factory = recognition_factory
        self.clock = clock
        self._capture = None
        self._recognition = None
        self._closed = False
        self._started = False
        self._sequence = 0

    def close(self) -> None:
        """Cancel outstanding observation work. Safe to call repeatedly."""
        capture, recognition = self._capture, self._recognition
        self._capture = None
        self._recognition = None
        self._closed = True
        if capture is not None:
            try:
                capture.cancel()
            except Exception:
                pass
        if recognition is not None:
            try:
                recognition.close()
            except Exception:
                pass

    def run(self, guard: Callable[[], None], wait: Callable[[float], None], *,
            progress: Callable[[str], None] | None = None) -> PackInspectionReport:
        """Return one terminal state from fresh, distinct calibrated captures."""
        if self._closed or self._started:
            raise PackInspectionError("timeout")
        self._started = True
        deadline = self.clock() + _SESSION_SECONDS
        inspector = StateInspector(self.pack)
        latest_captured_at: float | None = None
        try:
            self._guard(guard, deadline)
            self._progress(progress, "warming")
            self._guard(guard, deadline)
            self._warm(guard, wait, deadline)
            observed = 0
            while observed < _MAX_FRAMES:
                raw = self._capture_frame(guard, wait, deadline)
                now = self._now(deadline)
                self._require_fresh(raw.captured_at, now)
                if latest_captured_at is not None and raw.captured_at <= latest_captured_at:
                    raise PackInspectionError("stale")
                latest_captured_at = raw.captured_at
                self._sequence += 1
                try:
                    raw_observation = Observation(layout_from_capture(raw), raw.captured_at, 1,
                                                  self._sequence, raw.pixels)
                except Exception as error:
                    if isinstance(error, (TypeError, ValueError)):
                        raise PackInspectionError("layout_changed") from None
                    raise PackInspectionError("invalid_result") from None
                if raw_observation.layout != self.calibration.source_layout:
                    raise PackInspectionError("layout_changed")
                try:
                    observation = self.calibration.crop(raw_observation)
                except (TypeError, ValueError):
                    raise PackInspectionError("layout_changed") from None
                self._guard(guard, deadline)
                now = self._now(deadline)
                self._require_fresh(observation.captured_at, now)
                age = now - observation.captured_at
                timeout = min(_MATCH_SECONDS, _FRESHNESS_SECONDS - age)
                if timeout <= 0:
                    raise PackInspectionError("stale")
                matches = self._match(observation, timeout, guard, wait, deadline)
                now = self._now(deadline)
                self._require_fresh(observation.captured_at, now)
                try:
                    anchors = validate_anchor_hits(self.pack, observation.layout.physical_size, matches)
                except (PackResultError, TypeError, ValueError):
                    raise PackInspectionError("invalid_result") from None
                scores = {hit.id: hit.score for hit in anchors}
                try:
                    static = classify_scores(self.pack, scores)
                    state = inspector.inspect(observation, scores, now=now)
                except (TypeError, ValueError):
                    raise PackInspectionError("invalid_result") from None
                observed += 1
                required = self._required_frames(static.state_id)
                report = PackInspectionReport(state, anchors, raw, required, observed)
                if state.reason != "unstable" or observed == _MAX_FRAMES:
                    return report
                self._progress(progress, f"checking {observed}/{_MAX_FRAMES}")
                self._pause(guard, wait, deadline, .05)
            raise PackInspectionError("timeout")
        finally:
            self.close()

    def _warm(self, guard: Callable[[], None], wait: Callable[[float], None], deadline: float) -> None:
        try:
            self._recognition = self.recognition_factory(self.pack, self.calibration.viewport[2:])
            self._recognition.start()
        except Exception:
            raise PackInspectionError("recognition_failed") from None
        warm_deadline = min(deadline, self.clock() + _WARMUP_SECONDS)
        while not self._recognition.ready:
            self._guard(guard, warm_deadline)
            try:
                result = self._recognition.poll()
            except Exception:
                raise PackInspectionError("recognition_failed") from None
            self._guard(guard, warm_deadline)
            if result is not None:
                raise PackInspectionError("recognition_failed")
            self._pause(guard, wait, warm_deadline, .02)

    def _capture_frame(self, guard: Callable[[], None], wait: Callable[[float], None], deadline: float) -> CapturedWindow:
        self._guard(guard, deadline)
        try:
            self._capture = self.capture_factory("capture", self.calibration.source_layout.target,
                                                 timeout=_CAPTURE_SECONDS)
        except Exception:
            raise PackInspectionError("capture_failed") from None
        try:
            while True:
                self._guard(guard, deadline)
                try:
                    result = self._capture.poll()
                except Exception:
                    raise PackInspectionError("capture_failed") from None
                self._guard(guard, deadline)
                if result is not None:
                    break
                self._pause(guard, wait, deadline, .02)
            try:
                failed = getattr(result, "error", "")
                frame = getattr(result, "frame", None)
            except Exception:
                raise PackInspectionError("capture_failed") from None
            if failed or not isinstance(frame, CapturedWindow):
                raise PackInspectionError("capture_failed")
            return frame
        finally:
            capture, self._capture = self._capture, None
            if capture is not None:
                try:
                    capture.cancel()
                except Exception:
                    pass

    def _match(self, observation: Observation, timeout: float, guard: Callable[[], None],
               wait: Callable[[float], None], deadline: float) -> tuple[AnchorHit, ...]:
        try:
            self._recognition.submit(*observation.layout.physical_size, observation.pixels, timeout=timeout)
        except Exception:
            raise PackInspectionError("recognition_failed") from None
        while True:
            self._guard(guard, deadline)
            try:
                result = self._recognition.poll()
            except Exception:
                raise PackInspectionError("recognition_failed") from None
            self._guard(guard, deadline)
            if result is not None:
                break
            self._pause(guard, wait, deadline, .02)
        if getattr(result, "error", ""):
            raise PackInspectionError("recognition_failed")
        hits = getattr(result, "hits", None)
        if type(hits) is not tuple:
            raise PackInspectionError("invalid_result")
        return hits

    def _required_frames(self, state_id: str | None) -> int:
        if state_id is None:
            return 0
        for state in self.pack.states:
            if state.id == state_id:
                return state.stable_frames
        return 0

    def _guard(self, guard: Callable[[], None], deadline: float) -> None:
        if self._closed or self._now(deadline) >= deadline:
            raise PackInspectionError("timeout")
        guard()
        if self._closed or self._now(deadline) >= deadline:
            raise PackInspectionError("timeout")

    def _pause(self, guard: Callable[[], None], wait: Callable[[float], None], deadline: float,
               seconds: float) -> None:
        self._guard(guard, deadline)
        wait(min(seconds, max(0.0, deadline - self.clock())))
        self._guard(guard, deadline)

    def _now(self, deadline: float) -> float:
        now = self.clock()
        if type(now) not in (int, float):
            raise PackInspectionError("timeout")
        if now > deadline:
            raise PackInspectionError("timeout")
        return float(now)

    @staticmethod
    def _require_fresh(captured_at: float, now: float) -> None:
        if captured_at > now or now - captured_at > _FRESHNESS_SECONDS:
            raise PackInspectionError("stale")

    def _progress(self, progress: Callable[[str], None] | None, message: str) -> None:
        if progress is not None and not self._closed:
            progress(message)
