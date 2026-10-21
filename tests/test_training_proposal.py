"""Pure in-memory proof for training draft crop candidates."""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import struct
import unittest

from PIL import Image

from afk_grinder.recognition.training_proposal import (
    Candidate, ProposalError, build_candidate, selected_train_ids, validate_candidate,
)
from afk_grinder.training_fixtures import FixturePixels
from afk_grinder.training_packet import parse_training_packet


def packet_payload(*, kind: str = "gameplay") -> dict[str, object]:
    return {
        "format": "afk-grinder-training", "schema_version": 1, "status": "draft",
        "id": "draft", "version": "0.1.0",
        "game": {"id": "test-game", "title": "Test Game", "place_id": None}, "locale": "en",
        "reference_size": [100, 50],
        "states": [{"id": "screen", "kind": kind, "description": "Visible screen."}],
        "examples": [
            {"id": "train-a", "path": "examples/train-a.png", "sha256": "a" * 64, "width": 100, "height": 50, "state_id": "screen", "split": "train", "origin": "synthetic"},
            {"id": "held-a", "path": "examples/held-a.png", "sha256": "b" * 64, "width": 100, "height": 50, "state_id": "screen", "split": "held_out", "origin": "synthetic"},
        ], "demonstrations": [],
    }


def recipe_payload(*, example_id: str = "train-a") -> dict[str, object]:
    return {
        "format": "afk-training-pack-recipe", "schema_version": 1,
        "pack_id": "test.candidate", "pack_version": "0.1.0",
        "provenance": {"source": "https://example.test/source", "revision": "a" * 40, "license": "MIT", "attribution": "Synthetic"},
        "setup": {"instructions": "Synthetic only.", "min_content_size": [80, 40]},
        "anchors": [{"id": "screen.anchor", "example_id": example_id, "crop": [20, 20, 20, 20], "roi": [10, 5, 80, 40], "threshold": 0.8, "scale_range": [1, 1]}],
        "states": [{"id": "screen", "positive": ["screen.anchor"], "exclude": [], "stable_frames": 2}],
    }


def pixels() -> FixturePixels:
    data = bytearray()
    for y in range(50):
        for x in range(100):
            data.extend(((x * 3) % 256, (y * 5) % 256, (x + y) % 256))
    return FixturePixels(100, 50, bytes(data))


class TrainingProposalTests(unittest.TestCase):
    def packet(self, *, kind: str = "gameplay"):
        return parse_training_packet(json.dumps(packet_payload(kind=kind)))

    def recipe(self, **changes: object) -> str:
        value = recipe_payload(**changes)
        return json.dumps(value)

    def candidate(self, *, kind: str = "gameplay") -> Candidate:
        return build_candidate(self.packet(kind=kind), self.recipe(), {"train-a": pixels()}, consent=True)

    def test_crop_roundtrip_pixel_placement_and_no_metadata(self):
        candidate = self.candidate()
        self.assertEqual(selected_train_ids(self.packet(), self.recipe()), ("train-a",))
        asset = candidate.assets[0]
        self.assertEqual((asset.id, asset.path), ("screen.anchor", "assets/screen.anchor.png"))
        self.assertNotIn(b"tEXt", asset.data)
        self.assertNotIn(b"iTXt", asset.data)
        with Image.open(BytesIO(asset.data)) as image:
            self.assertEqual((image.mode, image.size), ("RGB", (20, 20)))
            # Fixture BGR at source (20, 20) becomes RGB at crop origin.
            self.assertEqual(image.getpixel((0, 0)), (40, 100, 60))
        again = self.candidate()
        self.assertEqual(candidate.manifest, again.manifest)
        self.assertEqual(candidate.assets[0].data, again.assets[0].data)
        self.assertEqual(candidate.pack.states[0].kind, "gameplay")

    def test_protected_kind_and_train_only_selection_are_preserved(self):
        self.assertEqual(self.candidate(kind="transaction").pack.states[0].kind, "transaction")
        held = self.recipe(example_id="held-a")
        with self.assertRaises(ProposalError):
            selected_train_ids(self.packet(), held)
        with self.assertRaises(ProposalError):
            build_candidate(self.packet(), held, {"held-a": pixels()}, consent=True)

    def test_consent_fails_before_packet_recipe_or_fixture_work(self):
        with self.assertRaises(ProposalError):
            build_candidate(object(), object(), object(), consent=False)  # type: ignore[arg-type]

    def test_malformed_recipe_geometry_provenance_and_source_aspect_fail_closed(self):
        mutations = []
        bad = recipe_payload()
        bad["unknown"] = True
        mutations.append(bad)
        bad = recipe_payload()
        bad["anchors"][0]["crop"] = [0, 0, True, 20]
        mutations.append(bad)
        bad = recipe_payload()
        bad["anchors"][0]["roi"] = [90, 0, 11, 5]
        mutations.append(bad)
        bad = recipe_payload()
        bad["provenance"]["source"] = "http://example.test"
        mutations.append(bad)
        bad = recipe_payload()
        bad["states"][0]["positive"] = []
        mutations.append(bad)
        for value in mutations:
            with self.subTest(value=value), self.assertRaises(ProposalError):
                build_candidate(self.packet(), json.dumps(value), {"train-a": pixels()}, consent=True)
        wrong_aspect = packet_payload()
        wrong_aspect["examples"][0]["width"] = 199
        packet = parse_training_packet(json.dumps(wrong_aspect))
        with self.assertRaises(ProposalError):
            build_candidate(packet, self.recipe(), {"train-a": FixturePixels(199, 100, b"\0" * (199 * 100 * 3))}, consent=True)

    def test_forged_fixture_and_candidate_are_rejected(self):
        packet = self.packet()
        with self.assertRaises(ProposalError):
            build_candidate(packet, self.recipe(), {"train-a": FixturePixels(100, 50, b"bad")}, consent=True)
        candidate = self.candidate()
        forged_asset = replace(candidate.assets[0], data=candidate.assets[0].data + b"x")
        with self.assertRaises(ProposalError):
            validate_candidate(packet, self.recipe(), candidate.manifest, (forged_asset,))
        metadata = candidate.assets[0].data[:-12]
        chunk = b"tEXt" + b"note\0private"
        metadata += struct.pack(">I", len(chunk) - 4) + chunk
        metadata += struct.pack(">I", __import__("zlib").crc32(chunk) & 0xffffffff) + candidate.assets[0].data[-12:]
        forged = replace(candidate.assets[0], data=metadata, sha256=sha256(metadata).hexdigest())
        manifest = json.loads(candidate.manifest)
        manifest["assets"][0]["sha256"] = forged.sha256
        changed = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        with self.assertRaises(ProposalError):
            validate_candidate(packet, self.recipe(), changed, (forged,))

    def test_caps_revalidate_sealed_packet_and_compile_work_limits(self):
        packet = self.packet()
        with self.assertRaises(ProposalError):
            selected_train_ids(replace(packet, version="9.9.9"), self.recipe())
        oversized = recipe_payload()
        oversized["anchors"] = oversized["anchors"] * 17
        with self.assertRaises(ProposalError):
            build_candidate(packet, json.dumps(oversized), {"train-a": pixels()}, consent=True)
        search = recipe_payload()
        search["anchors"][0]["scale_range"] = [0.5, 2]
        search["anchors"][0]["roi"] = [0, 0, 100, 50]
        # Existing compiler bounds still run at reference size.
        self.assertIsNotNone(build_candidate(packet, json.dumps(search), {"train-a": pixels()}, consent=True).pack)


if __name__ == "__main__":
    unittest.main()
