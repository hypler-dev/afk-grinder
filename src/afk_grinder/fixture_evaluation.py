"""Explicit-consent, local fixture evaluation; never capture or input.

The command runs image decoding and pinned Maa recognition in a disposable
child. This bounds its lifetime; it is not an operating-system sandbox.
Only static labels, scores, boxes and counters may leave the child.
"""

from __future__ import annotations

from collections import Counter
import json
import math
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import time
from typing import Any

from afk_grinder import __version__
from afk_grinder.recognition.matcher import TemplateHit, TemplateMatcher
from afk_grinder.recognition.packs import PackError, ResourcePack, load_pack
from afk_grinder.recognition.state import StaticInspection, classify_scores
from afk_grinder.training_packet import (
    MAX_JSON_BYTES, TrainingPacket, TrainingPacketError, parse_training_packet, validate_training_packet,
)


MAX_FIXTURES = 64
MAX_REPORT_BYTES = 1024 * 1024
EVALUATION_TIMEOUT = 120.0
REPORT_FORMAT = "afk-grinder-fixture-evaluation"
ERROR_CODES = frozenset({
    "consent_required", "pack_invalid", "dataset_invalid", "fixture_invalid",
    "recognition_failed", "timeout", "worker_failed", "report_invalid",
})
_ID = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}\Z")


class EvaluationError(ValueError):
    """A fixed local error code, containing no native or filesystem details."""

    def __init__(self, code: str):
        if code not in ERROR_CODES:
            code = "worker_failed"
        self.code = code
        super().__init__(code)


def _consent(consent: bool) -> None:
    if consent is not True:
        raise EvaluationError("consent_required")


