"""Create original synthetic fixtures for the read-only pack evaluator.

These images contain no game artwork, screenshots or private data. They test
the compiler and evaluator, not Adopt Me compatibility or live readiness.
"""

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import random
import re
import subprocess

from PIL import Image


def _png(image: Image.Image) -> bytes:
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def generate(destination: Path, source_revision: str) -> tuple[Path, Path, Path]:
    """Create a new demo directory; never overwrite an existing destination."""
    if not re.fullmatch(r"[0-9a-f]{40}", source_revision):
        raise ValueError("Demo provenance requires a source revision.")
    destination.mkdir(mode=0o700)
    pack_root = destination / "pack"
    fixture_root = destination / "fixtures"
    (pack_root / "assets").mkdir(parents=True)
    (fixture_root / "examples").mkdir(parents=True)
    images = {}
    assets = []
    anchors = []
    names = ("gameplay", "transaction", "popup", "unknown")
    for index, name in enumerate(names):
        rng = random.Random(4801 + index)
        image = Image.frombytes("RGB", (16, 16), bytes(rng.randrange(256) for _ in range(16 * 16 * 3)))
        images[name] = image
        encoded = _png(image)
        relative = f"assets/{name}.png"
        (pack_root / relative).write_bytes(encoded)
        assets.append({"id": name, "path": relative, "sha256": hashlib.sha256(encoded).hexdigest()})
        anchors.append({"id": name, "asset": name, "roi": [0, 0, 96, 64], "threshold": 0.97, "scale_range": [0.9, 1.1]})
    states = [
        {"id": "gameplay", "positive": ["gameplay"], "exclude": ["transaction", "popup"], "stable_frames": 2, "kind": "gameplay"},
        *({"id": name, "positive": [name], "exclude": [], "stable_frames": 2, "kind": name} for name in names[1:]),
    ]
    pack = {
        "format": "afk-resource-pack", "schema_version": 1, "id": "example.static-safety", "version": "0.1.0", "min_app_version": "0.2.0",
        "provenance": {"source": "https://github.com/hypler-dev/afk-grinder", "revision": source_revision,
                       "license": "MIT", "attribution": "AFK Grinder contributors; original synthetic test textures."},
        "reference_size": [96, 64], "setup": {"language": "en", "instructions": "Synthetic fixture evaluation only; no game or input.", "min_content_size": [96, 64]},
        "assets": assets, "anchors": anchors, "states": states, "routines": [],
    }
    (pack_root / "pack.json").write_text(json.dumps(pack, indent=2) + "\n", encoding="utf-8")
    cases = [
        ("tuning", "validation", "gameplay", ("gameplay",), (96, 64)),
        ("clear", "held_out", "gameplay", ("gameplay",), (96, 64)),
        ("large", "held_out", "gameplay", ("gameplay",), (144, 96)),
        ("purchase", "held_out", "transaction", ("transaction",), (96, 64)),
        ("notice", "held_out", "popup", ("popup",), (96, 64)),
        ("overlay", "held_out", "transaction", ("gameplay", "transaction"), (96, 64)),
        ("conflict", "held_out", "transaction", ("transaction", "popup"), (96, 64)),
        ("unclassified", "held_out", "unknown", (), (96, 64)),
        ("known-unknown", "held_out", "unknown", ("unknown",), (96, 64)),
        ("small", "held_out", "unknown", (), (48, 32)),
    ]
    examples = []
    for index, (example_id, split, state, visible, size) in enumerate(cases):
        rng = random.Random(8107 + index)
        image = Image.frombytes("RGB", size, bytes(rng.randrange(32) for _ in range(size[0] * size[1] * 3)))
        scale = size[0] / 96
        for ordinal, name in enumerate(visible):
            texture_size = round(16 * scale)
            texture = images[name].resize((texture_size, texture_size), Image.Resampling.LANCZOS)
            image.paste(texture, (round((11 + ordinal * 32) * scale), round((9 + index % 7) * scale)))
        encoded = _png(image)
        relative = f"examples/{example_id}.png"
        (fixture_root / relative).write_bytes(encoded)
        examples.append({"id": example_id, "path": relative, "sha256": hashlib.sha256(encoded).hexdigest(),
                         "width": size[0], "height": size[1], "state_id": state, "split": split, "origin": "synthetic"})
    packet = {
        "format": "afk-grinder-training", "schema_version": 1, "status": "draft", "id": "synthetic-safety", "version": "0.1.0",
        "game": {"id": "synthetic-demo", "title": "Original synthetic recognition demo", "place_id": None},
        "locale": "en", "reference_size": [96, 64],
        "states": [{"id": name, "kind": name, "description": f"Synthetic {name} fixture."} for name in names],
        "examples": examples, "demonstrations": [],
    }
    packet_path = destination / "training.json"
    packet_path.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    return pack_root, packet_path, fixture_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    generate(args.destination, revision)
    print("Original synthetic demo created. Images remain draft test fixtures; no input or capture ran.")


if __name__ == "__main__":
    main()
