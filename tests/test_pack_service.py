"""Pack recognition worker tests use synthetic BGR bytes and fake child targets."""

from __future__ import annotations

from io import BytesIO
import json
import multiprocessing
from pathlib import Path
import queue
import tempfile
import threading
import time
import unittest

from PIL import Image

from afk_grinder import __version__
from afk_grinder.recognition.matcher import TemplateHit
from afk_grinder.recognition.pack_results import AnchorHit
from afk_grinder.recognition.packs import load_pack
from afk_grinder.recognition.pack_service import (
    MAX_COMPILED_TEMPLATES,
    PackRecognitionResult,
    PackRecognitionService,
    PackWorkerConfig,
    TIMEOUT_ERROR,
    WARMUP_ERROR,
    WORKER_ERROR,
    _read_message,
    _worker,
)
from tools.make_fixture_demo import generate


class Pipe:
    def __init__(self, packets=()):
        self.packets = list(packets)
        self.sent = []
        self.closed = False

    def recv_bytes(self, maximum):
        if not self.packets:
            raise EOFError
        packet = self.packets.pop(0)
        if len(packet) > maximum:
            raise OSError("oversized")
        return packet

    def send_bytes(self, packet):
        self.sent.append(packet)

    def close(self):
        self.closed = True


class Gate:
    def wait(self, timeout):
        return True


class FakeMatcher:
    instances = []

    def __init__(self, specs):
        self.specs = tuple(specs)
        self.warmed = False
        self.closed = False
        type(self).instances.append(self)

    def warmup(self):
        self.warmed = True

    def match(self, width, height, pixels, *, timeout):
        if not self.warmed:
            raise AssertionError("warmup required")
        return tuple(TemplateHit(spec.template_id, 0.0, None) for spec in self.specs)

    def close(self):
        self.closed = True


