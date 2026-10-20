"""Synthetic-only tests for local replay storage."""

from __future__ import annotations

from pathlib import Path
import os
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from afk_grinder.models import Target
from afk_grinder.recognition.observation import Layout, Observation, Rect
from afk_grinder.replay import ReplayError, ReplayFrame, ReplaySettings, ReplayStore


SESSION = "0123456789abcdef0123456789abcdef"


class Clock:
    def __init__(self) -> None:
        self.monotonic = 100.0
        self.utc = 1_000_000.0

    def tick(self, seconds: float) -> None:
        self.monotonic += seconds
        self.utc += seconds


def observation(width: int = 640, height: int = 360) -> Observation:
    layout = Layout(
        Target(1, "window", "RobloxPlayer", "com.roblox.RobloxPlayer"),
        "window",
        Rect(0, 0, width, height),
        (width, height),
        "monitor",
        (1, 1),
    )
    pixels = bytes((index % 251 for index in range(width * height * 3)))
    return Observation(layout, 1.0, 1, 1, pixels)


class ReplayStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "replays"
        self.clock = Clock()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def store(self, settings: ReplaySettings = ReplaySettings(enabled=True)) -> ReplayStore:
        return ReplayStore(
            self.root,
            settings,
            monotonic_clock=lambda: self.clock.monotonic,
            utc_clock=lambda: self.clock.utc,
        )

    def test_webp_is_low_resolution_aspect_preserving_and_metadata_free(self) -> None:
        store = self.store(ReplaySettings(enabled=True, max_width=320))

        entry = store.record(observation(640, 360), SESSION, "gameplay")

        self.assertEqual((entry.width, entry.height), (320, 180))
        mime, payload = store.get_frame(entry.frame_id)
        self.assertEqual(mime, "image/webp")
        with Image.open(__import__("io").BytesIO(payload)) as image:
            self.assertEqual(image.size, (320, 180))
            self.assertFalse(image.getexif())
            self.assertNotIn("icc_profile", image.info)

    def test_jpeg_never_upscales_and_has_no_exif(self) -> None:
        store = self.store(ReplaySettings(enabled=True, image_format="jpeg", max_width=960))

        entry = store.record(observation(400, 225), SESSION, "gameplay")

        self.assertEqual((entry.width, entry.height), (400, 225))
        mime, payload = store.get_frame(entry.frame_id)
        self.assertEqual(mime, "image/jpeg")
        with Image.open(__import__("io").BytesIO(payload)) as image:
            self.assertEqual(image.size, (400, 225))
            self.assertFalse(image.getexif())

    def test_login_unknown_and_restricted_never_copy_source_pixels_into_encoder(self):
        for state in ("redacted_login", "redacted_unknown", "redacted_restricted"):
            with self.subTest(state=state):
                store = self.store()
                with patch("afk_grinder.replay.Image.frombytes", side_effect=AssertionError("Source must not enter encoder")):
                    entry = store.record(observation(8, 8), SESSION, state)
                _, payload = store.get_frame(entry.frame_id)
                with Image.open(__import__("io").BytesIO(payload)) as image:
                    self.assertEqual(len(set(image.get_flattened_data())), 1)
                    self.assertFalse(image.getexif())
                self.clock.tick(2)

    def test_purchase_and_trade_are_blurred_before_any_encoded_file(self):
        store = self.store()
        original = observation(640, 360)
        entry = store.record(original, SESSION, "redacted_purchase")
        _, payload = store.get_frame(entry.frame_id)
        with Image.open(__import__("io").BytesIO(payload)) as image:
            restored = image.convert("RGB").tobytes()
            self.assertNotEqual(restored, original.pixels)
            self.assertLess(len(set(image.get_flattened_data())), 2000)
            self.assertFalse(image.getexif())

    def test_default_off_and_blocked_states_never_create_storage(self) -> None:
        store = self.store(ReplaySettings())
        self.assertIsNone(store.record(observation(), SESSION, "gameplay"))
        self.assertFalse(self.root.exists())

        enabled = self.store()
        for state in ("unknown", "login", "transaction"):
            with self.subTest(state=state):
                self.assertIsNone(enabled.record(observation(), SESSION, state))
        self.assertFalse(self.root.exists())

    def test_interval_and_disable_prevent_future_writes(self) -> None:
        store = self.store()
        first = store.record(observation(), SESSION, "gameplay")
        self.assertIsNone(store.record(observation(), SESSION, "gameplay"))
        self.clock.tick(2)
        self.assertIsNotNone(store.record(observation(), SESSION, "gameplay"))
        store.update_settings(ReplaySettings(enabled=False))
        self.clock.tick(2)
        self.assertIsNone(store.record(observation(), SESSION, "gameplay"))
        self.assertEqual(len(store.list_frames()), 2)
        self.assertIsNotNone(first)

    def test_retention_shrink_and_expired_get(self) -> None:
        store = self.store(ReplaySettings(enabled=True, retention_days=7))
        first = store.record(observation(), SESSION, "gameplay")
        self.clock.tick(2 * 24 * 60 * 60)
        store.update_settings(ReplaySettings(enabled=True, retention_days=1))

        self.assertEqual(store.list_frames(), ())
        with self.assertRaisesRegex(ReplayError, "unavailable"):
            store.get_frame(first.frame_id)

    def test_disk_cap_removes_oldest_indexed_frame(self) -> None:
        store = self.store(ReplaySettings(enabled=True, max_bytes=100 * 1024 * 1024))
        first = store.record(observation(), SESSION, "gameplay")
        old = ReplayFrame(
            frame_id="fedcba9876543210fedcba9876543210",
            session_id=SESSION,
            recorded_at=self.clock.utc - 1,
            width=1,
            height=1,
            image_format="webp",
            event="frame",
            state="gameplay",
        )
        old_path = self.root / "frames" / f"{old.frame_id}.webp"
        with old_path.open("wb") as stream:
            stream.truncate(100 * 1024 * 1024)
        with store._database() as db:
            store._insert(db, old, old_path.stat().st_size)
        store.purge()

        self.assertEqual(store.list_frames(), (first,))
        self.assertFalse(old_path.exists())

    def test_bad_ids_symlinks_hardlinks_and_atomic_failure_fail_closed(self) -> None:
        store = self.store()
        with self.assertRaises(ValueError):
            store.record(observation(), "../bad", "gameplay")
        entry = store.record(observation(), SESSION, "gameplay")
        index = self.root / "index.sqlite3"
        linked = self.root / "index-link.json"
        os.link(index, linked)
        with self.assertRaisesRegex(ReplayError, "unsafe"):
            store.list_frames()
        linked.unlink()

        frame = self.root / "frames" / f"{entry.frame_id}.webp"
        frame.unlink()
        os.link(index, frame)
        with self.assertRaisesRegex(ReplayError, "unsafe"):
            store.get_frame(entry.frame_id)
        frame.unlink()
        frame.symlink_to(index)
        with self.assertRaisesRegex(ReplayError, "unsafe"):
            store.get_frame(entry.frame_id)

        fresh_root = Path(self.temporary.name) / "fresh"
        fresh = ReplayStore(fresh_root, ReplaySettings(enabled=True), monotonic_clock=lambda: self.clock.monotonic,
                            utc_clock=lambda: self.clock.utc)
        with patch.object(fresh, "_insert", side_effect=ReplayError("Replay index update failed.")):
            with self.assertRaisesRegex(ReplayError, "index update failed"):
                fresh.record(observation(), SESSION, "gameplay")
        self.assertEqual(list((fresh_root / "frames").iterdir()), [])

    def test_corrupt_stored_image_fails_closed(self) -> None:
        store = self.store()
        entry = store.record(observation(), SESSION, "gameplay")
        path = self.root / "frames" / f"{entry.frame_id}.webp"
        path.write_bytes(b"not an image")

        with self.assertRaisesRegex(ReplayError, "invalid"):
            store.get_frame(entry.frame_id)

    def test_settings_are_strict_and_stats_stay_bounded(self) -> None:
        for changes in ({"enabled": 1}, {"retention_days": True}, {"max_width": 319},
                        {"quality": 86}, {"interval_seconds": 0}, {"max_bytes": float(100 * 1024 * 1024)}):
            with self.subTest(changes=changes):
                with self.assertRaises(ValueError):
                    ReplaySettings(**changes)
        store = self.store()
        self.assertEqual(store.stats().frame_count, 0)
        self.assertFalse(self.root.exists())

    def test_more_than_4096_frames_are_retained_and_old_frame_remains_readable(self):
        store = self.store()
        first = store.record(observation(8, 8), SESSION, "gameplay")
        mime, encoded = store.get_frame(first.frame_id)
        with store._database() as db:
            for index in range(4096):
                frame = ReplayFrame(f"{index:032x}", SESSION, self.clock.utc + 2 + index * 2,
                                    8, 8, "webp", "frame", "gameplay")
                store._atomic_write(store._frame_path(frame), encoded)
                store._insert(db, frame, len(encoded))
        self.clock.tick(8194)
        self.assertEqual(store.purge().frame_count, 4097)
        self.assertEqual(len(store.list_frames()), 4096)
        self.assertEqual(store.get_frame(first.frame_id), (mime, encoded))
        self.assertEqual(store.session_summaries()[0]["frame_count"], 4097)
        newest = store.list_frames()
        older = store.list_frames(before=(newest[0].recorded_at, newest[0].frame_id))
        self.assertEqual(older, (first,))
        self.assertFalse({item.frame_id for item in newest} & {item.frame_id for item in older})

    def test_cursor_ties_and_session_pages_have_no_missing_or_duplicate_rows(self):
        store = self.store()
        first = store.record(observation(8, 8), SESSION, "gameplay")
        _, encoded = store.get_frame(first.frame_id)
        with store._database() as db:
            for index in range(101):
                frame = ReplayFrame(f"{index:032x}", f"{index:032x}", self.clock.utc,
                                    8, 8, "webp", "frame", "gameplay")
                store._atomic_write(store._frame_path(frame), encoded)
                store._insert(db, frame, len(encoded))
        seen, cursor = [], None
        while page := store.list_frames(limit=7, before=cursor):
            seen.extend(item.frame_id for item in page)
            cursor = (page[0].recorded_at, page[0].frame_id)
        self.assertEqual(len(seen), 102)
        self.assertEqual(len(set(seen)), 102)
        sessions = store.session_summaries()
        older = store.session_summaries(before=(sessions[-1]["started_at"], sessions[-1]["id"]))
        self.assertEqual(len(sessions) + len(older), 102)
        self.assertFalse({item["id"] for item in sessions} & {item["id"] for item in older})

    def test_disk_stats_include_index_and_preferences(self):
        store = self.store()
        entry = store.record(observation(8, 8), SESSION, "gameplay")
        store.save_settings()
        actual = sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())
        self.assertEqual(store.stats().byte_count, actual)
        self.assertGreater(actual, store._frame_path(entry).stat().st_size)

    def test_preferences_survive_restart_and_failed_save_never_purges_history(self):
        store = self.store(ReplaySettings(enabled=True, retention_days=365))
        first = store.record(observation(8, 8), SESSION, "gameplay")
        store.save_settings()
        self.clock.tick(8 * 86400)
        restarted = self.store(ReplaySettings())
        self.assertEqual(restarted.restore_settings().retention_days, 365)
        self.assertEqual(restarted.stats().frame_count, 1)
        with patch.object(restarted, "save_settings", side_effect=ReplayError("Replay write failed.")):
            with self.assertRaises(ReplayError):
                restarted.update_settings(ReplaySettings(enabled=True, retention_days=1))
        self.assertEqual(restarted.settings.retention_days, 365)
        self.assertIsNotNone(restarted.get_frame(first.frame_id))
