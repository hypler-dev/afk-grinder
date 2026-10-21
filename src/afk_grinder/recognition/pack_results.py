"""Bounded template-to-anchor metadata, shared by offline and live inspection.

This module has no decoding, capture, input, SDK initialization or file APIs.
Reported scores are recognition evidence, never permission to perform an action.
"""

from dataclasses import dataclass
import math
from typing import TYPE_CHECKING

from .matcher import TemplateHit
from .packs import ResourcePack

if TYPE_CHECKING:
    from .pack_compiler import CompiledPack


class PackResultError(ValueError):
    """A pack matcher returned incomplete or inconsistent metadata."""


@dataclass(frozen=True, slots=True)
class AnchorHit:
    id: str
    score: float | None
    box: tuple[int, int, int, int] | None


def _score(value: object) -> bool:
    try:
        return type(value) in (int, float) and math.isfinite(value) and 0 <= value <= 1
    except OverflowError:
        return False


def aggregate_hits(pack: ResourcePack, compiled: "CompiledPack",
                   hits: tuple[TemplateHit, ...]) -> tuple[AnchorHit, ...]:
    """Require every compiled variant, then select one conservative anchor score."""
    expected = {item.spec.template_id: item for item in compiled.templates}
    if (len(expected) != len(compiled.templates) or type(hits) is not tuple
            or len(hits) != len(expected)):
        raise PackResultError("Incomplete template results.")
    received = set()
    by_anchor: dict[str, list[TemplateHit]] = {anchor.id: [] for anchor in pack.anchors}
    for hit in hits:
        if (type(hit) is not TemplateHit or type(hit.template_id) is not str
                or hit.template_id not in expected or hit.template_id in received or not _score(hit.score)):
            raise PackResultError("Invalid template result.")
        item = expected[hit.template_id]
        if item.anchor_id not in by_anchor:
            raise PackResultError("Unknown anchor result.")
        if hit.box is not None:
            if (type(hit.box) is not tuple or len(hit.box) != 4 or any(type(v) is not int for v in hit.box)
                    or hit.score < item.spec.threshold):
                raise PackResultError("Invalid template box.")
            x, y, width, height = hit.box
            rx, ry, rw, rh = item.spec.roi
            if (width != item.spec.width or height != item.spec.height or x < rx or y < ry
                    or x + width > rx + rw or y + height > ry + rh):
                raise PackResultError("Template box leaves its search region.")
        by_anchor[item.anchor_id].append(hit)
        received.add(hit.template_id)
    results = []
    for anchor in pack.anchors:
        variants = by_anchor[anchor.id]
        if not variants:
            raise PackResultError("Missing anchor result.")
        best = max(variants, key=lambda item: item.score)
        # A miss at a zero threshold must not become positive evidence.
        score = float(best.score) if best.box is not None or best.score < anchor.threshold else None
        results.append(AnchorHit(anchor.id, score, best.box))
    # Compiled ROIs may use an explicit offset viewport. Each native hit was
    # checked against that exact compiled spec above; the live service's
    # separate parent check applies to its already-cropped, full-frame layout.
    return tuple(results)


def validate_anchor_hits(pack: ResourcePack, frame_size: tuple[int, int],
                         hits: tuple[AnchorHit, ...]) -> tuple[AnchorHit, ...]:
    """Validate metadata against the parent-owned pack and physical frame.

    The native worker remains responsible for matching image pixels. This check
    prevents a response from changing anchor identities, thresholds or ROIs.
    """
    if (type(pack) is not ResourcePack or type(frame_size) is not tuple or len(frame_size) != 2
            or any(type(v) is not int or v <= 0 for v in frame_size)
            or frame_size[0] * frame_size[1] > 16_000_000
            or type(hits) is not tuple or len(hits) != len(pack.anchors)):
        raise PackResultError("Invalid anchor results.")
    width, height = frame_size
    reference_width, reference_height = pack.reference_size
    if (abs((width / height) / (reference_width / reference_height) - 1) > .01
            or width < pack.setup.min_content_size[0] or height < pack.setup.min_content_size[1]):
        raise PackResultError("Unsupported anchor layout.")
    for hit, anchor in zip(hits, pack.anchors, strict=True):
        if (type(hit) is not AnchorHit or hit.id != anchor.id
                or hit.score is not None and not _score(hit.score)):
            raise PackResultError("Invalid anchor identity or score.")
        if hit.box is None:
            if hit.score is not None and hit.score >= anchor.threshold:
                raise PackResultError("Passing anchor score has no box.")
            continue
        if (hit.score is None or hit.score < anchor.threshold or type(hit.box) is not tuple
                or len(hit.box) != 4 or any(type(v) is not int for v in hit.box)):
            raise PackResultError("Invalid anchor box.")
        x, y, box_width, box_height = hit.box
        rx, ry, rw, rh = anchor.roi
        left = math.ceil(rx * width / reference_width)
        top = math.ceil(ry * height / reference_height)
        right = math.floor((rx + rw) * width / reference_width)
        bottom = math.floor((ry + rh) * height / reference_height)
        if (not 8 <= box_width <= 512 or not 8 <= box_height <= 512
                or x < left or y < top or x + box_width > right or y + box_height > bottom):
            raise PackResultError("Anchor box leaves its search region.")
    return hits