def _send(connection, payload):
    connection.send_bytes(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def success_worker(connection, config, gate):
    if not gate.wait(1):
        return
    _send(connection, {"kind": "ready"})
    while True:
        try:
            header = json.loads(connection.recv_bytes(16_384).decode("utf-8"))
        except EOFError:
            return
        if header.get("kind") == "close":
            return
        connection.recv_bytes(64 * 1024 * 1024)
        _send(connection, {
            "kind": "result", "request_id": header["request_id"], "variant_count": 1,
            "anchors": [{"id": anchor.id, "score": None, "box": None} for anchor in config.pack.anchors],
        })


def blocked_worker(connection, config, gate):
    if not gate.wait(1):
        return
    _send(connection, {"kind": "ready"})
    connection.recv_bytes(16_384)
    connection.recv_bytes(64 * 1024 * 1024)
    time.sleep(1)


def silent_worker(connection, config, gate):
    gate.wait(1)
    time.sleep(1)


def ready_but_nonreading_worker(connection, config, gate):
    """Advertise readiness, then leave the parent raw-pixel write blocked."""
    if gate.wait(1):
        _send(connection, {"kind": "ready"})
        time.sleep(5)


class ProcessWithoutChild:
    """Process fake used to force parent lifecycle order without forking."""

    def __init__(self):
        self.started = False
        self.terminated = False
        self.killed = False

    def start(self):
        self.started = True

    def is_alive(self):
        return False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    def join(self, timeout=None):
        return None


class LifecycleContext:
    """Use portable spawn IPC while retaining deterministic process admission."""

    def __init__(self):
        self._spawn = multiprocessing.get_context("spawn")
        self.process = ProcessWithoutChild()

    def Pipe(self, *, duplex):
        return self._spawn.Pipe(duplex=duplex)

    def Event(self):
        return self._spawn.Event()

    def Process(self, **_kwargs):
        return self.process


class BlockingQueue:
    """Pause submit after it has selected a frame, before queue admission ends."""

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self._queue = queue.Queue(maxsize=1)

    def put_nowait(self, item):
        self.entered.set()
        if not self.release.wait(1):
            raise AssertionError("test did not release queued frame")
        self._queue.put_nowait(item)

    def get_nowait(self):
        return self._queue.get_nowait()

    def empty(self):
        return self._queue.empty()


class ObservingConnection:
    """Expose the second parent write without changing the spawned child."""

    def __init__(self, connection):
        self._connection = connection
        self._send_count = 0
        self.pixels_started = threading.Event()

    def send_bytes(self, payload):
        self._send_count += 1
        if self._send_count == 2:
            self.pixels_started.set()
        self._connection.send_bytes(payload)

    def recv_bytes(self, maximum):
        return self._connection.recv_bytes(maximum)

    def poll(self, timeout):
        return self._connection.poll(timeout)

    def close(self):
        self._connection.close()


class PackRecognitionServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        pack_directory, _, _ = generate(root / "demo", "a" * 40)
        self.pack = load_pack(pack_directory, app_version=__version__)
        self.size = self.pack.reference_size
        self.pixels = b"\x00\x01\x02" * (self.size[0] * self.size[1])
        FakeMatcher.instances = []

    def wait_for(self, service, *, limit=1.0):
        deadline = time.monotonic() + limit
        while time.monotonic() < deadline:
            result = service.poll()
            if result is not None:
                return result
            time.sleep(.01)
        self.fail("worker result timed out")

    def service(self, target):
        return PackRecognitionService(
            self.pack, self.size, _context=multiprocessing.get_context("spawn"), _worker_target=target,
        )

    def test_worker_aggregates_template_hits_to_ordered_anchor_metadata(self):
        request = json.dumps({
            "kind": "match", "request_id": 1, "width": self.size[0], "height": self.size[1], "timeout": 1.0,
        }).encode("utf-8")
        pipe = Pipe([request, self.pixels, b'{"kind":"close"}'])

        _worker(pipe, PackWorkerConfig(self.pack, self.size), Gate(), FakeMatcher)

        messages = [json.loads(packet) for packet in pipe.sent]
        self.assertEqual(messages[0], {"kind": "ready"})
        result = messages[1]
        self.assertEqual(result["kind"], "result")
        self.assertEqual(result["request_id"], 1)
        self.assertLessEqual(result["variant_count"], MAX_COMPILED_TEMPLATES)
        self.assertEqual([item["id"] for item in result["anchors"]], [anchor.id for anchor in self.pack.anchors])
        self.assertTrue(FakeMatcher.instances[0].closed)

    def test_parent_rejects_stale_or_out_of_roi_metadata(self):
        stale = Pipe([b'{"kind":"result","request_id":2,"variant_count":1,"anchors":[]}'])
        with self.assertRaisesRegex(ValueError, "Invalid recognition result"):
            _read_message(stale, self.pack, self.size, 1)

        duplicate = Pipe([b'{"kind":"result","kind":"ready"}'])
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            _read_message(duplicate, self.pack, self.size, 1)

        anchors = [{"id": anchor.id, "score": 1.0, "box": [999999, 0, 8, 8]} for anchor in self.pack.anchors]
        bad_box = Pipe([json.dumps({
            "kind": "result", "request_id": 1, "variant_count": 1, "anchors": anchors,
        }).encode("utf-8")])
        with self.assertRaisesRegex(ValueError, "Invalid recognition result"):
            _read_message(bad_box, self.pack, self.size, 1)

    def test_single_inflight_exact_dimensions_and_idempotent_close(self):
        service = self.service(success_worker)
        self.addCleanup(service.close)
        service.start()
        deadline = time.monotonic() + 5
        while not service.ready and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(service.ready)
        wrong_pixels = b"\x00\x01\x02" * ((self.size[0] - 1) * self.size[1])
        with self.assertRaisesRegex(ValueError, "do not match"):
            service.submit(self.size[0] - 1, self.size[1], wrong_pixels)
        service.submit(*self.size, self.pixels)
        with self.assertRaisesRegex(RuntimeError, "not ready"):
            service.submit(*self.size, self.pixels)
        result = self.wait_for(service)
        self.assertFalse(result.error)
        self.assertEqual([hit.id for hit in result.hits], [anchor.id for anchor in self.pack.anchors])
        service.close()
        service.close()
        self.assertFalse(service.ready)

    def test_cancel_drops_late_results_and_warmup_timeout_is_bounded(self):
        service = self.service(blocked_worker)
        self.addCleanup(service.close)
        service.start()
        deadline = time.monotonic() + 5
        while not service.ready and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(service.ready)
        service.submit(*self.size, self.pixels)
        service.cancel()
        time.sleep(.05)
        self.assertIsNone(service.poll())

        timed = PackRecognitionService(
            self.pack, self.size, _context=multiprocessing.get_context("spawn"), _worker_target=silent_worker,
            warmup_timeout=.05,
        )
        self.addCleanup(timed.close)
        timed.start()
        result = self.wait_for(timed)
        self.assertEqual(result.error, WARMUP_ERROR)
        self.assertFalse(timed.ready)

    def test_response_parser_uses_fixed_errors_and_no_sdk_import(self):
        pipe = Pipe([json.dumps({"kind": "error", "error": WORKER_ERROR, "request_id": 1}).encode("utf-8")])
        self.assertEqual(_read_message(pipe, self.pack, self.size, 1).error, WORKER_ERROR)
        self.assertNotIn("maa", __import__("afk_grinder.recognition.pack_service", fromlist=["x"]).__dict__)
        self.assertNotEqual(TIMEOUT_ERROR, WARMUP_ERROR)

    def test_forced_cancel_races_leave_no_queued_frame_child_or_result(self):
        context = LifecycleContext()
        service = PackRecognitionService(self.pack, self.size, _context=context)
        self.addCleanup(service.close)

        # A launch deferred until after cancellation must not create a child.
        service.cancel()
        service._launch()
        self.assertFalse(context.process.started)
        self.assertIsNone(service.poll())

        # Recreate the service so submit can be held precisely at queue admission.
        context = LifecycleContext()
        service = PackRecognitionService(self.pack, self.size, _context=context)
        self.addCleanup(service.close)
        blocking_requests = BlockingQueue()
        service._requests = blocking_requests
        with service._lock:
            service._state = "ready"
        errors = []
        submitter = threading.Thread(
            target=lambda: self._submit_forced_race(service, errors), daemon=True,
        )
        submitter.start()
        self.assertTrue(blocking_requests.entered.wait(1))
        canceller = threading.Thread(target=service.cancel, daemon=True)
        canceller.start()
        self.assertTrue(service._stopped.wait(1))
        blocking_requests.release.set()
        submitter.join(timeout=1)
        canceller.join(timeout=1)

        self.assertFalse(submitter.is_alive())
        self.assertFalse(canceller.is_alive())
        self.assertEqual(errors, [])
        self.assertTrue(blocking_requests.empty())
        self.assertFalse(context.process.started)
        self.assertFalse(service._complete_request(1, PackRecognitionResult(error=WORKER_ERROR)))
        self.assertIsNone(service.poll())

    def _submit_forced_race(self, service, errors):
        try:
            service.submit(*self.size, self.pixels)
        except Exception as error:  # pragma: no cover - assertion keeps test diagnostics compact.
            errors.append(error)


class PackRecognitionServiceNativeCanaryTests(unittest.TestCase):
    """Real default-spawn Maa worker proof using original synthetic pixels only."""

    def test_default_spawn_worker_returns_synthetic_anchor_metadata(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        pack_directory, _, _ = generate(Path(temporary.name) / "demo", "a" * 40)
        pack = load_pack(pack_directory, app_version=__version__)
        size = pack.reference_size
        texture = next(asset for asset in pack.assets if asset.id == "gameplay")
        with Image.open(BytesIO(texture.data)) as source:
            frame = Image.new("RGB", size, (200, 200, 200))
            frame.paste(source.convert("RGB"), (11, 9))
        service = PackRecognitionService(pack, size)
        self.addCleanup(service.close)
        service.start()
        deadline = time.monotonic() + 10
        while not service.ready and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(service.ready)
        service.submit(*size, frame.tobytes("raw", "BGR"))
        while time.monotonic() < deadline:
            result = service.poll()
            if result is not None:
                break
            time.sleep(.01)
        else:
            self.fail("default spawned Maa worker result timed out")
        self.assertEqual(result.error, "")
        gameplay = next(hit for hit in result.hits if hit.id == "gameplay")
        self.assertIsNotNone(gameplay.box)
        self.assertEqual(gameplay.box, (11, 9, 16, 16))

    def _nonreading_service(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        pack_directory, _, _ = generate(Path(temporary.name) / "demo", "a" * 40)
        manifest_path = pack_directory / "pack.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["reference_size"] = [2048, 2048]
        manifest["setup"]["min_content_size"] = [2048, 2048]
        for anchor in manifest["anchors"]:
            anchor["roi"] = [0, 0, 2048, 2048]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        pack = load_pack(pack_directory, app_version=__version__)
        service = PackRecognitionService(pack, pack.reference_size, _worker_target=ready_but_nonreading_worker)
        observer = ObservingConnection(service._parent)
        service._parent = observer
        self.addCleanup(service.close)
        service.start()
        deadline = time.monotonic() + 10
        while not service.ready and time.monotonic() < deadline:
            time.sleep(.01)
        self.assertTrue(service.ready)
        pixels = b"\x00\x01\x02" * (pack.reference_size[0] * pack.reference_size[1])
        return service, observer, pixels

    def test_nonreading_spawn_child_timeout_unwinds_blocked_writer(self):
        service, observer, pixels = self._nonreading_service()
        service.submit(*service._config.frame_size, pixels, timeout=.5)
        self.assertTrue(observer.pixels_started.wait(1))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            result = service.poll()
            if result is not None:
                break
            time.sleep(.01)
        else:
            self.fail("deadline did not publish a bounded result")
        self.assertEqual(result.error, TIMEOUT_ERROR)
        service._thread.join(timeout=1)
        self.assertFalse(service._thread.is_alive())
        self.assertFalse(service._process.is_alive())
        self.assertIsNone(service.poll())

    def test_nonreading_spawn_child_cancel_returns_and_drops_result(self):
        service, observer, pixels = self._nonreading_service()
        service.submit(*service._config.frame_size, pixels)
        self.assertTrue(observer.pixels_started.wait(1))
        started = time.monotonic()
        service.cancel()
        self.assertLess(time.monotonic() - started, 1)
        service._thread.join(timeout=1)
        self.assertFalse(service._thread.is_alive())
        self.assertFalse(service._process.is_alive())
        self.assertIsNone(service.poll())
