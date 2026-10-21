"""Add original train images and a crop recipe to the synthetic fixture demo."""

import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import random
import subprocess

from PIL import Image

from tools.make_fixture_demo import generate as generate_fixture_demo


def generate(destination: Path, source_revision: str) -> tuple[Path, Path, Path]:
    """Create an entirely synthetic local compiler/evaluator example."""
    pack_root, packet_path, fixture_root = generate_fixture_demo(destination, source_revision)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    pack = json.loads((pack_root / "pack.json").read_text(encoding="utf-8"))
    anchors = []
    for index, state in enumerate(packet["states"]):
        name = state["id"]
        rng = random.Random(324091 + index)
        size = tuple(packet["reference_size"])
        image = Image.frombytes("RGB", size, bytes(rng.randrange(32) for _ in range(size[0] * size[1] * 3)))
        with Image.open(pack_root / f"assets/{name}.png") as texture:
            image.paste(texture.convert("RGB"), (11, 9))
        stream = BytesIO()
        image.save(stream, format="PNG")
        encoded = stream.getvalue()
        identifier = f"train-{name}"
        relative = f"examples/{identifier}.png"
        (fixture_root / relative).write_bytes(encoded)
        packet["examples"].append({
            "id": identifier, "path": relative, "sha256": hashlib.sha256(encoded).hexdigest(),
            "width": size[0], "height": size[1], "state_id": name, "split": "train", "origin": "synthetic",
        })
        anchors.append({
            "id": name, "example_id": identifier, "crop": [11, 9, 16, 16],
            "roi": [0, 0, *size], "threshold": 0.97, "scale_range": [0.9, 1.1],
        })
    recipe = {
        "format": "afk-training-pack-recipe", "schema_version": 1,
        "pack_id": "example.compiled-training", "pack_version": "0.1.0",
        "provenance": pack["provenance"],
        "setup": {"instructions": "Original synthetic draft only; never a game routine.", "min_content_size": [96, 64]},
        "anchors": anchors,
        "states": [{key: value for key, value in state.items() if key != "kind"} for state in pack["states"]],
    }
    packet_path.write_text(json.dumps(packet, indent=2) + "\n", encoding="utf-8")
    recipe_path = destination / "recipe.json"
    recipe_path.write_text(json.dumps(recipe, indent=2) + "\n", encoding="utf-8")
    return packet_path, recipe_path, fixture_root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    revision = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    generate(args.destination, revision)
    print("Original synthetic train/held-out demo created. No game content, capture or input.")


if __name__ == "__main__":
    main()
