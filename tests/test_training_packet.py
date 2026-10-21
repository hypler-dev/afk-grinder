"""Contract tests for data-only local training proposals."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import unittest

from afk_grinder.training_packet import (
    TrainingPacket,
    TrainingPacketError,
    fine_tuning_records,
    parse_training_packet,
    validate_training_packet,
)


def payload() -> dict[str, object]:
    return {
        "format": "afk-grinder-training",
        "schema_version": 1,
        "status": "draft",
        "id": "adopt-me-draft",
        "version": "0.1.0",
        "game": {"id": "adopt-me", "title": "Adopt Me", "place_id": "920587237"},
        "locale": "en",
        "reference_size": [1920, 1080],
        "states": [
            {"id": "gameplay", "kind": "gameplay", "description": "Visible in-game play scene."},
            {"id": "daily-reward-popup", "kind": "popup", "description": "Visible daily reward overlay."},
            {"id": "trade-window", "kind": "transaction", "description": "Trade interface is blocked."},
            {"id": "unknown-overlay", "kind": "unknown", "description": "Unrecognized overlay blocks actions."},
        ],
        "examples": [
            {"id": "gameplay-001", "path": "examples/gameplay-001.webp", "sha256": "a" * 64, "width": 1920, "height": 1080, "state_id": "gameplay", "split": "train", "origin": "synthetic"},
            {"id": "reward-001", "path": "examples/reward-001.webp", "sha256": "b" * 64, "width": 1920, "height": 1080, "state_id": "daily-reward-popup", "split": "validation", "origin": "manual"},
            {"id": "gameplay-002", "path": "examples/gameplay-002.webp", "sha256": "c" * 64, "width": 1920, "height": 1080, "state_id": "gameplay", "split": "held_out", "origin": "manual"},
        ],
        "demonstrations": [
            {"id": "reward-overlay-review", "from_state": "gameplay", "to_state": "daily-reward-popup", "capability_request": "review-daily-reward", "example_ids": ["gameplay-001", "reward-001"], "max_duration_ms": 5000, "retry_limit": 1},
        ],
    }


class TrainingPacketTests(unittest.TestCase):
    def parse(self, value: dict[str, object] | None = None):
        return parse_training_packet(json.dumps(payload() if value is None else value))

    def test_valid_packet_is_immutable_draft_and_export_is_text_only(self):
        packet = self.parse()
        self.assertEqual(packet.status, "draft")
        self.assertEqual(packet.examples[0].path, "examples/gameplay-001.webp")
        with self.assertRaises(FrozenInstanceError):
            packet.id = "changed"
        with self.assertRaises(TrainingPacketError):
            fine_tuning_records(packet)
        with self.assertRaises(TrainingPacketError):
            fine_tuning_records(replace(packet, status="approved"), consent=True)

        private_path = replace(packet, examples=(replace(packet.examples[0], path="/private/replay.webp"), *packet.examples[1:]))
        held_out_as_train = replace(packet, examples=(*packet.examples[:2], replace(packet.examples[2], split="train")))
        direct_constructor = TrainingPacket(
            packet.id,
            packet.version,
            packet.game,
            packet.locale,
            packet.reference_size,
            packet.states,
            packet.examples,
            packet.demonstrations,
        )
        for forged in (private_path, held_out_as_train, direct_constructor):
            with self.subTest(forged=type(forged).__name__):
                with self.assertRaises(TrainingPacketError):
                    fine_tuning_records(forged, consent=True)

        records = fine_tuning_records(packet, consent=True)
        self.assertEqual(len(records), 2)
        decoded = [json.loads(record) for record in records]
        self.assertEqual({record["split"] for record in decoded}, {"train", "validation"})
        self.assertTrue(all("held_out" not in record for record in records))
        self.assertTrue(all(set(record["image_ref"]) == {"path", "sha256", "width", "height"} for record in decoded))

    def test_checked_in_synthetic_metadata_does_not_load_an_asset(self):
        sample = Path("examples/training/adopt-me-draft.json").read_text(encoding="utf-8")
        packet = parse_training_packet(sample)
        self.assertEqual(packet.status, "draft")
        self.assertEqual(packet.examples[0].origin, "synthetic")
        self.assertFalse(Path(packet.examples[0].path).exists())

    def test_json_safety_rejects_duplicate_nonfinite_deep_and_unknown_data(self):
        cases = (
            '{"format":"afk-grinder-training","format":"afk-grinder-training"}',
            '{"value":NaN}',
            "[" * 13 + "0" + "]" * 13,
        )
        for text in cases:
            with self.subTest(text=text[:24]):
                with self.assertRaises(TrainingPacketError):
                    parse_training_packet(text)

        invalid = payload()
        invalid["surprise"] = True
        with self.assertRaises(TrainingPacketError):
            self.parse(invalid)

    def test_status_numeric_and_login_values_fail_closed(self):
        invalid = payload()
        invalid["status"] = "approved"
        with self.assertRaises(TrainingPacketError):
            self.parse(invalid)

        invalid = payload()
        invalid["reference_size"] = [True, 1080]
        with self.assertRaises(TrainingPacketError):
            self.parse(invalid)

        invalid = payload()
        invalid["states"][0]["description"] = "Login screen visible."
        with self.assertRaises(TrainingPacketError):
            self.parse(invalid)

        invalid = payload()
        invalid["states"][0]["description"] = "Sign in screen visible."
        with self.assertRaises(TrainingPacketError):
            self.parse(invalid)

    def test_paths_hash_splits_and_references_are_strict(self):
        invalid = payload()
        invalid["examples"][0]["path"] = "examples/../gameplay-001.webp"
        with self.assertRaises(TrainingPacketError):
            self.parse(invalid)

        invalid = payload()
        invalid["examples"][1]["sha256"] = "a" * 64
        with self.assertRaises(TrainingPacketError):
            self.parse(invalid)

        invalid = payload()
        invalid["demonstrations"][0]["example_ids"] = ["missing"]
        with self.assertRaises(TrainingPacketError):
            self.parse(invalid)

    def test_transaction_unknown_and_executable_requests_cannot_be_demonstrated(self):
        for state_id, request in (("trade-window", "review-trade"), ("unknown-overlay", "review-overlay"), ("gameplay", "press-key")):
            with self.subTest(state_id=state_id, request=request):
                invalid = payload()
                invalid["demonstrations"][0]["from_state"] = state_id
                invalid["demonstrations"][0]["capability_request"] = request
                with self.assertRaises(TrainingPacketError):
                    self.parse(invalid)

    def test_sealed_packet_revalidation_rejects_tampering_and_unsealed_construction(self):
        packet = self.parse()
        validated = validate_training_packet(packet)
        self.assertEqual(validated, packet)
        self.assertIsNot(validated, packet)

        forged = TrainingPacket(
            packet.id,
            packet.version,
            packet.game,
            packet.locale,
            packet.reference_size,
            packet.states,
            packet.examples,
            packet.demonstrations,
        )
        changed = replace(packet, examples=(replace(packet.examples[0], split="held_out"), *packet.examples[1:]))
        object.__setattr__(packet, "examples", (replace(packet.examples[0], path="examples/other.webp"), *packet.examples[1:]))
        for candidate in (forged, changed, packet):
            with self.subTest(candidate=type(candidate).__name__), self.assertRaises(TrainingPacketError):
                validate_training_packet(candidate)


if __name__ == "__main__":
    unittest.main()
