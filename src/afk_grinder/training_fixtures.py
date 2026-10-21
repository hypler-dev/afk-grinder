"""Consent-gated, single-file loader for local training fixtures.

This module is deliberately separate from training-packet parsing and runtime
recognition.  It reads only the exact canonical path named by one validated
example, never searches a dataset directory, and returns in-memory BGR pixels.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from io import BytesIO
from pathlib import Path
import stat
from typing import Final
import warnings

from PIL import Image, UnidentifiedImageError

from . import training_packet
from .recognition import packs


MAX_ENCODED_BYTES: Final = 8 * 1024 * 1024
MAX_IMAGE_PIXELS: Final = 16_000_000
_PIL_FORMATS: Final = ("PNG", "JPEG", "WEBP")
_FORMAT_BY_EXTENSION: Final = {"png": "PNG", "jpg": "JPEG", "webp": "WEBP"}


class FixtureError(ValueError):
    """Raised when a selected fixture cannot be safely loaded."""


@dataclass(frozen=True, slots=True)
class FixturePixels:
    """One decoded RGB-source image expressed as immutable BGR bytes."""

    width: int
    height: int
    pixels: bytes


@dataclass(frozen=True, slots=True)
class _Lineage:
    paths: tuple[Path, ...]
    identities: tuple[tuple[int, int], ...]


def load_fixture(
    directory: Path | str,
    example: training_packet.Example,
    *,
    consent: bool = False,
) -> FixturePixels:
    """Load one explicit, consented fixture after strict metadata verification.

    The caller selects the dataset directory and one training-packet example.
    This function never discovers fixtures, reads replay/profile paths, or
    persists decoded pixels.
    """
    if consent is not True:
        raise FixtureError("explicit fixture consent is required")
    canonical = _validated_example(example)
    if not isinstance(directory, (str, Path)):
        raise FixtureError("fixture directory is invalid")

    try:
        root = packs._open_root(directory, None)
    except (OSError, TypeError, ValueError, packs.PackError) as exc:
        raise FixtureError("fixture directory is unavailable") from exc

    try:
        lineage = _capture_lineage(root.path, canonical.path)
        encoded = packs._read_regular(root, canonical.path, MAX_ENCODED_BYTES)
        _ensure_lineage_unchanged(lineage)
        if hashlib.sha256(encoded).hexdigest() != canonical.sha256:
            raise FixtureError("fixture hash mismatch")
        pixels = _decode_pixels(encoded, canonical)
        packs._ensure_root_unchanged(root)
        _ensure_lineage_unchanged(lineage)
        return pixels
    except FixtureError:
        raise
    except (OSError, ValueError, packs.PackError) as exc:
        raise FixtureError("fixture could not be read") from exc
    finally:
        root.close()


def _validated_example(example: training_packet.Example) -> training_packet.Example:
    """Re-run parser rules because frozen dataclasses can still be forged."""
    if type(example) is not training_packet.Example:
        raise FixtureError("fixture example has an invalid type")
    try:
        training_packet._slug(example.state_id, "fixture state id")
    except (TypeError, ValueError, training_packet.TrainingPacketError) as exc:
        raise FixtureError("fixture example is invalid") from exc
    payload = {
        "id": example.id,
        "path": example.path,
        "sha256": example.sha256,
        "width": example.width,
        "height": example.height,
        "state_id": example.state_id,
        "split": example.split,
        "origin": example.origin,
    }
    try:
        return training_packet._validate_examples([payload], {example.state_id})[0]
    except (AttributeError, TypeError, ValueError, training_packet.TrainingPacketError) as exc:
        raise FixtureError("fixture example is invalid") from exc


def _capture_lineage(root_path: Path, relative: str) -> _Lineage:
    """Snapshot resolved root ancestry without rejecting legitimate /tmp aliases."""
    try:
        resolved_root = root_path.resolve(strict=True)
    except OSError as exc:
        raise FixtureError("fixture directory is unavailable") from exc
    paths: list[Path] = []
    identities: list[tuple[int, int]] = []
    current = resolved_root
    while True:
        try:
            info = current.lstat()
        except OSError as exc:
            raise FixtureError("fixture directory is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise FixtureError("fixture directory is invalid")
        paths.append(current)
        identities.append((info.st_dev, info.st_ino))
        if current.parent == current:
            break
        current = current.parent
    selected_parent = resolved_root
    for component in Path(relative).parts[:-1]:
        selected_parent = selected_parent / component
        try:
            info = selected_parent.lstat()
        except OSError as exc:
            raise FixtureError("fixture directory is unavailable") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise FixtureError("fixture directory is invalid")
        paths.append(selected_parent)
        identities.append((info.st_dev, info.st_ino))
    return _Lineage(tuple(paths), tuple(identities))


def _ensure_lineage_unchanged(lineage: _Lineage) -> None:
    for path, identity in zip(lineage.paths, lineage.identities, strict=True):
        try:
            info = path.lstat()
        except OSError as exc:
            raise FixtureError("fixture directory changed during load") from exc
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != identity:
            raise FixtureError("fixture directory changed during load")


def _decode_pixels(encoded: bytes, example: training_packet.Example) -> FixturePixels:
    expected_format = _FORMAT_BY_EXTENSION[example.path.rsplit(".", 1)[1]]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(encoded), formats=_PIL_FORMATS) as probe:
                _validate_image_header(probe, example, expected_format)
                probe.verify()
            with Image.open(BytesIO(encoded), formats=_PIL_FORMATS) as image:
                _validate_image_header(image, example, expected_format)
                image.load()
                _reject_transparency(image)
                rgb = image.convert("RGB")
                return FixturePixels(example.width, example.height, _rgb_to_bgr(rgb.tobytes()))
    except (Image.DecompressionBombError, Image.DecompressionBombWarning, MemoryError, OSError, SyntaxError, TypeError, UnidentifiedImageError, ValueError) as exc:
        raise FixtureError("fixture image is invalid") from exc


def _validate_image_header(image: Image.Image, example: training_packet.Example, expected_format: str) -> None:
    if image.format != expected_format:
        raise FixtureError("fixture format does not match metadata")
    width, height = image.size
    if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
        raise FixtureError("fixture image exceeds pixel limit")
    if (width, height) != (example.width, example.height):
        raise FixtureError("fixture dimensions do not match metadata")
    if getattr(image, "is_animated", False) or getattr(image, "n_frames", 1) != 1:
        raise FixtureError("animated fixtures are unsupported")


def _reject_transparency(image: Image.Image) -> None:
    if image.mode not in {"RGBA", "LA", "PA"} and "transparency" not in image.info:
        return
    alpha = image.convert("RGBA").getchannel("A")
    if alpha.getextrema() != (255, 255):
        raise FixtureError("transparent fixtures are unsupported")


def _rgb_to_bgr(rgb: bytes) -> bytes:
    bgr = bytearray(len(rgb))
    bgr[0::3] = rgb[2::3]
    bgr[1::3] = rgb[1::3]
    bgr[2::3] = rgb[0::3]
    return bytes(bgr)
