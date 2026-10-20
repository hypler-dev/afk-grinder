"""Synthetic checks for the offline recognition state inspector."""

from __future__ import annotations

from dataclasses import replace
import gc
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
import weakref
import zlib

from afk_grinder.models import Target
from afk_grinder.recognition.observation import Layout, Observation, Rect
from afk_grinder.recognition.packs import load_pack
from afk_grinder.recognition.state import StateInspector


def _chunk(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(payload, zlib.crc32(kind)) & 0xFFFFFFFF)


def _png() -> bytes:
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(b"\0\0\0\0")) + _chunk(b"IEND", b""))


def _pack(anchors: dict[str, float], states: list[dict[str, object]]):
    """Load a tiny schema-valid local pack; no game image fixture is used."""
    data = _png()
    asset = {"id": "asset", "path": "assets/anchor.png", "sha256": hashlib.sha256(data).hexdigest()}
    payload = {
        "format": "afk-resource-pack",
        "schema_version": 1,
        "id": "test.pack",
        "version": "0.1.0",
        "min_app_version": "0.1.0",
        "provenance": {"source": "https://example.test/pack", "revision": "a" * 40, "license": "MIT", "attribution": "test"},
        "reference_size": [16, 9],
        "setup": {"language": "en", "instructions": "test", "min_content_size": [16, 9]},
        "assets": [asset] if anchors else [],
        "anchors": [
            {"id": anchor_id, "asset": "asset", "roi": [0, 0, 1, 1], "threshold": threshold, "scale_range": [1, 1]}
            for anchor_id, threshold in anchors.items()
        ],
        "states": states,
        "routines": [],
    }
    directory = tempfile.TemporaryDirectory()
    root = Path(directory.name)
    if anchors:
        (root / "assets").mkdir()
        (root / "assets" / "anchor.png").write_bytes(data)
    (root / "pack.json").write_text(json.dumps(payload), encoding="utf-8")
    try:
        return load_pack(root)
    finally:
        directory.cleanup()


def _state(state_id: str, positive: list[str], exclude: list[str] | None = None, stable_frames: int = 2) -> dict[str, object]:
    return {"id": state_id, "positive": positive, "exclude": exclude or [], "stable_frames": stable_frames}


