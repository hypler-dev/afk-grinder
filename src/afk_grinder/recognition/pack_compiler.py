"""Compile one validated resource pack into bounded in-memory matcher specs.

This module receives already-loaded pack data, revalidates its immutable
snapshot, and returns only BGR templates plus frame-relative search regions.
It does not open paths, initialize MaaFramework, capture pixels, or authorize
input.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import math
import struct
from typing import Final

from PIL import Image

from afk_grinder import __version__
from .matcher import TemplateSpec
from .observation import Rect
from .packs import (
    Anchor,
    Asset,
    PackError,
    Provenance,
    ResourcePack,
    Setup,
    State,
    MAX_ASSET_BYTES,
    MAX_TOTAL_ASSET_BYTES,
    _validate_manifest,
    _validate_png,
)


MAX_COMPILED_TEMPLATES: Final = 576
MAX_COMPILED_TEMPLATE_PIXELS: Final = 4_000_000
# Public evaluator compatibility name: total pixels across compiled variants.
MAX_COMPILED_PIXELS: Final = MAX_COMPILED_TEMPLATE_PIXELS
MAX_DECODED_SOURCE_ASSET_PIXELS: Final = 4_000_000
MAX_SUMMED_VARIANT_ROI_PIXELS: Final = 64_000_000
MAX_FRAME_PIXELS: Final = 16_000_000
MAX_SCALE_VARIANTS: Final = 9
_PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"
_ALLOWED_PNG_CHUNKS: Final = frozenset({b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS"})
_APNG_CHUNKS: Final = frozenset({b"acTL", b"fcTL", b"fdAT"})


class PackCompileError(ValueError):
    """Raised when an immutable pack cannot form safe matcher inputs."""


@dataclass(frozen=True, slots=True)
class CompiledTemplate:
    """One engine-owned template spec, associated only with its anchor ID."""

    anchor_id: str
    spec: TemplateSpec


@dataclass(frozen=True, slots=True)
class CompiledPack:
    """Bounded in-memory templates for one exact pack and physical frame."""

    pack_id: str
    pack_version: str
    frame_size: tuple[int, int]
    templates: tuple[CompiledTemplate, ...]


def compile_pack(
    pack: ResourcePack,
    frame_size: tuple[int, int],
    *,
    viewport: Rect | None = None,
) -> CompiledPack:
    """Compile validated pack assets into immutable BGR TemplateSpecs.

    ``viewport`` is physical capture pixels containing the reference content.
    It is never stretched: template scale uses its smaller reference axis.
    """
    frame_width, frame_height = _frame_size(frame_size)
    snapshot = _validated_snapshot(pack)
    active_viewport = _viewport(viewport, frame_width, frame_height, snapshot)
    decoded_assets = _decode_assets(snapshot)

    nominal_scale = min(
        active_viewport.width / snapshot.reference_size[0],
        active_viewport.height / snapshot.reference_size[1],
    )
    templates: list[CompiledTemplate] = []
    compiled_pixels = 0
    summed_roi_pixels = 0
    for anchor_index, anchor in enumerate(snapshot.anchors):
        roi = _map_roi(anchor, snapshot.reference_size, active_viewport, frame_width, frame_height)
        image = decoded_assets[anchor.asset]
        dimensions: set[tuple[int, int]] = set()
        for factor in _scale_factors(anchor.scale_range):
            width = _round_pixel(image.width * nominal_scale * factor)
            height = _round_pixel(image.height * nominal_scale * factor)
            if not 8 <= width <= 512 or not 8 <= height <= 512:
                raise PackCompileError("template scale is outside matcher dimensions")
            dimensions.add((width, height))
        for variant_index, (width, height) in enumerate(sorted(dimensions)):
            if width > roi[2] or height > roi[3]:
                raise PackCompileError("mapped ROI cannot represent requested template search")
            pixel_count = width * height
            if len(templates) + 1 > MAX_COMPILED_TEMPLATES:
                raise PackCompileError("compiled template count exceeds limit")
            if compiled_pixels + pixel_count > MAX_COMPILED_TEMPLATE_PIXELS:
                raise PackCompileError("compiled template pixels exceed limit")
            if summed_roi_pixels + roi[2] * roi[3] > MAX_SUMMED_VARIANT_ROI_PIXELS:
                raise PackCompileError("compiled ROI search work exceeds limit")
            resized = image if image.size == (width, height) else image.resize(
                (width, height), Image.Resampling.LANCZOS
            )
            pixels = resized.tobytes("raw", "BGR")
            if _is_flat_bgr(pixels, width, height):
                raise PackCompileError("flat templates are unsupported for normalized matching")
            spec = TemplateSpec(
                f"p{anchor_index:02d}s{variant_index:02d}", width, height, pixels, roi, anchor.threshold
            )
            templates.append(CompiledTemplate(anchor.id, spec))
            compiled_pixels += pixel_count
            summed_roi_pixels += roi[2] * roi[3]
    return CompiledPack(snapshot.id, snapshot.version, (frame_width, frame_height), tuple(templates))


def _frame_size(value: object) -> tuple[int, int]:
    if (type(value) is not tuple or len(value) != 2
            or any(type(dimension) is not int or dimension <= 0 for dimension in value)):
        raise PackCompileError("frame_size must be two positive integer physical pixels")
    width, height = value
    if width * height > MAX_FRAME_PIXELS:
        raise PackCompileError("frame dimensions exceed compiler limit")
    return width, height


def _validated_snapshot(pack: object) -> ResourcePack:
    if type(pack) is not ResourcePack:
        raise TypeError("compile_pack requires a loaded ResourcePack")
    _exact_pack_types(pack)
    payload = {
        "format": "afk-resource-pack",
        "schema_version": 1,
        "id": pack.id,
        "version": pack.version,
        "min_app_version": pack.min_app_version,
        "provenance": {
            "source": pack.provenance.source,
            "revision": pack.provenance.revision,
            "license": pack.provenance.license,
            "attribution": pack.provenance.attribution,
        },
        "reference_size": list(pack.reference_size),
        "setup": {
            "language": pack.setup.language,
            "instructions": pack.setup.instructions,
            "min_content_size": list(pack.setup.min_content_size),
        },
        "assets": [
            {"id": asset.id, "path": asset.path, "sha256": asset.sha256}
            for asset in pack.assets
        ],
        "anchors": [
            {
                "id": anchor.id,
                "asset": anchor.asset,
                "roi": list(anchor.roi),
                "threshold": anchor.threshold,
                "scale_range": list(anchor.scale_range),
            }
            for anchor in pack.anchors
        ],
        "states": [
            {
                "id": state.id,
                "positive": list(state.positive),
                "exclude": list(state.exclude),
                "stable_frames": state.stable_frames,
                "kind": state.kind,
            }
            for state in pack.states
        ],
        "routines": [],
    }
    try:
        rebuilt = _validate_manifest(payload, __version__)
    except PackError as error:
        raise PackCompileError("pack snapshot no longer meets resource-pack schema") from error
    if not _same_snapshot(pack, rebuilt):
        raise PackCompileError("pack snapshot changed during schema reconstruction")
    return pack


def _exact_pack_types(pack: ResourcePack) -> None:
    if (type(pack.id) is not str or type(pack.version) is not str or type(pack.min_app_version) is not str
            or type(pack.provenance) is not Provenance or type(pack.setup) is not Setup
            or type(pack.reference_size) is not tuple or type(pack.assets) is not tuple
            or type(pack.anchors) is not tuple or type(pack.states) is not tuple):
        raise PackCompileError("pack contains unsupported mutable or derived values")
    if not all(type(value) is str for value in (
        pack.provenance.source, pack.provenance.revision, pack.provenance.license, pack.provenance.attribution,
        pack.setup.language, pack.setup.instructions,
    )):
        raise PackCompileError("pack metadata types are invalid")
    if not _integer_tuple(pack.reference_size, 2) or not _integer_tuple(pack.setup.min_content_size, 2):
        raise PackCompileError("pack size types are invalid")
    for asset in pack.assets:
        if (type(asset) is not Asset or type(asset.id) is not str or type(asset.path) is not str
                or type(asset.sha256) is not str or type(asset.data) is not bytes):
            raise PackCompileError("pack asset types are invalid")
    for anchor in pack.anchors:
        if (type(anchor) is not Anchor or type(anchor.id) is not str or type(anchor.asset) is not str
                or not _integer_tuple(anchor.roi, 4) or not _finite_number(anchor.threshold)
                or not _number_tuple(anchor.scale_range, 2)):
            raise PackCompileError("pack anchor types are invalid")
    for state in pack.states:
        if (type(state) is not State or type(state.id) is not str or type(state.positive) is not tuple
                or type(state.exclude) is not tuple or type(state.stable_frames) is not int
                or type(state.kind) is not str or not all(type(value) is str for value in state.positive + state.exclude)):
            raise PackCompileError("pack state types are invalid")


def _same_snapshot(source: ResourcePack, rebuilt: ResourcePack) -> bool:
    return (
        source.id == rebuilt.id and source.version == rebuilt.version
        and source.min_app_version == rebuilt.min_app_version
        and source.provenance == rebuilt.provenance and source.reference_size == rebuilt.reference_size
        and source.setup == rebuilt.setup and tuple(
            (asset.id, asset.path, asset.sha256) for asset in source.assets
        ) == tuple((asset.id, asset.path, asset.sha256) for asset in rebuilt.assets)
        and source.anchors == rebuilt.anchors and source.states == rebuilt.states
    )


def _viewport(viewport: Rect | None, frame_width: int, frame_height: int, pack: ResourcePack) -> Rect:
    active = Rect(0, 0, frame_width, frame_height) if viewport is None else viewport
    if type(active) is not Rect:
        raise TypeError("viewport must be a Rect or None")
    if (active.x < 0 or active.y < 0 or active.x + active.width > frame_width
            or active.y + active.height > frame_height):
        raise PackCompileError("viewport must stay inside physical frame")
    reference_width, reference_height = pack.reference_size
    aspect = (active.width / active.height) / (reference_width / reference_height)
    if abs(aspect - 1) > 0.01:
        raise PackCompileError("viewport aspect differs from reference by more than one percent")
    minimum_width, minimum_height = pack.setup.min_content_size
    if active.width < minimum_width or active.height < minimum_height:
        raise PackCompileError("viewport is smaller than pack minimum content size")
    return active


def _decode_assets(pack: ResourcePack) -> dict[str, Image.Image]:
    sanitized: dict[str, tuple[bytes, tuple[int, int]]] = {}
    total_pixels = 0
    total_bytes = 0
    for asset in pack.assets:
        if len(asset.data) > MAX_ASSET_BYTES:
            raise PackCompileError("pack asset bytes exceed loader limit")
        total_bytes += len(asset.data)
        if total_bytes > MAX_TOTAL_ASSET_BYTES:
            raise PackCompileError("total pack asset bytes exceed loader limit")
        if sha256(asset.data).hexdigest() != asset.sha256:
            raise PackCompileError("pack asset hash changed before compilation")
        try:
            _validate_png(asset.data, asset.path)
            png, size = _sanitize_png(asset.data)
        except PackError as error:
            raise PackCompileError("pack asset PNG structure is invalid") from error
        total_pixels += size[0] * size[1]
        if total_pixels > MAX_DECODED_SOURCE_ASSET_PIXELS:
            raise PackCompileError("decoded source asset pixels exceed limit")
        sanitized[asset.id] = (png, size)

    decoded: dict[str, Image.Image] = {}
    for asset in pack.assets:
        png, expected_size = sanitized[asset.id]
        try:
            with Image.open(BytesIO(png)) as opened:
                if opened.format != "PNG" or opened.size != expected_size:
                    raise PackCompileError("PNG decoder disagrees with validated structure")
                opened.load()
                if _has_nonopaque_alpha(opened):
                    raise PackCompileError("transparent templates are unsupported")
                decoded[asset.id] = opened.convert("RGB")
        except PackCompileError:
            raise
        except Exception as error:
            raise PackCompileError("PNG decoder rejected validated asset bytes") from error
    return decoded


def _sanitize_png(data: bytes) -> tuple[bytes, tuple[int, int]]:
    """Keep image chunks only; never offer arbitrary ancillary metadata to Pillow."""
    chunks = [_PNG_SIGNATURE]
    offset = len(_PNG_SIGNATURE)
    width = height = 0
    while offset < len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        end = offset + 12 + length
        chunk_type = data[offset + 4:offset + 8]
        if chunk_type in _APNG_CHUNKS:
            raise PackCompileError("animated PNG templates are unsupported")
        if chunk_type not in _ALLOWED_PNG_CHUNKS:
            if 65 <= chunk_type[0] <= 90:
                raise PackCompileError("PNG has unsupported critical chunk")
        else:
            chunks.append(data[offset:end])
        if chunk_type == b"IHDR":
            width, height = struct.unpack(">II", data[offset + 8:offset + 16])
        offset = end
    return b"".join(chunks), (width, height)


def _has_nonopaque_alpha(image: Image.Image) -> bool:
    if "A" not in image.getbands() and "transparency" not in image.info:
        return False
    return image.convert("RGBA").getchannel("A").getextrema() != (255, 255)


def _map_roi(
    anchor: Anchor,
    reference_size: tuple[int, int],
    viewport: Rect,
    frame_width: int,
    frame_height: int,
) -> tuple[int, int, int, int]:
    x, y, width, height = anchor.roi
    reference_width, reference_height = reference_size
    left = math.ceil(viewport.x + x * viewport.width / reference_width)
    top = math.ceil(viewport.y + y * viewport.height / reference_height)
    right = math.floor(viewport.x + (x + width) * viewport.width / reference_width)
    bottom = math.floor(viewport.y + (y + height) * viewport.height / reference_height)
    if not (0 <= left < right <= frame_width and 0 <= top < bottom <= frame_height):
        raise PackCompileError("mapped ROI leaves physical frame or has no pixels")
    return left, top, right - left, bottom - top


def _scale_factors(scale_range: tuple[float, float]) -> tuple[float, ...]:
    lower, upper = scale_range
    if lower == upper:
        return (lower,)
    factors = [lower * (upper / lower) ** (index / (MAX_SCALE_VARIANTS - 1))
               for index in range(MAX_SCALE_VARIANTS)]
    factors[0] = lower
    factors[-1] = upper
    if lower < 1 < upper:
        closest = min(range(1, MAX_SCALE_VARIANTS - 1), key=lambda index: abs(factors[index] - 1))
        factors[closest] = 1.0
    return tuple(sorted(set(factors)))


def _round_pixel(value: float) -> int:
    if not math.isfinite(value) or value <= 0:
        raise PackCompileError("template scale is invalid")
    return math.floor(value + 0.5)


def _is_flat_bgr(pixels: bytes, width: int, height: int) -> bool:
    first = pixels[:3]
    return bool(first) and pixels == first * (width * height)


def _integer_tuple(value: object, count: int) -> bool:
    return type(value) is tuple and len(value) == count and all(type(item) is int for item in value)


def _number_tuple(value: object, count: int) -> bool:
    return type(value) is tuple and len(value) == count and all(_finite_number(item) for item in value)


def _finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)
