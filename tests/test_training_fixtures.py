"""Safety and decoding tests for explicit local training fixtures."""

from __future__ import annotations

from dataclasses import replace
import hashlib
from io import BytesIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from afk_grinder.training_fixtures import FixtureError, load_fixture
from afk_grinder.training_packet import Example, parse_training_packet
import afk_grinder.training_fixtures as training_fixtures


def image_bytes(format_name: str, *, size: tuple[int, int] = (2, 1), mode: str = "RGB", color=(1, 2, 3), **options: object) -> bytes:
    image = Image.new(mode, size, color)
    stream = BytesIO()
    image.save(stream, format=format_name, **options)
    return stream.getvalue()


def animated_webp() -> bytes:
    first = Image.new("RGB", (2, 1), (255, 0, 0))
    second = Image.new("RGB", (2, 1), (0, 0, 255))
    stream = BytesIO()
    first.save(stream, format="WEBP", save_all=True, append_images=[second], duration=10, loop=0, lossless=True)
    data = stream.getvalue()
    with Image.open(BytesIO(data)) as image:
        if image.n_frames != 2:
            raise AssertionError("test fixture must remain animated")
    return data


def parsed_example(data: bytes, *, extension: str, **changes: object) -> Example:
    payload = {
        "format": "afk-grinder-training",
        "schema_version": 1,
        "status": "draft",
        "id": "fixture-packet",
        "version": "0.1.0",
        "game": {"id": "fixture-game", "title": "Fixture Game", "place_id": None},
        "locale": "en",
        "reference_size": [2, 1],
        "states": [{"id": "gameplay", "kind": "gameplay", "description": "Visible gameplay."}],
        "examples": [{
            "id": "sample-001",
            "path": f"examples/sample-001.{extension}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "width": 2,
            "height": 1,
            "state_id": "gameplay",
            "split": "train",
            "origin": "synthetic",
        }],
        "demonstrations": [],
    }
    payload["examples"][0].update(changes)
    return parse_training_packet(json.dumps(payload)).examples[0]


class TrainingFixtureTests(unittest.TestCase):
    def write(self, root: Path, example: Example, data: bytes) -> None:
        target = root / example.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def test_valid_png_jpeg_and_webp_decode_to_immutable_bgr(self):
        formats = (("png", "PNG"), ("jpg", "JPEG"), ("webp", "WEBP"))
        for extension, format_name in formats:
            with self.subTest(format_name=format_name), tempfile.TemporaryDirectory() as directory:
                data = image_bytes(format_name)
                example = parsed_example(data, extension=extension)
                root = Path(directory)
                self.write(root, example, data)
                fixture = load_fixture(root, example, consent=True)
                self.assertEqual((fixture.width, fixture.height), (2, 1))
                self.assertIsInstance(fixture.pixels, bytes)
                self.assertEqual(len(fixture.pixels), 6)
                if format_name == "PNG":
                    self.assertEqual(fixture.pixels, b"\x03\x02\x01\x03\x02\x01")

    def test_consent_must_be_exactly_true(self):
        data = image_bytes("PNG")
        example = parsed_example(data, extension="png")
        with tempfile.TemporaryDirectory() as directory:
            self.write(Path(directory), example, data)
            for consent in (False, None, 1, "true"):
                with self.subTest(consent=repr(consent)), self.assertRaises(FixtureError):
                    load_fixture(directory, example, consent=consent)  # type: ignore[arg-type]

    def test_forged_metadata_fail_closed(self):
        data = image_bytes("PNG")
        example = parsed_example(data, extension="png")
        forged = (
            replace(example, path="profiles/private.png"),
            replace(example, sha256="A" * 64),
            replace(example, width=True),
            replace(example, state_id="Login"),
            replace(example, split="private"),
            replace(example, origin="replay"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, example, data)
            for value in forged:
                with self.subTest(value=value), self.assertRaises(FixtureError):
                    load_fixture(root, value, consent=True)

    def test_file_links_fail_closed(self):
        data = image_bytes("PNG")
        example = parsed_example(data, extension="png")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, example, data)
            target = root / example.path
            target.unlink()
            external = root / "external.png"
            external.write_bytes(data)
            try:
                target.symlink_to(external)
            except OSError:
                pass
            else:
                with self.assertRaises(FixtureError):
                    load_fixture(root, example, consent=True)
                target.unlink()
            target.hardlink_to(external)
            with self.assertRaises(FixtureError):
                load_fixture(root, example, consent=True)

    def test_hash_size_format_animation_transparency_and_decode_fail(self):
        cases = []
        png = image_bytes("PNG")
        cases.append(("hash", png, parsed_example(png, extension="png"), b"tampered"))
        cases.append(("format", png, parsed_example(png, extension="jpg"), png))
        cases.append(("dimensions", png, parsed_example(png, extension="png", width=1), png))
        malformed = b"not-an-image"
        cases.append(("malformed", malformed, parsed_example(malformed, extension="png"), malformed))
        animated = animated_webp()
        cases.append(("animated", animated, parsed_example(animated, extension="webp"), animated))
        transparent = image_bytes("PNG", mode="RGBA", color=(1, 2, 3, 0))
        cases.append(("transparent", transparent, parsed_example(transparent, extension="png"), transparent))
        for label, digest_data, example, stored in cases:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as directory:
                self.write(Path(directory), example, stored)
                with self.assertRaises(FixtureError):
                    load_fixture(directory, example, consent=True)

        with tempfile.TemporaryDirectory() as directory:
            data = b"x" * (training_fixtures.MAX_ENCODED_BYTES + 1)
            example = parsed_example(data, extension="png")
            self.write(Path(directory), example, data)
            with self.assertRaises(FixtureError):
                load_fixture(directory, example, consent=True)

    def test_late_parent_change_and_tmp_alias_fail_or_preserve_safe_identity(self):
        data = image_bytes("PNG")
        example = parsed_example(data, extension="png")
        if os.name == "posix" and Path("/tmp").is_dir():
            with tempfile.TemporaryDirectory(dir="/tmp") as directory:
                root = Path(directory)
                self.write(root, example, data)
                alias = Path("/tmp") / root.name
                self.assertEqual(load_fixture(alias, example, consent=True).pixels, b"\x03\x02\x01\x03\x02\x01")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write(root, example, data)
            original = training_fixtures._decode_pixels

            def replace_parent(encoded: bytes, selected: Example):
                examples = root / "examples"
                examples.rename(root / "moved-examples")
                examples.mkdir()
                return original(encoded, selected)

            with patch.object(training_fixtures, "_decode_pixels", side_effect=replace_parent), self.assertRaises(FixtureError):
                load_fixture(root, example, consent=True)


if __name__ == "__main__":
    unittest.main()