class StateInspectorTests(unittest.TestCase):
    def setUp(self):
        self.layout = Layout(
            Target(1, "app", "RobloxPlayer", "com.roblox.RobloxPlayer"),
            "window", Rect(0, 0, 16, 9), (16, 9), "monitor", (1, 1),
        )

    def observation(self, sequence: int, captured_at: float | None = None, *, layout=None, generation: int = 1) -> Observation:
        active_layout = self.layout if layout is None else layout
        return Observation(active_layout, sequence / 10 if captured_at is None else captured_at,
                           generation, sequence, bytes(16 * 9 * 3))

    def inspect(self, inspector: StateInspector, sequence: int, scores, **changes):
        observation = self.observation(sequence, **changes)
        return inspector.inspect(observation, scores, now=observation.captured_at + 0.1)

    def test_unique_candidate_requires_declared_consecutive_frames_and_saturates(self):
        inspector = StateInspector(_pack({"a": 0.8}, [_state("ready", ["a"], stable_frames=3)]))
        results = [self.inspect(inspector, sequence, {"a": 0.8}) for sequence in range(1, 5)]
        self.assertEqual([(item.status, item.state_id, item.reason, item.stable_frames) for item in results], [
            ("unknown", None, "unstable", 1),
            ("unknown", None, "unstable", 2),
            ("known", "ready", "stable", 3),
            ("known", "ready", "stable", 3),
        ])

    def test_threshold_and_missing_are_distinct_from_evaluated_negative(self):
        pack = _pack({"a": 0.8, "b": 0.7}, [_state("ready", ["a"], ["b"])])
        self.assertEqual(self.inspect(StateInspector(pack), 1, {"a": 0.79, "b": None}).reason, "no_match")
        self.assertEqual(self.inspect(StateInspector(pack), 1, {"a": 0.8}).reason, "insufficient_evidence")
        self.assertEqual(self.inspect(StateInspector(pack), 1, {"a": 0.8, "b": 0.69}).reason, "unstable")

    def test_irrelevant_missing_evidence_does_not_make_a_ruled_out_state_possible(self):
        inspector = StateInspector(_pack({"a": 0.8, "b": 0.7}, [_state("ready", ["a"], ["b"])]))
        result = self.inspect(inspector, 1, {"a": 0.1})
        self.assertEqual((result.status, result.reason), ("unknown", "no_match"))

    def test_matching_exclusion_blocks_even_when_another_state_matches(self):
        pack = _pack({"a": 0.8, "b": 0.7, "c": 0.6}, [
            _state("unsafe", ["a"], ["b"]), _state("other", ["c"]),
        ])
        result = self.inspect(StateInspector(pack), 1, {"a": 0.8, "b": 0.7, "c": 0.6})
        self.assertEqual((result.status, result.state_id, result.reason, result.stable_frames), ("blocked", None, "excluded", 0))

    def test_multiple_complete_candidates_are_ambiguous(self):
        pack = _pack({"a": 0.8, "b": 0.7}, [_state("one", ["a"]), _state("two", ["b"])])
        result = self.inspect(StateInspector(pack), 1, {"a": 0.8, "b": 0.7})
        self.assertEqual((result.status, result.state_id, result.reason), ("unknown", None, "ambiguous"))

    def test_unknown_and_state_switch_reset_stability(self):
        pack = _pack({"a": 0.8, "b": 0.8}, [_state("one", ["a"]), _state("two", ["b"])])
        inspector = StateInspector(pack)
        self.assertEqual(self.inspect(inspector, 1, {"a": 0.8, "b": 0.1}).stable_frames, 1)
        self.assertEqual(self.inspect(inspector, 2, {"a": True}).reason, "invalid_evidence")
        self.assertEqual(self.inspect(inspector, 3, {"a": 0.8, "b": 0.1}).stable_frames, 1)
        self.assertEqual(self.inspect(inspector, 4, {"a": 0.1, "b": 0.8}).stable_frames, 1)
        result = self.inspect(inspector, 5, {"a": 0.1, "b": 0.8})
        self.assertEqual((result.status, result.state_id), ("known", "two"))

    def test_frame_freshness_and_time_validation_fail_closed(self):
        pack = _pack({"a": 0.8}, [_state("ready", ["a"])])
        cases = [
            (self.observation(1, 1.0), 1.5, "unstable", 1),
            (self.observation(1, 1.0), 1.500001, "stale", 0),
            (self.observation(1, 1.0), 0.5, "future", 0),
            (self.observation(1, 1.0), True, "invalid_time", 0),
        ]
        for observation, now, reason, stable_frames in cases:
            with self.subTest(reason=reason):
                result = StateInspector(pack).inspect(observation, {"a": 0.8}, now=now)
                self.assertEqual((result.status, result.reason, result.stable_frames), ("unknown", reason, stable_frames))

    def test_replay_generation_regression_and_bad_payload_are_out_of_order(self):
        inspector = StateInspector(_pack({"a": 0.8}, [_state("ready", ["a"])]))
        first = self.observation(2, 1.0, generation=2)
        self.assertEqual(inspector.inspect(first, {"a": True}, now=1.1).reason, "invalid_evidence")
        self.assertEqual(inspector.inspect(first, {"a": 0.8}, now=1.1).reason, "out_of_order")
        older_generation = self.observation(3, 1.1, generation=1)
        self.assertEqual(inspector.inspect(older_generation, {"a": 0.8}, now=1.2).reason, "out_of_order")
        nonincreasing_time = self.observation(4, 1.0, generation=3)
        self.assertEqual(inspector.inspect(nonincreasing_time, {"a": 0.8}, now=1.1).reason, "out_of_order")

    def test_layout_change_and_sequence_gap_restart_stability(self):
        pack = _pack({"a": 0.8}, [_state("ready", ["a"])])
        inspector = StateInspector(pack)
        self.assertEqual(self.inspect(inspector, 1, {"a": 0.8}).stable_frames, 1)
        changed = replace(self.layout, monitor_id="other")
        self.assertEqual(self.inspect(inspector, 2, {"a": 0.8}, layout=changed).stable_frames, 1)
        self.assertEqual(self.inspect(inspector, 3, {"a": 0.8}, layout=changed).stable_frames, 2)
        self.assertEqual(self.inspect(inspector, 5, {"a": 0.8}, layout=changed).stable_frames, 1)

    def test_competing_missing_state_blocks_a_unique_candidate_but_negative_allows_it(self):
        pack = _pack({"a": 0.8, "b": 0.8}, [_state("first", ["a"]), _state("other", ["b"])])
        self.assertEqual(self.inspect(StateInspector(pack), 1, {"a": 0.8}).reason, "insufficient_evidence")
        result = self.inspect(StateInspector(pack), 1, {"a": 0.8, "b": 0.1})
        self.assertEqual((result.reason, result.stable_frames), ("unstable", 1))

    def test_generation_change_and_duplicate_after_known_restart_stability(self):
        inspector = StateInspector(_pack({"a": 0.8}, [_state("ready", ["a"])]))
        self.assertEqual(self.inspect(inspector, 1, {"a": 0.8}).stable_frames, 1)
        self.assertEqual(self.inspect(inspector, 2, {"a": 0.8}).status, "known")
        duplicate = self.observation(2)
        self.assertEqual(inspector.inspect(duplicate, {"a": 0.8}, now=0.3).reason, "out_of_order")
        self.assertEqual(self.inspect(inspector, 3, {"a": 0.8}).stable_frames, 1)
        self.assertEqual(self.inspect(inspector, 4, {"a": 0.8}, generation=2).stable_frames, 1)

    def test_unverified_layout_and_invalid_scores_reset_stability(self):
        pack = _pack({"a": 0.8}, [_state("ready", ["a"])])
        unverified = replace(self.layout, region_kind="window-unverified", content_verified=False)
        result = self.inspect(StateInspector(pack), 1, {"a": 0.8}, layout=unverified)
        self.assertEqual((result.status, result.reason), ("unknown", "unverified_layout"))
        cases = [{"a": True}, {"a": float("nan")}, {"a": float("inf")}, {"a": 10 ** 1000},
                 {"a": -0.1}, {"a": 1.1}, {"a": "0.8"}, {"unknown": 0.8}, [("a", 0.8)], None]
        for scores in cases:
            with self.subTest(scores=repr(scores)[:30]):
                result = self.inspect(StateInspector(pack), 1, scores)
                self.assertEqual((result.status, result.reason, result.stable_frames), ("unknown", "invalid_evidence", 0))
        self.assertEqual(self.inspect(StateInspector(pack), 1, {"a": None}).reason, "insufficient_evidence")

    def test_empty_valid_pack_has_no_match_and_observation_is_not_retained(self):
        inspector = StateInspector(_pack({}, []))
        result = self.inspect(inspector, 1, {})
        self.assertEqual((result.status, result.reason), ("unknown", "no_match"))

        observed = self.observation(2)
        reference = weakref.ref(observed)
        inspector.inspect(observed, {}, now=0.3)
        del observed
        gc.collect()
        self.assertIsNone(reference())

    def test_candidate_and_known_paths_retain_neither_observation_nor_pixels(self):
        inspector = StateInspector(_pack({"a": 0.8}, [_state("ready", ["a"])]))
        first_pixels = bytes(16 * 9 * 3)
        second_pixels = bytes(16 * 9 * 3)
        first = Observation(self.layout, 0.1, 1, 1, first_pixels)
        second = Observation(self.layout, 0.2, 1, 2, second_pixels)
        first_reference = weakref.ref(first)
        second_reference = weakref.ref(second)
        first_pixel_references = sys.getrefcount(first_pixels)
        second_pixel_references = sys.getrefcount(second_pixels)
        self.assertEqual(inspector.inspect(first, {"a": 0.8}, now=0.2).reason, "unstable")
        self.assertEqual(inspector.inspect(second, {"a": 0.8}, now=0.3).status, "known")
        self.assertEqual(sys.getrefcount(first_pixels), first_pixel_references)
        self.assertEqual(sys.getrefcount(second_pixels), second_pixel_references)
        del first, second
        gc.collect()
        self.assertIsNone(first_reference())
        self.assertIsNone(second_reference())
        self.assertEqual(sys.getrefcount(first_pixels), first_pixel_references - 1)
        self.assertEqual(sys.getrefcount(second_pixels), second_pixel_references - 1)

    def test_constructor_rejects_non_pack_values(self):
        with self.assertRaises(TypeError):
            StateInspector(object())


if __name__ == "__main__":
    unittest.main()