def _read_json(path: Path, limit: int) -> dict[str, Any]:
    mode = path.lstat()
    if not stat.S_ISREG(mode.st_mode) or mode.st_nlink != 1 or mode.st_size > limit:
        raise ValueError("Invalid bounded JSON file.")
    with path.open("rb") as stream:
        contents = stream.read(limit + 1)
    if len(contents) > limit:
        raise ValueError("Invalid bounded JSON file.")
    def unique_pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key.")
            result[key] = value
        return result

    payload = json.loads(contents, object_pairs_hook=unique_pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Non-finite JSON.")))
    if type(payload) is not dict:
        raise ValueError("Invalid JSON object.")
    return payload


def _aggregate(pack: ResourcePack, compiled: Any, hits: tuple[TemplateHit, ...]) -> tuple[dict[str, float | None], list[dict[str, Any]]]:
    expected = {item.spec.template_id: item for item in compiled.templates}
    if type(hits) is not tuple or len(hits) != len(expected):
        raise EvaluationError("recognition_failed")
    received = set()
    by_anchor: dict[str, list[TemplateHit]] = {anchor.id: [] for anchor in pack.anchors}
    for hit in hits:
        if type(hit) is not TemplateHit or hit.template_id not in expected or hit.template_id in received:
            raise EvaluationError("recognition_failed")
        item = expected[hit.template_id]
        if type(hit.score) not in (int, float) or not math.isfinite(hit.score) or not 0 <= hit.score <= 1:
            raise EvaluationError("recognition_failed")
        if hit.box is not None:
            if (type(hit.box) is not tuple or len(hit.box) != 4 or any(type(v) is not int for v in hit.box)
                    or hit.score < item.spec.threshold):
                raise EvaluationError("recognition_failed")
            x, y, width, height = hit.box
            rx, ry, rw, rh = item.spec.roi
            if (width != item.spec.width or height != item.spec.height or x < rx or y < ry
                    or x + width > rx + rw or y + height > ry + rh):
                raise EvaluationError("recognition_failed")
        by_anchor[item.anchor_id].append(hit)
        received.add(hit.template_id)
    scores: dict[str, float | None] = {}
    anchors = []
    for anchor in pack.anchors:
        variants = by_anchor[anchor.id]
        if not variants:
            raise EvaluationError("recognition_failed")
        best = max(variants, key=lambda item: item.score)
        # An absent hit at a zero threshold cannot assert positive evidence.
        score = float(best.score) if best.box is not None or best.score < anchor.threshold else None
        scores[anchor.id] = score
        anchors.append({"id": anchor.id, "score": score, "box": list(best.box) if best.box is not None else None})
    return scores, anchors


def evaluate_fixtures(pack: ResourcePack, packet: TrainingPacket, directory: Path, *,
                      consent: bool = False, split: str = "held_out", matcher_factory: Any = None) -> dict[str, Any]:
    """Evaluate static examples; never simulate temporal frames or approve a pack."""
    _consent(consent)
    from afk_grinder.recognition.pack_compiler import (
        MAX_COMPILED_PIXELS, MAX_COMPILED_TEMPLATES, compile_pack,
    )
    from afk_grinder.training_fixtures import load_fixture

    try:
        packet = validate_training_packet(packet)
    except (TrainingPacketError, ValueError, TypeError):
        raise EvaluationError("dataset_invalid") from None
    if split not in {"train", "validation", "held_out"}:
        raise EvaluationError("dataset_invalid")
    if type(pack) is not ResourcePack or not pack.anchors or not pack.states:
        raise EvaluationError("pack_invalid")
    try:
        # Validate assets and the reference workload even if every selected
        # fixture has an unsupported layout. Such fixtures cannot bypass pack
        # validation or produce a successful report for malformed assets.
        compiled = compile_pack(pack, pack.reference_size)
    except (PackError, ValueError, TypeError):
        raise EvaluationError("pack_invalid") from None
    states = {state.id: state for state in pack.states}
    if (packet.reference_size != pack.reference_size or packet.locale != pack.setup.language
            or any(state.id not in states or states[state.id].kind != state.kind for state in packet.states)):
        raise EvaluationError("dataset_invalid")
    selected = tuple(example for example in packet.examples if example.split == split)
    if not 0 < len(selected) <= MAX_FIXTURES:
        raise EvaluationError("dataset_invalid")

    class PackTemplateMatcher(TemplateMatcher):
        # These limits are application code, never fields supplied by a pack.
        _template_limit = MAX_COMPILED_TEMPLATES
        _template_pixel_limit = MAX_COMPILED_PIXELS

    factory = matcher_factory or PackTemplateMatcher
    matcher = None
    rows = []
    confusion: dict[str, Counter] = {}
    exact_matches = unsafe = 0
    expected_states = {state.id: state for state in packet.states}
    try:
        for example in selected:
            try:
                frame = load_fixture(directory, example, consent=True)
            except Exception:
                raise EvaluationError("fixture_invalid") from None
            size = (frame.width, frame.height)
            expected = expected_states[example.state_id]
            ratio = (frame.width / frame.height) / (pack.reference_size[0] / pack.reference_size[1])
            if (abs(ratio - 1) > 0.01 or frame.width < pack.setup.min_content_size[0]
                    or frame.height < pack.setup.min_content_size[1]):
                prediction = StaticInspection("unknown", None, "unsupported_layout")
                anchors, elapsed, variant_count = [], 0.0, 0
            else:
                prediction = None
            if prediction is None:
                if compiled.frame_size != size:
                    if matcher is not None:
                        matcher.close()
                        matcher = None
                    try:
                        compiled = compile_pack(pack, size)
                    except (PackError, ValueError, TypeError):
                        raise EvaluationError("pack_invalid") from None
                if matcher is None:
                    matcher = factory(tuple(item.spec for item in compiled.templates))
                    matcher.warmup()
            if prediction is None:
                started = time.monotonic()
                hits = matcher.match(frame.width, frame.height, frame.pixels, timeout=2.0)
                elapsed = (time.monotonic() - started) * 1000
                scores, anchors = _aggregate(pack, compiled, hits)
                prediction = classify_scores(pack, scores)
                variant_count = len(compiled.templates)
                del hits
            bucket = prediction.state_id or f"__{prediction.status}__"
            confusion.setdefault(expected.id, Counter())[bucket] += 1
            exact_matches += prediction.state_id == expected.id
            unsafe += expected.kind != "gameplay" and prediction.status == "candidate"
            rows.append({
                "example_id": example.id, "expected_state": expected.id, "expected_kind": expected.kind,
                "predicted_state": prediction.state_id, "predicted_kind": prediction.kind,
                "status": prediction.status, "reason": prediction.reason,
                "width": frame.width, "height": frame.height, "latency_ms": round(elapsed, 3),
                "variant_count": variant_count, "anchors": anchors,
            })
            del frame
    except EvaluationError:
        raise
    except Exception:
        raise EvaluationError("recognition_failed") from None
    finally:
        if matcher is not None:
            try:
                matcher.close()
            except Exception:
                raise EvaluationError("recognition_failed") from None
    return {
        "format": REPORT_FORMAT, "schema_version": 1, "app_version": __version__,
        "pack": {"id": pack.id, "version": pack.version},
        "dataset": {"id": packet.id, "version": packet.version, "locale": packet.locale},
        "split": split, "example_count": len(rows), "exact_label_matches": exact_matches,
        "unsafe_protected_predictions": unsafe, "confusion": {key: dict(value) for key, value in confusion.items()},
        "temporal_stability_evaluated": False, "live_readiness": False, "approved": False,
        "native_input": False, "screen_capture": False, "persistent_images": False, "model_training": False,
        "examples": rows,
    }


def _load_metadata(pack_directory: Path, packet_path: Path) -> tuple[ResourcePack, TrainingPacket]:
    """Read strict pack/packet metadata and encoded assets, without decoding pixels."""
    try:
        pack = load_pack(pack_directory, app_version=__version__)
    except Exception:
        raise EvaluationError("pack_invalid") from None
    try:
        packet_data = _read_json(packet_path, MAX_JSON_BYTES)
        packet = parse_training_packet(json.dumps(packet_data, allow_nan=False))
    except Exception:
        raise EvaluationError("dataset_invalid") from None
    return pack, packet


def worker(pack_directory: Path, packet_path: Path, fixture_directory: Path, report_path: Path, *,
           consent: bool, split: str) -> None:
    """Write a private bounded status file for the controlling process."""
    try:
        _consent(consent)
        pack, packet = _load_metadata(pack_directory, packet_path)
        report = evaluate_fixtures(pack, packet, fixture_directory, consent=True, split=split)
        payload = {"ok": True, "report": report}
    except EvaluationError as error:
        payload = {"ok": False, "error": error.code}
    except Exception:
        payload = {"ok": False, "error": "worker_failed"}
    encoded = json.dumps(payload, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_REPORT_BYTES:
        encoded = json.dumps({"ok": False, "error": "report_invalid"})
    with report_path.open("x", encoding="utf-8") as stream:
        stream.write(encoded)


def _validate_report(payload: dict[str, Any]) -> dict[str, Any]:
    if type(payload) is not dict:
        raise EvaluationError("report_invalid")
    if set(payload) != {"ok", "report"} or payload["ok"] is not True:
        if (set(payload) == {"ok", "error"} and payload["ok"] is False
                and type(payload["error"]) is str and payload["error"] in ERROR_CODES):
            raise EvaluationError(payload["error"])
        raise EvaluationError("report_invalid")
    report = payload["report"]
    expected = {"format", "schema_version", "app_version", "pack", "dataset", "split", "example_count",
                "exact_label_matches", "unsafe_protected_predictions", "confusion", "temporal_stability_evaluated",
                "live_readiness", "approved", "native_input", "screen_capture", "persistent_images", "model_training", "examples"}
    if (type(report) is not dict or set(report) != expected or report["format"] != REPORT_FORMAT
            or type(report["schema_version"]) is not int or report["schema_version"] != 1
            or report["app_version"] != __version__ or type(report["split"]) is not str
            or report["split"] not in {"train", "validation", "held_out"}):
        raise EvaluationError("report_invalid")
    for field in ("temporal_stability_evaluated", "live_readiness", "approved", "native_input", "screen_capture", "persistent_images", "model_training"):
        if report[field] is not False:
            raise EvaluationError("report_invalid")
    count = report["example_count"]
    if type(count) is not int or not 0 < count <= MAX_FIXTURES or type(report["examples"]) is not list or len(report["examples"]) != count:
        raise EvaluationError("report_invalid")
    for field in ("exact_label_matches", "unsafe_protected_predictions"):
        if type(report[field]) is not int or not 0 <= report[field] <= count:
            raise EvaluationError("report_invalid")
    for field, keys in (("pack", {"id", "version"}), ("dataset", {"id", "version", "locale"})):
        if type(report[field]) is not dict or set(report[field]) != keys:
            raise EvaluationError("report_invalid")
        if any(type(value) is not str or not 0 < len(value) <= 64 for value in report[field].values()):
            raise EvaluationError("report_invalid")
        if (not _ID.fullmatch(report[field]["id"])
                or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", report[field]["version"])):
            raise EvaluationError("report_invalid")
    if report["dataset"]["locale"] != "en":
        raise EvaluationError("report_invalid")
    row_keys = {"example_id", "expected_state", "expected_kind", "predicted_state", "predicted_kind", "status", "reason", "width", "height", "latency_ms", "variant_count", "anchors"}
    seen_examples = set()
    actual_confusion: dict[str, Counter] = {}
    actual_matches = actual_unsafe = 0
    kinds = {"gameplay", "popup", "transaction", "loading", "disconnected", "unknown"}
    for row in report["examples"]:
        if type(row) is not dict or set(row) != row_keys:
            raise EvaluationError("report_invalid")
        for field in ("example_id", "expected_state", "expected_kind", "status", "reason"):
            if type(row[field]) is not str or not _ID.fullmatch(row[field]):
                raise EvaluationError("report_invalid")
        for field in ("predicted_state", "predicted_kind"):
            if row[field] is not None and (type(row[field]) is not str or not _ID.fullmatch(row[field])):
                raise EvaluationError("report_invalid")
        if (row["example_id"] in seen_examples or row["expected_kind"] not in kinds
                or row["predicted_kind"] is not None and row["predicted_kind"] not in kinds | {"unclassified"}
                or row["status"] not in {"candidate", "unknown", "blocked"}
                or any(type(row[field]) is not int or row[field] <= 0 for field in ("width", "height"))
                or type(row["variant_count"]) is not int or row["variant_count"] < 0
                or row["width"] * row["height"] > 16_000_000 or row["variant_count"] > 576
                or type(row["latency_ms"]) not in (int, float) or not math.isfinite(row["latency_ms"]) or row["latency_ms"] < 0
                or type(row["anchors"]) is not list or len(row["anchors"]) > min(64, row["variant_count"])):
            raise EvaluationError("report_invalid")
        if row["variant_count"] == 0:
            if (row["status"] != "unknown" or row["reason"] != "unsupported_layout"
                    or row["predicted_state"] is not None or row["predicted_kind"] is not None or row["anchors"]):
                raise EvaluationError("report_invalid")
        elif not row["anchors"]:
            raise EvaluationError("report_invalid")
        if row["status"] == "candidate":
            valid_classification = (row["predicted_state"] is not None
                                    and row["predicted_kind"] in {"gameplay", "unclassified"}
                                    and row["reason"] == "unstabilized")
        elif row["status"] == "blocked":
            valid_classification = (
                row["predicted_state"] is None and row["predicted_kind"] is None and row["reason"] == "excluded"
                or row["predicted_state"] is not None and row["predicted_kind"] in {"popup", "transaction", "loading", "disconnected"}
                and row["reason"] == row["predicted_kind"]
            )
        else:
            valid_classification = (
                row["predicted_state"] is not None and row["predicted_kind"] == "unknown" and row["reason"] == "unknown_screen"
                or row["predicted_state"] is None and row["predicted_kind"] is None
                and row["reason"] in {"invalid_evidence", "no_match", "insufficient_evidence", "ambiguous", "invalid_state_kind", "unsupported_layout"}
            )
        if not valid_classification:
            raise EvaluationError("report_invalid")
        seen_examples.add(row["example_id"])
        actual_confusion.setdefault(row["expected_state"], Counter())[row["predicted_state"] or f"__{row['status']}__"] += 1
        actual_matches += row["predicted_state"] == row["expected_state"]
        actual_unsafe += row["expected_kind"] != "gameplay" and row["status"] == "candidate"
        seen_anchors = set()
        for anchor in row["anchors"]:
            if (type(anchor) is not dict or set(anchor) != {"id", "score", "box"}
                    or type(anchor["id"]) is not str or not _ID.fullmatch(anchor["id"])):
                raise EvaluationError("report_invalid")
            if anchor["id"] in seen_anchors:
                raise EvaluationError("report_invalid")
            seen_anchors.add(anchor["id"])
            score, box = anchor["score"], anchor["box"]
            if score is not None and (type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1):
                raise EvaluationError("report_invalid")
            if box is not None:
                if (score is None or type(box) is not list or len(box) != 4 or any(type(value) is not int for value in box)
                        or min(box[:2]) < 0 or min(box[2:]) <= 0
                        or box[0] + box[2] > row["width"] or box[1] + box[3] > row["height"]):
                    raise EvaluationError("report_invalid")
    if type(report["confusion"]) is not dict:
        raise EvaluationError("report_invalid")
    total = 0
    for label, predictions in report["confusion"].items():
        if type(label) is not str or not _ID.fullmatch(label) or type(predictions) is not dict:
            raise EvaluationError("report_invalid")
        for prediction, value in predictions.items():
            if (type(prediction) is not str or not (prediction in {"__blocked__", "__unknown__"} or _ID.fullmatch(prediction))
                    or type(value) is not int or not 0 < value <= count):
                raise EvaluationError("report_invalid")
            total += value
    if (total != count or report["confusion"] != {key: dict(value) for key, value in actual_confusion.items()}
            or report["exact_label_matches"] != actual_matches or report["unsafe_protected_predictions"] != actual_unsafe):
        raise EvaluationError("report_invalid")
    return report


def _bind_report(report: dict[str, Any], pack: ResourcePack, packet: TrainingPacket, split: str) -> None:
    """Bind child metadata to parent-selected inputs, never child-provided labels."""
    selected = tuple(example for example in packet.examples if example.split == split)
    if (report["pack"] != {"id": pack.id, "version": pack.version}
            or report["dataset"] != {"id": packet.id, "version": packet.version, "locale": packet.locale}
            or report["split"] != split or report["example_count"] != len(selected)):
        raise EvaluationError("report_invalid")
    expected_states = {state.id: state for state in packet.states}
    pack_states = {state.id: state for state in pack.states}
    anchor_ids = [anchor.id for anchor in pack.anchors]
    if (packet.reference_size != pack.reference_size or packet.locale != pack.setup.language
            or any(state.id not in pack_states or pack_states[state.id].kind != state.kind for state in packet.states)):
        raise EvaluationError("report_invalid")
    for row, example in zip(report["examples"], selected, strict=True):
        expected = expected_states[example.state_id]
        predicted = pack_states.get(row["predicted_state"])
        if (row["example_id"] != example.id or row["expected_state"] != expected.id
                or row["expected_kind"] != expected.kind
                or (row["width"], row["height"]) != (example.width, example.height)
                or row["predicted_state"] is not None and (predicted is None or predicted.kind != row["predicted_kind"])
                or row["variant_count"] > 0 and [anchor["id"] for anchor in row["anchors"]] != anchor_ids):
            raise EvaluationError("report_invalid")
        ratio = (example.width / example.height) / (pack.reference_size[0] / pack.reference_size[1])
        unsupported = (abs(ratio - 1) > 0.01 or example.width < pack.setup.min_content_size[0]
                       or example.height < pack.setup.min_content_size[1])
        if (row["variant_count"] == 0) != unsupported:
            raise EvaluationError("report_invalid")
        if not unsupported:
            scores = {}
            for metadata, anchor in zip(row["anchors"], pack.anchors, strict=True):
                score = metadata["score"]
                if (metadata["box"] is None and score is not None and score >= anchor.threshold
                        or metadata["box"] is not None and score < anchor.threshold):
                    raise EvaluationError("report_invalid")
                scores[anchor.id] = score
            prediction = classify_scores(pack, scores)
            if (prediction.status, prediction.state_id, prediction.kind, prediction.reason) != (
                    row["status"], row["predicted_state"], row["predicted_kind"], row["reason"]):
                raise EvaluationError("report_invalid")


def run_evaluation(pack_directory: Path, packet_path: Path, fixture_directory: Path, *,
                   consent: bool = False, split: str = "held_out") -> dict[str, Any]:
    """Bound decoding, native calls and teardown to one disposable process."""
    _consent(consent)
    if split not in {"train", "validation", "held_out"}:
        raise EvaluationError("dataset_invalid")
    pack, packet = _load_metadata(pack_directory, packet_path)
    if not 0 < sum(example.split == split for example in packet.examples) <= MAX_FIXTURES:
        raise EvaluationError("dataset_invalid")
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command += ["-m", "afk_grinder"]
    with tempfile.TemporaryDirectory(prefix="afk-grinder-fixture-") as directory:
        report_path = Path(directory) / "report.json"
        command += ["--fixture-worker", str(pack_directory), "--training-packet", str(packet_path),
                    "--fixture-directory", str(fixture_directory), "--fixture-report", str(report_path),
                    "--fixture-consent", "--fixture-split", split]
        try:
            process = subprocess.run(command, timeout=EVALUATION_TIMEOUT,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        except subprocess.TimeoutExpired:
            raise EvaluationError("timeout") from None
        except OSError:
            raise EvaluationError("worker_failed") from None
        try:
            payload = _read_json(report_path, MAX_REPORT_BYTES)
            if process.returncode != 0:
                raise EvaluationError("worker_failed")
            report = _validate_report(payload)
            _bind_report(report, pack, packet, split)
            return report
        except EvaluationError:
            raise
        except Exception:
            raise EvaluationError("report_invalid") from None
