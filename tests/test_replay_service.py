"""Synthetic queue tests for replay service; no images, capture, or native I/O."""

from __future__ import annotations

from pathlib import Path
import tempfile
import threading
import time
import unittest

from afk_grinder.models import Target
from afk_grinder.recognition.observation import Layout, Observation, Rect
from afk_grinder.replay import ReplayFrame, ReplaySettings, ReplayStats
from afk_grinder.replay_service import ReplayService


SESSION = "0123456789abcdef0123456789abcdef"
FRAME = "fedcba9876543210fedcba9876543210"


def observation() -> Observation:
    layout = Layout(Target(1, "window", "RobloxPlayer", "com.roblox.RobloxPlayer"), "window", Rect(0, 0, 4, 3), (4, 3), "monitor", (1, 1))
    return Observation(layout, 1.0, 1, 1, bytes(4 * 3 * 3))


class FakeStore:
    def __init__(self, root: Path, settings: ReplaySettings) -> None:
        self.root = root
        self.settings = settings
        self.recorded: list[tuple[Observation, str, str]] = []
        self.record_started = threading.Event()
        self.release_record = threading.Event()
        self.block_records = False
        self.frames: list[ReplayFrame] = []
        self.updated: list[ReplaySettings] = []
        self.restore_error = False
        self.save_error = False
        self.saved = 0
        self.history_calls = 0

    def restore_settings(self) -> ReplaySettings:
        if self.restore_error:
            raise RuntimeError("corrupt")
        return self.settings

    def save_settings(self) -> None:
        if self.save_error:
            raise RuntimeError("disk")
        self.saved += 1

    def update_settings(self, settings: ReplaySettings) -> ReplaySettings:
        self.save_settings()
        self.settings = settings
        self.updated.append(settings)
        return settings

    def record(self, item: Observation, session_id: str, state: str):
        self.record_started.set()
        if self.block_records:
            self.release_record.wait(1)
        if not self.settings.enabled:
            return None
        self.recorded.append((item, session_id, state))
        frame = ReplayFrame(FRAME, session_id, 10.0, 4, 3, "webp", "frame", state)
        self.frames = [frame]
        return frame

    def list_frames(self, session_id: str | None = None):
        self.history_calls += 1
        return tuple(frame for frame in self.frames if session_id is None or frame.session_id == session_id)

    def stats(self):
        self.history_calls += 1
        return ReplayStats(len(self.frames), len({frame.session_id for frame in self.frames}), 12 * len(self.frames), self.settings.enabled)

    def delete_session(self, session_id: str) -> int:
        count = len(self.frames)
        self.frames = [frame for frame in self.frames if frame.session_id != session_id]
        return count

    def get_frame(self, frame_id: str):
        if frame_id != FRAME:
            raise RuntimeError("missing")
        return "image/webp", b"fake"


