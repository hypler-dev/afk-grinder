"""Fixed local OCR model provenance; no runtime network access."""

from __future__ import annotations

import hashlib
from pathlib import Path
import stat
import sys

COMMIT = "dabcd4681ac990dc4361de26416d986abd80e4aa"
MODELS = {
    "det.onnx": ("OCR/ppocr_v3/en_us/det.onnx", 2423224,
                 "8fe4bf6abfb20402357827f2efc964c8b28cf980e29fe09a99b742ae29725fa9"),
    "rec.onnx": ("OCR/ppocr_v4/en_us/rec.onnx", 7656612,
                 "af88197ae6ab9f391e59f3f26ad8a6851c1cbbebb91d37834fb7bc21f779a8d7"),
    "keys.txt": ("OCR/ppocr_v4/en_us/keys.txt", 190,
                 "5662df9d2d03f0e8ca0d3b0649d6acbab904b6a14b3d3521463c71c37c668ce3"),
}


def model_directory() -> Path:
    """Return the application-owned bundled directory, never a bridge path."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "afk_grinder" / "ocr_models"
    return Path(__file__).resolve().parents[3] / "local-profiles" / "ocr-en-v4"


def validate_models(directory: Path) -> Path:
    """Verify exact sizes and digests before the optional SDK loads weights."""
    try:
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError()
        for name, (_, size, digest) in MODELS.items():
            path = directory / name
            details = path.lstat()
            if (not stat.S_ISREG(details.st_mode) or details.st_nlink != 1
                    or details.st_size != size or path.is_symlink()
                    or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
                raise ValueError()
    except (OSError, ValueError):
        raise RuntimeError("Pinned local OCR models are unavailable or invalid.") from None
    return directory
