"""In-memory, recognition-only TemplateMatch adapter for managed workers."""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import importlib.metadata
import importlib.util
import math
import os
from pathlib import Path
import re
from typing import Any

from .maa_adapter import (
    FRAME_CACHE_LIMIT,
    PINNED_MAA_VERSION,
    SDKError,
    read_only_controller_type,
    wait_for_job,
)

MAX_TEMPLATES = 16
MAX_TEMPLATE_PIXELS = 1_000_000
MAX_FRAME_PIXELS = 16_000_000
MAX_OCR_RESULTS = 512
OPTIONAL_SDK_MESSAGE = "Recognition is optional. Install the locked recognition extra first."


def _integer(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_frame(width: Any, height: Any, pixels: Any) -> None:
    if (not _integer(width) or not _integer(height) or width <= 0 or height <= 0
            or width * height > MAX_FRAME_PIXELS):
        raise ValueError("Recognition frame dimensions are invalid.")
    if not isinstance(pixels, bytes) or len(pixels) != width * height * 3:
        raise ValueError("Recognition frame must be immutable BGR bytes matching its dimensions.")


def _load_pinned_modules() -> tuple[Any, Any, Any, Any, Any, Any]:
    if "MAAFW_BINARY_PATH" in os.environ:
        raise SDKError("Recognition SDK override is disabled.")
    try:
        version = importlib.metadata.version("MaaFw").removeprefix("v")
    except importlib.metadata.PackageNotFoundError as error:
        raise SDKError(OPTIONAL_SDK_MESSAGE) from error
    if version != PINNED_MAA_VERSION:
        raise SDKError("Recognition SDK version is not pinned.")
    if importlib.util.find_spec("maa") is None:
        raise SDKError(OPTIONAL_SDK_MESSAGE)
    try:
        library = importlib.import_module("maa.library").Library
        tasker_type = importlib.import_module("maa.tasker").Tasker
        resource_type = importlib.import_module("maa.resource").Resource
        controller_base = importlib.import_module("maa.controller").CustomController
        definitions = importlib.import_module("maa.define")
        numpy = importlib.import_module("numpy")
        if library.version().removeprefix("v") != PINNED_MAA_VERSION:
            raise SDKError("Recognition native SDK version is not pinned.")
        return tasker_type, resource_type, controller_base, definitions, numpy, importlib.import_module("maa.pipeline")
    except SDKError:
        raise
    except Exception as error:
        raise SDKError("Recognition initialization failed.") from error


def _configure_read_only_tasker(tasker_type: Any, resource_type: Any, controller_base: Any,
                                definitions: Any, numpy: Any) -> tuple[Any, Any]:
    tasker = tasker_type()
    settings = (
        ("set_log_dir", ""),
        ("set_save_draw", False),
        ("set_save_on_error", False),
        ("set_debug_mode", False),
        ("set_stdout_level", definitions.LoggingLevelEnum.Off),
        ("set_reco_image_cache_limit", FRAME_CACHE_LIMIT),
    )
    for name, value in settings:
        if not getattr(tasker_type, name)(value):
            raise SDKError("Recognition SDK refused a required safety setting.")
    resource = resource_type()
    if not resource.set_cpu():
        raise SDKError("Recognition SDK refused CPU-only mode.")
    controller = read_only_controller_type(controller_base)(numpy.zeros((2, 2, 3), dtype=numpy.uint8))
    wait_for_job(controller.post_connection())
    if not tasker.bind(resource, controller):
        raise SDKError("Recognition SDK refused read-only binding.")
    return tasker, resource


@dataclass(frozen=True)
class TemplateSpec:
    """One bounded BGR template and its frame-relative recognition region."""

    template_id: str
    width: int
    height: int
    pixels: bytes
    roi: tuple[int, int, int, int]
    threshold: float

    def __post_init__(self) -> None:
        if not isinstance(self.template_id, str) or not 0 < len(self.template_id) <= 128:
            raise ValueError("Template identifier is invalid.")
        if not _integer(self.width) or not _integer(self.height) or not 8 <= self.width <= 512 or not 8 <= self.height <= 512:
            raise ValueError("Template dimensions must be between 8 and 512 pixels.")
        if not isinstance(self.pixels, bytes) or len(self.pixels) != self.width * self.height * 3:
            raise ValueError("Template pixels must be immutable BGR bytes matching its dimensions.")
        if (not isinstance(self.roi, tuple) or len(self.roi) != 4 or
                not all(_integer(value) for value in self.roi)):
            raise ValueError("Template ROI must be four integer values.")
        x, y, width, height = self.roi
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            raise ValueError("Template ROI must have a non-negative origin and positive dimensions.")
        if not _finite_number(self.threshold) or not 0 <= self.threshold <= 1:
            raise ValueError("Template threshold must be finite and between zero and one.")


@dataclass(frozen=True)
class TemplateHit:
    """Sanitized recognition metadata; never contains source image data."""

    template_id: str
    score: float
    box: tuple[int, int, int, int] | None


class TemplateMatcher:
    """CPU-only, bounded template matching with no action or capture APIs."""

    def __init__(self, specs: tuple[TemplateSpec, ...] | list[TemplateSpec]) -> None:
        if not isinstance(specs, (tuple, list)) or not 0 < len(specs) <= MAX_TEMPLATES:
            raise ValueError("Matcher requires between one and sixteen templates.")
        if not all(isinstance(spec, TemplateSpec) for spec in specs):
            raise ValueError("Matcher templates must be TemplateSpec instances.")
        if len({spec.template_id for spec in specs}) != len(specs):
            raise ValueError("Matcher template identifiers must be unique.")
        if sum(spec.width * spec.height for spec in specs) > MAX_TEMPLATE_PIXELS:
            raise ValueError("Matcher templates exceed the pixel safety limit.")
        self._specs = tuple(specs)
        self._tasker: Any = None
        self._closed = False

    def match(self, width: int, height: int, pixels: bytes, *, timeout: float = 2.0) -> tuple[TemplateHit, ...]:
        """Match one BGR frame. Misses return metadata with ``box=None``."""
        self._validate_frame(width, height, pixels)
        if not _finite_number(timeout) or not 0 < timeout <= 2:
            raise ValueError("Recognition timeout must be finite and at most two seconds.")
        if self._closed:
            raise SDKError("Recognition matcher is closed.")
        self._ensure_initialized()
        try:
            numpy = importlib.import_module("numpy")
            frame = numpy.frombuffer(pixels, dtype=numpy.uint8).reshape((height, width, 3))
            hits = tuple(self._match_one(spec, frame, width, height, timeout) for spec in self._specs)
        except SDKError:
            raise
        except Exception as error:
            raise SDKError("Recognition match failed.") from error
        return hits

    def cancel(self, timeout: float = 2.0) -> None:
        """Request bounded stop of pending recognition work without enabling input."""
        if self._tasker is None:
            return
        try:
            wait_for_job(self._tasker.post_stop(), timeout)
        except Exception as error:
            raise SDKError("Recognition cancellation failed.") from error

    def close(self) -> None:
        """Release the active tasker after a bounded stop attempt."""
        if self._closed:
            return
        try:
            self.cancel()
        finally:
            self._tasker = None
            self._closed = True

    def _ensure_initialized(self) -> None:
        if self._tasker is not None:
            return
        try:
            tasker_type, resource_type, controller_base, definitions, numpy, _ = _load_pinned_modules()
            tasker, resource = _configure_read_only_tasker(
                tasker_type, resource_type, controller_base, definitions, numpy
            )
            for spec in self._specs:
                template = numpy.frombuffer(spec.pixels, dtype=numpy.uint8).reshape((spec.height, spec.width, 3))
                if not resource.override_image(spec.template_id, template):
                    raise SDKError("Recognition SDK rejected an in-memory template.")
            self._tasker = tasker
        except SDKError:
            raise
        except Exception as error:
            raise SDKError("Recognition initialization failed.") from error

    def _match_one(self, spec: TemplateSpec, frame: Any, frame_width: int, frame_height: int,
                   timeout: float) -> TemplateHit:
        pipeline = importlib.import_module("maa.pipeline")
        job = self._tasker.post_recognition(
            pipeline.JRecognitionType.TemplateMatch,
            pipeline.JTemplateMatch(template=[spec.template_id], roi=spec.roi, threshold=[0.0]),
            frame,
        )
        wait_for_job(job, timeout)
        detail = job.get()
        if detail is None or len(detail.nodes) != 1:
            raise SDKError("Recognition returned invalid metadata.")
        recognition = detail.nodes[0].recognition
        if recognition is None or not isinstance(recognition.hit, bool):
            raise SDKError("Recognition returned invalid metadata.")
        if not recognition.hit:
            return TemplateHit(spec.template_id, 0.0, None)
        result = recognition.best_result
        if result is None:
            raise SDKError("Recognition returned invalid metadata.")
        if not _finite_number(result.score):
            raise SDKError("Recognition returned invalid metadata.")
        score = float(result.score)
        box = tuple(result.box)
        if (not math.isfinite(score) or not 0 <= score <= 1 or len(box) != 4 or
                not all(_integer(value) for value in box)):
            raise SDKError("Recognition returned invalid metadata.")
        x, y, width, height = box
        roi_x, roi_y, roi_width, roi_height = spec.roi
        if (width != spec.width or height != spec.height or x < roi_x or y < roi_y
                or x + width > roi_x + roi_width or y + height > roi_y + roi_height
                or x + width > frame_width or y + height > frame_height):
            raise SDKError("Recognition returned invalid metadata.")
        if score < spec.threshold:
            return TemplateHit(spec.template_id, score, None)
        return TemplateHit(spec.template_id, score, box)

    def _validate_frame(self, width: Any, height: Any, pixels: Any) -> None:
        _validate_frame(width, height, pixels)
        for spec in self._specs:
            x, y, roi_width, roi_height = spec.roi
            if x + roi_width > width or y + roi_height > height:
                raise ValueError("Template ROI is outside the recognition frame.")


@dataclass(frozen=True)
class LabelHit:
    """A recognized safety label with no raw OCR text or image payload."""

    label_id: str
    score: float
    box: tuple[int, int, int, int]


class LabelMatcher:
    """CPU-only OCR label filter for root-supplied patterns.

    Patterns compile with ``re.I`` and use ``fullmatch`` so unlabelled OCR text,
    including account or chat text, is discarded inside the worker.
    """

    def __init__(self, model_directory: Path, patterns: dict[str, str]) -> None:
        if not isinstance(model_directory, Path):
            raise ValueError("OCR model directory must be a Path.")
        if not isinstance(patterns, dict) or not 0 < len(patterns) <= 32:
            raise ValueError("OCR matcher requires between one and thirty-two labels.")
        compiled: list[tuple[str, re.Pattern[str]]] = []
        for label_id, expression in patterns.items():
            if (not isinstance(label_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", label_id)
                    or not isinstance(expression, str) or not 0 < len(expression) <= 128):
                raise ValueError("OCR label configuration is invalid.")
            try:
                compiled.append((label_id, re.compile(expression, re.I)))
            except re.error as error:
                raise ValueError("OCR label configuration is invalid.") from error
        self._model_directory = model_directory
        self._patterns = tuple(compiled)
        self._tasker: Any = None
        self._closed = False

    def match_labels(self, width: int, height: int, pixels: bytes, *, timeout: float = 2.0) -> tuple[LabelHit, ...]:
        """Recognize one in-memory BGR frame and return known label metadata only."""
        _validate_frame(width, height, pixels)
        if not _finite_number(timeout) or not 0 < timeout <= 2:
            raise ValueError("Recognition timeout must be finite and at most two seconds.")
        if self._closed:
            raise SDKError("Recognition matcher is closed.")
        self._ensure_initialized()
        try:
            numpy = importlib.import_module("numpy")
            frame = numpy.frombuffer(pixels, dtype=numpy.uint8).reshape((height, width, 3))
            pipeline = importlib.import_module("maa.pipeline")
            job = self._tasker.post_recognition(
                pipeline.JRecognitionType.OCR,
                pipeline.JOCR(roi=(0, 0, width, height), threshold=0.0),
                frame,
            )
            wait_for_job(job, timeout)
            detail = job.get()
            return self._label_hits(detail, width, height)
        except SDKError:
            raise
        except Exception as error:
            raise SDKError("Recognition match failed.") from error

    def cancel(self, timeout: float = 2.0) -> None:
        """Request bounded stop of pending recognition work without enabling input."""
        if self._tasker is None:
            return
        try:
            wait_for_job(self._tasker.post_stop(), timeout)
        except Exception as error:
            raise SDKError("Recognition cancellation failed.") from error

    def close(self) -> None:
        """Release the active tasker after a bounded stop attempt."""
        if self._closed:
            return
        try:
            self.cancel()
        finally:
            self._tasker = None
            self._closed = True

    def _ensure_initialized(self) -> None:
        if self._tasker is not None:
            return
        if not self._model_directory.is_dir():
            raise SDKError("Recognition OCR model is unavailable.")
        try:
            tasker_type, resource_type, controller_base, definitions, numpy, _ = _load_pinned_modules()
            tasker, resource = _configure_read_only_tasker(
                tasker_type, resource_type, controller_base, definitions, numpy
            )
            wait_for_job(resource.post_ocr_model(self._model_directory))
            self._tasker = tasker
        except SDKError:
            raise
        except Exception as error:
            raise SDKError("Recognition OCR model is unavailable.") from error

    def _label_hits(self, detail: Any, frame_width: int, frame_height: int) -> tuple[LabelHit, ...]:
        if detail is None or len(detail.nodes) != 1:
            raise SDKError("Recognition returned invalid metadata.")
        recognition = detail.nodes[0].recognition
        if recognition is None or not isinstance(recognition.hit, bool):
            raise SDKError("Recognition returned invalid metadata.")
        if not recognition.hit:
            return ()
        results = recognition.all_results
        if not isinstance(results, list) or len(results) > MAX_OCR_RESULTS:
            raise SDKError("Recognition returned invalid metadata.")
        hits: list[LabelHit] = []
        for result in results:
            text = getattr(result, "text", None)
            score = getattr(result, "score", None)
            box = getattr(result, "box", None)
            if not isinstance(text, str) or not _finite_number(score):
                raise SDKError("Recognition returned invalid metadata.")
            score = float(score)
            if not 0 <= score <= 1:
                raise SDKError("Recognition returned invalid metadata.")
            box = tuple(box) if box is not None else ()
            if (len(box) != 4 or not all(_integer(value) for value in box)):
                raise SDKError("Recognition returned invalid metadata.")
            x, y, width, height = box
            if width <= 0 or height <= 0 or x < 0 or y < 0 or x + width > frame_width or y + height > frame_height:
                raise SDKError("Recognition returned invalid metadata.")
            for label_id, pattern in self._patterns:
                if pattern.fullmatch(text):
                    hits.append(LabelHit(label_id, score, box))
                    break
        return tuple(hits)