class ReplayServiceTests(unittest.TestCase):
    def test_real_default_store_reads_missing_history_without_creating_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "replays"
            service = ReplayService(root)
            try:
                deadline = time.monotonic() + 1
                while time.monotonic() < deadline and service.poll()["phase"] == "loading":
                    time.sleep(0.005)
                self.assertEqual(service.poll()["phase"], "ready")
                self.assertFalse(root.exists())
            finally:
                service.close()
                self.assertTrue(service._done.wait(1))

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.store: FakeStore | None = None

        def factory(root: Path, settings: ReplaySettings) -> FakeStore:
            self.store = FakeStore(root, settings)
            return self.store

        self.service = ReplayService(Path(self.temporary.name) / "replays", store_factory=factory)

    def tearDown(self) -> None:
        self.service.close()
        self.service._done.wait(1)
        self.temporary.cleanup()

    def wait_for(self, predicate) -> dict[str, object]:
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            result = self.service.poll()
            if predicate(result):
                return result
            time.sleep(0.005)
        self.fail("replay service did not finish expected queued work")

    def enable(self) -> None:
        self.assertTrue(self.service.command("settings", ReplaySettings(enabled=True)))
        self.wait_for(lambda result: result["settings"]["enabled"] is True)

    def test_default_off_never_creates_store_root_and_command_validation_is_strict(self):
        self.assertFalse(self.service.submit(observation(), SESSION, "gameplay"))
        self.assertFalse(self.service.command("settings", {"enabled": True}))
        self.assertFalse(self.service.command("select", "not-a-uuid"))
        self.assertFalse(self.service.command("frame", 1))
        self.assertFalse(self.service.command("refresh", {}))
        self.wait_for(lambda result: result["phase"] == "ready")
        self.assertFalse((Path(self.temporary.name) / "replays").exists())

    def test_frame_queue_backpressure_and_stop_session_epoch_drop_pending_work(self):
        self.enable()
        assert self.store is not None
        self.store.block_records = True
        self.assertTrue(self.service.submit(observation(), SESSION, "gameplay"))
        self.assertTrue(self.store.record_started.wait(1))
        self.assertTrue(self.service.submit(observation(), SESSION, "gameplay"))
        self.assertFalse(self.service.submit(observation(), SESSION, "gameplay"))
        self.assertTrue(self.service.stop_session(SESSION))
        self.store.release_record.set()
        self.wait_for(lambda result: len(self.store.recorded) == 1)
        time.sleep(0.05)
        self.assertEqual(len(self.store.recorded), 1)

    def test_disable_priority_clears_pending_frames_and_prevents_future_writes(self):
        self.enable()
        assert self.store is not None
        self.store.block_records = True
        self.assertTrue(self.service.submit(observation(), SESSION, "gameplay"))
        self.assertTrue(self.store.record_started.wait(1))
        self.assertTrue(self.service.submit(observation(), SESSION, "gameplay"))
        self.assertTrue(self.service.command("settings", ReplaySettings(enabled=False)))
        self.store.release_record.set()
        self.wait_for(lambda result: result["settings"]["enabled"] is False)
        time.sleep(0.05)
        self.assertEqual(len(self.store.recorded), 1)
        self.assertFalse(self.service.submit(observation(), SESSION, "gameplay"))

    def test_queued_privacy_marker_survives_session_stop(self):
        self.enable()
        assert self.store is not None
        self.store.block_records = True
        self.assertTrue(self.service.submit(observation(), SESSION, "gameplay"))
        self.assertTrue(self.store.record_started.wait(1))
        self.assertTrue(self.service.submit(observation(), SESSION, "redacted_unknown"))
        self.assertTrue(self.service.stop_session(SESSION))
        self.store.release_record.set()
        self.wait_for(lambda result: len(self.store.recorded) == 2)
        self.assertEqual([entry[2] for entry in self.store.recorded], ["gameplay", "redacted_unknown"])

    def test_deleted_session_rejects_queued_and_future_privacy_markers(self):
        self.enable()
        assert self.store is not None
        self.store.block_records = True
        self.assertTrue(self.service.submit(observation(), SESSION, "gameplay"))
        self.assertTrue(self.store.record_started.wait(1))
        processed = threading.Event()
        handle_frame = self.service._handle_frame

        def observe_completion(task):
            try:
                handle_frame(task)
            finally:
                processed.set()

        self.service._handle_frame = observe_completion
        self.assertTrue(self.service.submit(observation(), SESSION, "redacted_unknown"))
        self.assertTrue(self.service.command("delete", SESSION))
        self.store.release_record.set()
        self.assertTrue(processed.wait(1))
        self.assertEqual([entry[2] for entry in self.store.recorded], ["gameplay"])
        self.assertEqual(self.store.frames, [])
        self.assertFalse(self.service.submit(observation(), SESSION, "redacted_unknown"))

    def test_recording_off_discards_queued_and_future_privacy_markers(self):
        self.enable()
        assert self.store is not None
        self.store.block_records = True
        self.assertTrue(self.service.submit(observation(), SESSION, "gameplay"))
        self.assertTrue(self.store.record_started.wait(1))
        self.assertTrue(self.service.submit(observation(), SESSION, "redacted_unknown"))
        self.assertTrue(self.service.command("settings", ReplaySettings(enabled=False)))
        self.store.release_record.set()
        self.wait_for(lambda result: result["settings"]["enabled"] is False)
        self.assertTrue(self.service._frames.empty())
        self.assertEqual([entry[2] for entry in self.store.recorded], ["gameplay"])
        self.assertFalse(self.service.submit(observation(), SESSION, "redacted_unknown"))

    def test_settings_are_usable_only_after_atomic_save_and_restore_failure_reads_no_history(self):
        assert self.store is not None
        self.store.save_error = True
        self.assertTrue(self.service.command("settings", ReplaySettings(enabled=True)))
        self.wait_for(lambda result: result["phase"] == "error")
        self.assertFalse(self.service.submit(observation(), SESSION, "gameplay"))
        self.assertEqual(self.store.saved, 0)

        self.service.close()
        self.service._done.wait(1)
        self.temporary.cleanup()
        self.temporary = tempfile.TemporaryDirectory()
        failed_store: FakeStore | None = None

        def factory(root: Path, settings: ReplaySettings) -> FakeStore:
            nonlocal failed_store
            failed_store = FakeStore(root, settings)
            failed_store.restore_error = True
            return failed_store

        self.service = ReplayService(Path(self.temporary.name) / "replays", store_factory=factory)
        self.wait_for(lambda result: result["phase"] == "error")
        assert failed_store is not None
        self.assertEqual(failed_store.frames, [])
        self.assertEqual(failed_store.history_calls, 0)
        self.assertFalse(self.service.submit(observation(), SESSION, "gameplay"))

    def test_select_read_delete_and_close_use_cached_safe_state(self):
        self.enable()
        assert self.store is not None
        self.assertTrue(self.service.submit(observation(), SESSION, "gameplay"))
        self.wait_for(lambda result: result["stats"]["frame_count"] == 1)
        self.assertTrue(self.service.command("select", SESSION))
        selected = self.wait_for(lambda result: result["selected_session"] == SESSION)
        self.assertEqual(selected["frames"][0]["frame_id"], FRAME)
        self.assertTrue(self.service.command("frame", FRAME))
        frame = self.wait_for(lambda result: result["frame"] is not None)
        self.assertEqual(frame["frame"], {"frame_id": FRAME, "data_url": "data:image/webp;base64,ZmFrZQ=="})
        self.assertTrue(self.service.command("delete", SESSION))
        cleared = self.wait_for(lambda result: result["stats"]["frame_count"] == 0)
        self.assertIsNone(cleared["frame"])
        self.service.close()
        self.assertFalse(self.service.submit(observation(), SESSION, "gameplay"))
        self.assertTrue(self.service.done or self.service._done.wait(1))


if __name__ == "__main__":
    unittest.main()
