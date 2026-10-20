"""Private, bounded local replay-frame storage.

This module accepts already-captured observations. It never captures, exports,
or authorizes input, and it stores no window titles, keys, source paths, or
full-resolution frame files.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from io import BytesIO
import json
import math
import os
from pathlib import Path
import re
import stat
import sqlite3
from contextlib import contextmanager
import threading
import time
import uuid
from typing import Callable

from PIL import Image, ImageFilter

from afk_grinder.recognition.observation import Observation


_MEBIBYTE = 1024 * 1024
_GIBIBYTE = 1024 * 1024 * 1024
_MAX_FRAME_BYTES = 2 * _MEBIBYTE
_SESSION_ID = re.compile(r"[0-9a-f]{32}\Z")
_STATES = frozenset({"gameplay", "bank_reward", "disconnected", "popup_dismissed", "reconnected",
                     "redacted_login", "redacted_trade", "redacted_purchase", "redacted_unknown", "redacted_restricted"})
_EVENTS = frozenset({"frame", "state_change"})
_MIME_TYPES = {"webp": "image/webp", "jpeg": "image/jpeg"}


class ReplayError(RuntimeError):
    """A fixed, safe replay-store failure without host filesystem details."""


@dataclass(frozen=True)
class ReplaySettings:
    enabled: bool = False
    retention_days: int = 7
    image_format: str = "webp"
    max_width: int = 960
    quality: int = 60
    interval_seconds: int = 2
    max_bytes: int = 2 * _GIBIBYTE

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("Replay enabled must be boolean.")
        if type(self.retention_days) is not int or not 1 <= self.retention_days <= 365:
            raise ValueError("Replay retention_days must be an integer from 1 to 365.")
        if type(self.image_format) is not str or self.image_format not in _MIME_TYPES:
            raise ValueError("Replay image_format must be webp or jpeg.")
        if type(self.max_width) is not int or not 320 <= self.max_width <= 1920:
            raise ValueError("Replay max_width must be an integer from 320 to 1920.")
        if type(self.quality) is not int or not 30 <= self.quality <= 85:
            raise ValueError("Replay quality must be an integer from 30 to 85.")
        if type(self.interval_seconds) is not int or not 1 <= self.interval_seconds <= 30:
            raise ValueError("Replay interval_seconds must be an integer from 1 to 30.")
        if type(self.max_bytes) is not int or not 100 * _MEBIBYTE <= self.max_bytes <= 20 * _GIBIBYTE:
            raise ValueError("Replay max_bytes must be an integer from 100 MiB to 20 GiB.")


@dataclass(frozen=True)
class ReplayFrame:
    frame_id: str
    session_id: str
    recorded_at: float
    width: int
    height: int
    image_format: str
    event: str
    state: str

    @property
    def mime_type(self) -> str:
        return _MIME_TYPES[self.image_format]


@dataclass(frozen=True)
class ReplayStats:
    frame_count: int
    session_count: int
    byte_count: int
    enabled: bool


class ReplayStore:
    """Synchronous private replay store for an engine-owned worker queue."""

    def __init__(
        self,
        root: Path,
        settings: ReplaySettings = ReplaySettings(),
        *,
        monotonic_clock: Callable[[], float] = time.monotonic,
        utc_clock: Callable[[], float] = time.time,
    ) -> None:
        if not isinstance(root, Path):
            raise ValueError("Replay root must be a pathlib Path.")
        if type(settings) is not ReplaySettings:
            raise ValueError("Replay settings must be ReplaySettings.")
        if not callable(monotonic_clock) or not callable(utc_clock):
            raise ValueError("Replay clocks must be callable.")
        self._root = root
        self._settings = settings
        self._monotonic_clock = monotonic_clock
        self._utc_clock = utc_clock
        self._last_recorded: dict[str, float] = {}
        self._lock = threading.RLock()

    @property
    def settings(self) -> ReplaySettings:
        with self._lock:
            return self._settings

    def update_settings(self, settings: ReplaySettings) -> ReplaySettings:
        """Replace settings and immediately apply smaller retention/disk caps."""
        if type(settings) is not ReplaySettings:
            raise ValueError("Replay settings must be ReplaySettings.")
        with self._lock:
            previous = self._settings
            self._settings = settings
            try:
                # Persist the explicit preference before any destructive purge.
                self.save_settings()
            except Exception:
                self._settings = previous
                raise
            self._purge_database()
            return self._settings

    def restore_settings(self) -> ReplaySettings:
        """Load an earlier explicit preference before applying any retention purge."""
        with self._lock:
            if not self._root_exists():
                return self._settings
            self._validate_root()
            path = self._root / "settings.json"
            if not path.exists():
                return self._settings
            try:
                raw = json.loads(self._read_regular_file(path, 4096))
                if type(raw) is not dict or set(raw) != set(asdict(ReplaySettings())):
                    raise ValueError()
                settings = ReplaySettings(**raw)
            except Exception:
                raise ReplayError("Replay preferences are invalid.") from None
            self._settings = settings
            return settings

    def save_settings(self) -> None:
        """Persist only after an explicit settings command; never save image data here."""
        with self._lock:
            self._ensure_storage(create=True)
            self._atomic_write(self._root / "settings.json", json.dumps(
                asdict(self._settings), separators=(",", ":"), allow_nan=False).encode("utf-8"))

    def record(self, observation: Observation, session_id: str, state: str, *,
               event: str = "frame") -> ReplayFrame | None:
        self._validate_session_id(session_id)
        self._validate_event(event)
        if not self._recordable(observation, state):
            return None
        with self._lock:
            if not self._settings.enabled:
                return None
            now = self._clock_value(self._monotonic_clock)
            previous = self._last_recorded.get(session_id)
            if previous is not None and now - previous < self._settings.interval_seconds:
                return None
            timestamp = self._clock_value(self._utc_clock)
            encoded, width, height = self._encode(observation, state=state)
            self._ensure_storage(create=True)
            self._purge_database(timestamp)
            entry = ReplayFrame(uuid.uuid4().hex, session_id, timestamp, width, height,
                                self._settings.image_format, event, state)
            path = self._frame_path(entry)
            self._atomic_write(path, encoded)
            try:
                with self._database() as db:
                    self._insert(db, entry, len(encoded))
            except Exception:
                self._remove_new_frame(path)
                raise ReplayError("Replay index update failed.") from None
            self._last_recorded[session_id] = now
            self._purge_database(timestamp)
            return entry

    def list_sessions(self) -> tuple[str, ...]:
        return tuple(item["id"] for item in self.session_summaries())

    def session_summaries(self, before: tuple[float, str] | None = None) -> tuple[dict, ...]:
        """Bound UI metadata, without deleting any older session or frame."""
        with self._lock:
            if not self._ensure_storage(create=False):
                return ()
            self._purge_database()
            with self._database() as db:
                query = ("SELECT session_id, first_time, frame_count FROM (SELECT session_id, "
                         "MIN(recorded_at) AS first_time, COUNT(*) AS frame_count FROM frames "
                         "WHERE deleted=0 GROUP BY session_id)")
                args = ()
                if before is not None:
                    timestamp, session_id = before
                    self._validate_session_id(session_id)
                    if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
                        raise ValueError("Replay page timestamp is invalid.")
                    query += " WHERE first_time<? OR (first_time=? AND session_id<?)"
                    args = (timestamp, timestamp, session_id)
                rows = db.execute(query + " ORDER BY first_time DESC,session_id DESC LIMIT 100", args).fetchall()
            return tuple({"id": row[0], "started_at": row[1], "frame_count": row[2]} for row in rows)

    def list_frames(self, session_id: str | None = None, *, limit: int = 4096,
                    before: tuple[float, str] | None = None) -> tuple[ReplayFrame, ...]:
        if session_id is not None:
            self._validate_session_id(session_id)
        if type(limit) is not int or not 1 <= limit <= 4096:
            raise ValueError("Replay page limit is invalid.")
        if before is not None:
            timestamp, frame_id = before
            self._validate_frame_id(frame_id)
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp):
                raise ValueError("Replay page timestamp is invalid.")
        with self._lock:
            if not self._ensure_storage(create=False):
                return ()
            self._purge_database()
            query, args = "SELECT " + self._columns() + " FROM frames WHERE deleted=0", []
            if session_id is not None:
                query += " AND session_id=?"
                args.append(session_id)
            if before is not None:
                query += " AND (recorded_at<? OR (recorded_at=? AND frame_id<?))"
                args.extend((timestamp, timestamp, frame_id))
            query += " ORDER BY recorded_at DESC, frame_id DESC LIMIT ?"
            args.append(limit)
            with self._database() as db:
                rows = db.execute(query, args).fetchall()
            return tuple(reversed([self._entry_from_row(row) for row in rows]))

    def get_frame(self, frame_id: str) -> tuple[str, bytes]:
        self._validate_frame_id(frame_id)
        with self._lock:
            if not self._ensure_storage(create=False):
                raise ReplayError("Replay frame is unavailable.")
            self._purge_database()
            with self._database() as db:
                row = db.execute("SELECT " + self._columns() + " FROM frames WHERE frame_id=? AND deleted=0",
                                 (frame_id,)).fetchone()
            if row is None:
                raise ReplayError("Replay frame is unavailable.")
            entry = self._entry_from_row(row)
            raw = self._read_regular_file(self._frame_path(entry), _MAX_FRAME_BYTES)
            try:
                with Image.open(BytesIO(raw)) as image:
                    image.verify()
                    if (image.format != {"webp": "WEBP", "jpeg": "JPEG"}[entry.image_format]
                            or image.size != (entry.width, entry.height)):
                        raise ValueError()
            except Exception:
                raise ReplayError("Replay frame is invalid.") from None
            return entry.mime_type, raw

    def delete_session(self, session_id: str) -> int:
        self._validate_session_id(session_id)
        with self._lock:
            if not self._ensure_storage(create=False):
                return 0
            with self._database() as db:
                count = db.execute("SELECT COUNT(*) FROM frames WHERE session_id=? AND deleted=0", (session_id,)).fetchone()[0]
                db.execute("UPDATE frames SET deleted=1 WHERE session_id=?", (session_id,))
            self._cleanup_deleted()
            self._last_recorded.pop(session_id, None)
            return count

    def purge(self) -> ReplayStats:
        with self._lock:
            if self._ensure_storage(create=False):
                self._purge_database()
            return self.stats()

    def stats(self) -> ReplayStats:
        with self._lock:
            if not self._ensure_storage(create=False):
                return ReplayStats(0, 0, 0, self._settings.enabled)
            self._purge_database()
            with self._database() as db:
                count, sessions, size = db.execute("SELECT COUNT(*), COUNT(DISTINCT session_id), "
                    "COALESCE(SUM(byte_count),0) FROM frames WHERE deleted=0").fetchone()
            return ReplayStats(count, sessions, size + self._metadata_bytes(), self._settings.enabled)

    def _ensure_storage(self, *, create: bool) -> bool:
        if not self._root_exists():
            if not create:
                return False
            try:
                self._root.mkdir(mode=0o700, parents=True, exist_ok=False)
                self._frames_dir().mkdir(mode=0o700)
            except OSError:
                raise ReplayError("Replay storage unavailable.") from None
        self._validate_root()
        path = self._index_path()
        created = False
        if not path.exists():
            if not create:
                raise ReplayError("Replay index is unavailable.")
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            os.close(descriptor)
            created = True
        with self._database() as db:
            if created:
                db.execute("PRAGMA auto_vacuum=INCREMENTAL")
            db.execute("CREATE TABLE IF NOT EXISTS frames (frame_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, "
                       "recorded_at REAL NOT NULL, width INTEGER NOT NULL, height INTEGER NOT NULL, "
                       "image_format TEXT NOT NULL, event TEXT NOT NULL, state TEXT NOT NULL, "
                       "byte_count INTEGER NOT NULL, deleted INTEGER NOT NULL DEFAULT 0)")
            db.execute("CREATE INDEX IF NOT EXISTS frame_age ON frames(deleted,recorded_at)")
            db.execute("CREATE INDEX IF NOT EXISTS frame_session ON frames(session_id,recorded_at)")
        self._recover_orphans()
        return True

    @contextmanager
    def _database(self):
        self._validate_root()
        self._validate_regular_frame(self._index_path())
        db = None
        try:
            db = sqlite3.connect(self._index_path(), timeout=1)
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        except sqlite3.Error:
            raise ReplayError("Replay index is invalid or unavailable.") from None
        finally:
            if db is not None:
                db.close()
            if os.name == "posix":
                os.chmod(self._index_path(), 0o600)

    @staticmethod
    def _columns():
        return "frame_id,session_id,recorded_at,width,height,image_format,event,state"

    def _entry_from_row(self, row):
        return self._entry_from_dict(dict(zip(self._columns().split(","), row)))

    def _insert(self, db, entry, size):
        db.execute("INSERT INTO frames VALUES (?,?,?,?,?,?,?,?,?,0)",
                   (*self._entry_dict(entry).values(), size))

    def _purge_database(self, now=None):
        timestamp = self._clock_value(self._utc_clock) if now is None else now
        self._cleanup_deleted()
        with self._database() as db:
            db.execute("PRAGMA incremental_vacuum").fetchall()
            db.execute("UPDATE frames SET deleted=1 WHERE recorded_at<?", (timestamp - self._settings.retention_days * 86400,))
            total = db.execute("SELECT COALESCE(SUM(byte_count),0) FROM frames WHERE deleted=0").fetchone()[0]
            total += self._metadata_bytes()
            # Small batches keep memory bounded even with years of metadata.
            while total > self._settings.max_bytes:
                rows = db.execute("SELECT frame_id,byte_count FROM frames WHERE deleted=0 "
                                  "ORDER BY recorded_at,frame_id LIMIT 256").fetchall()
                if not rows:
                    break
                for frame_id, size in rows:
                    if total <= self._settings.max_bytes:
                        break
                    db.execute("UPDATE frames SET deleted=1 WHERE frame_id=?", (frame_id,))
                    total -= size
        self._cleanup_deleted()
        with self._database() as db:
            db.execute("PRAGMA incremental_vacuum").fetchall()

    def _metadata_bytes(self):
        total = 0
        for path in (self._index_path(), self._root / "settings.json"):
            if path.exists():
                self._validate_regular_frame(path)
                total += path.stat().st_size
        return total

    def _cleanup_deleted(self):
        while True:
            with self._database() as db:
                rows = db.execute("SELECT " + self._columns() + " FROM frames WHERE deleted=1 LIMIT 256").fetchall()
            if not rows:
                return
            for row in rows:
                entry = self._entry_from_row(row)
                path = self._frame_path(entry)
                if path.exists() or path.is_symlink():
                    self._validate_regular_frame(path)
                    path.unlink()
                with self._database() as db:
                    db.execute("DELETE FROM frames WHERE frame_id=? AND deleted=1", (entry.frame_id,))

    def _recover_orphans(self):
        # Only on opening storage, not per-frame; no game files ever predate this index.
        if getattr(self, "_recovered", False):
            return
        with self._database() as db:
            for path in self._frames_dir().iterdir():
                if re.fullmatch(r"[0-9a-f]{32}\.(?:webp|jpg)", path.name):
                    if db.execute("SELECT 1 FROM frames WHERE frame_id=?", (path.stem,)).fetchone() is None:
                        self._validate_regular_frame(path)
                        path.unlink()
        self._recovered = True

    def _root_exists(self) -> bool:
        try:
            self._root.lstat()
        except FileNotFoundError:
            return False
        except OSError:
            raise ReplayError("Replay storage unavailable.") from None
        return True

    def _validate_root(self) -> None:
        self._validate_directory(self._root, private=True)
        self._validate_directory(self._frames_dir(), private=True)

    def _validate_directory(self, path: Path, *, private: bool) -> None:
        try:
            details = path.lstat()
        except OSError:
            raise ReplayError("Replay storage is unsafe.") from None
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISDIR(details.st_mode):
            raise ReplayError("Replay storage is unsafe.")
        if os.name == "posix" and private:
            try:
                os.chmod(path, 0o700)
            except OSError:
                raise ReplayError("Replay storage is unsafe.") from None

    def _validate_regular_frame(self, path: Path) -> None:
        try:
            details = path.lstat()
        except OSError:
            raise ReplayError("Replay frame is unavailable.") from None
        if stat.S_ISLNK(details.st_mode) or not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
            raise ReplayError("Replay storage is unsafe.")

    def _read_regular_file(self, path: Path, maximum_size: int) -> bytes:
        self._validate_regular_frame(path)
        descriptor = None
        try:
            descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            details = os.fstat(descriptor)
            if not stat.S_ISREG(details.st_mode) or details.st_nlink != 1:
                raise ReplayError("Replay storage is unsafe.")
            if not 0 <= details.st_size <= maximum_size:
                raise ReplayError("Replay frame is invalid.")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = None
                result = stream.read(maximum_size + 1)
            if len(result) > maximum_size:
                raise ReplayError("Replay frame is invalid.")
            return result
        except OSError:
            raise ReplayError("Replay frame is unavailable.") from None
        finally:
            if descriptor is not None:
                os.close(descriptor)

    def _encode(self, observation: Observation, *, state: str) -> tuple[bytes, int, int]:
        width, height = observation.layout.physical_size
        try:
            if state in {"redacted_login", "redacted_unknown", "redacted_restricted"}:
                # Do not even copy sensitive source pixels into the encoder.
                source = Image.new("RGB", (min(width, self._settings.max_width),
                                             max(1, round(height * min(1, self._settings.max_width / width)))),
                                   (18, 22, 35))
            else:
                source = Image.frombytes("RGB", (width, height), observation.pixels, "raw", "BGR")
            with source as image:
                if width > self._settings.max_width:
                    resized_height = round(height * self._settings.max_width / width)
                    image.thumbnail((self._settings.max_width, resized_height), Image.Resampling.LANCZOS)
                if state in {"redacted_purchase", "redacted_trade"}:
                    # Strong full-frame blur precedes encoding; the sharp
                    # original is never written or attached as metadata.
                    tiny = image.resize((max(1, image.width // 64), max(1, image.height // 64)), Image.Resampling.BOX)
                    blurred = tiny.resize(image.size, Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(24))
                    image.paste(blurred)
                    tiny.close()
                    blurred.close()
                output = BytesIO()
                if self._settings.image_format == "webp":
                    image.save(output, format="WEBP", quality=self._settings.quality, method=3, exif=b"")
                else:
                    image.save(output, format="JPEG", quality=self._settings.quality, optimize=True, exif=b"")
                encoded = output.getvalue()
                encoded_width, encoded_height = image.size
        except Exception:
            raise ReplayError("Replay frame encoding failed.") from None
        if len(encoded) > _MAX_FRAME_BYTES:
            raise ReplayError("Replay frame exceeds the size limit.")
        return encoded, encoded_width, encoded_height

    def _atomic_write(self, path: Path, payload: bytes) -> None:
        self._validate_root()
        if path.exists():
            self._validate_regular_frame(path)
        temporary = path.parent / f".pending-{uuid.uuid4().hex}"
        descriptor: int | None = None
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = None
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            if os.name == "posix":
                os.chmod(path, 0o600)
        except Exception:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise ReplayError("Replay write failed.") from None

    def _remove_new_frame(self, path: Path) -> None:
        try:
            if path.exists():
                self._validate_regular_frame(path)
                path.unlink()
        except ReplayError:
            raise
        except OSError:
            raise ReplayError("Replay storage unavailable.") from None

    def _entry_from_dict(self, raw: object) -> ReplayFrame:
        if type(raw) is not dict or set(raw) != {
            "frame_id", "session_id", "recorded_at", "width", "height", "image_format", "event", "state"
        }:
            raise ReplayError("Replay index is invalid.")
        try:
            entry = ReplayFrame(**raw)
        except TypeError:
            raise ReplayError("Replay index is invalid.") from None
        self._validate_frame_id(entry.frame_id)
        self._validate_session_id(entry.session_id)
        self._validate_event(entry.event)
        if entry.state not in _STATES or entry.image_format not in _MIME_TYPES:
            raise ReplayError("Replay index is invalid.")
        if (type(entry.recorded_at) not in (int, float) or isinstance(entry.recorded_at, bool)
                or not math.isfinite(entry.recorded_at) or type(entry.width) is not int
                or type(entry.height) is not int or entry.width <= 0 or entry.height <= 0):
            raise ReplayError("Replay index is invalid.")
        return entry

    @staticmethod
    def _entry_dict(entry: ReplayFrame) -> dict[str, object]:
        return {
            "frame_id": entry.frame_id,
            "session_id": entry.session_id,
            "recorded_at": entry.recorded_at,
            "width": entry.width,
            "height": entry.height,
            "image_format": entry.image_format,
            "event": entry.event,
            "state": entry.state,
        }

    def _index_path(self) -> Path:
        return self._root / "index.sqlite3"

    def _frames_dir(self) -> Path:
        return self._root / "frames"

    def _frame_path(self, entry: ReplayFrame) -> Path:
        extension = "webp" if entry.image_format == "webp" else "jpg"
        return self._frames_dir() / f"{entry.frame_id}.{extension}"

    @staticmethod
    def _recordable(observation: Observation, state: str) -> bool:
        return (
            type(observation) is Observation
            and observation.layout.target.is_roblox
            and observation.layout.region_kind == "client"
            and observation.layout.content_verified is True
            and type(state) is str
            and state in _STATES
        )

    @staticmethod
    def _clock_value(clock: Callable[[], float]) -> float:
        try:
            value = clock()
        except Exception:
            raise ReplayError("Replay clock is invalid.") from None
        if type(value) not in (int, float) or isinstance(value, bool) or not math.isfinite(value):
            raise ReplayError("Replay clock is invalid.")
        return float(value)

    @staticmethod
    def _validate_session_id(session_id: str) -> None:
        if type(session_id) is not str or _SESSION_ID.fullmatch(session_id) is None:
            raise ValueError("Replay session_id must be lowercase UUID hexadecimal.")

    @staticmethod
    def _validate_frame_id(frame_id: str) -> None:
        if type(frame_id) is not str or _SESSION_ID.fullmatch(frame_id) is None:
            raise ValueError("Replay frame_id must be lowercase UUID hexadecimal.")

    @staticmethod
    def _validate_event(event: str) -> None:
        if type(event) is not str or event not in _EVENTS:
            raise ValueError("Replay event is unsupported.")
