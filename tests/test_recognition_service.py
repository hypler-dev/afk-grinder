"""Warm recognition IPC tests use fakes and synthetic BGR bytes only."""

import json
import os
from pathlib import Path
import queue
import threading
import time
import unittest

from afk_grinder.recognition.matcher import LabelHit
from afk_grinder.recognition.service import (
    RecognitionService,
    RecognitionResult,
    TIMEOUT_ERROR,
    WORKER_ERROR,
    WARMUP_ERROR,
    _read_message,
    _worker,
)


LABELS = {"bank": r"bank", "trade": r"trade"}


class Pipe:
    def __init__(self, packets=()):
        self.packets = list(packets)
        self.sent = []
        self.closed = False
        self.close_calls = 0

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
        self.close_calls += 1
        self.closed = True


class FakeMatcher:
    hits = (LabelHit("bank", 0.9, (1, 2, 3, 4)),)
    error = None
    instances = []

    def __init__(self, model_directory, labels):
        self.model_directory = model_directory
        self.labels = labels
        self.closed = False
        self.frames = []
        self.warmups = 0
        type(self).instances.append(self)

    def warmup(self):
        self.warmups += 1

    def match_labels(self, width, height, pixels, *, timeout):
        if self.warmups != 1:
            raise AssertionError("Model must load before accepting frames.")
        self.frames.append((width, height, pixels, timeout))
        if type(self).error is not None:
            raise type(self).error
        return type(self).hits

    def close(self):
        self.closed = True


class LoopPipe(Pipe):
    def __init__(self, *, ready=True, respond=True):
        super().__init__()
        if ready:
            self.packets.append(b'{"kind":"ready"}')
        self.respond = respond
        self.request_id = None
        self.alive = True

    def poll(self, timeout):
        if not self.packets and timeout:
            time.sleep(min(timeout, 0.002))
        return bool(self.packets)

    def send_bytes(self, packet):
        self.sent.append(packet)
        try:
            header = json.loads(packet)
        except (UnicodeDecodeError, json.JSONDecodeError):
            if self.respond and self.request_id is not None:
                self.packets.append(json.dumps({
                    "kind": "result", "request_id": self.request_id,
                    "hits": [{"label_id": "bank", "score": 0.9, "box": [1, 2, 3, 4]}],
                }).encode())
            return
        if header.get("kind") == "match":
            self.request_id = header["request_id"]


class BlockingSendPipe(LoopPipe):
    """Simulates a child that stops consuming the next IPC header."""

    def __init__(self):
        super().__init__(respond=False)
        self.blocked = threading.Event()
        self.release = threading.Event()

    def send_bytes(self, packet):
        if b'"kind":"match"' in packet:
            self.blocked.set()
            self.release.wait(1)
        super().send_bytes(packet)


class BlockingReadPipe(LoopPipe):
    """Simulates a child that advertises a response then never frames it."""

    def __init__(self):
        super().__init__(respond=False)
        self.block_reads = False
        self.blocked = threading.Event()
        self.release = threading.Event()

    def send_bytes(self, packet):
        super().send_bytes(packet)
        try:
            json.loads(packet)
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.block_reads = True

    def poll(self, timeout):
        return self.block_reads or super().poll(timeout)

    def recv_bytes(self, maximum):
        if self.block_reads:
            self.blocked.set()
            self.release.wait(1)
            raise EOFError
        return super().recv_bytes(maximum)


class BlockingAdmissionQueue(queue.Queue):
    """Blocks one producer after state admission until the test releases it."""

    def __init__(self):
        super().__init__(maxsize=1)
        self.entered = threading.Event()
        self.release = threading.Event()

    def put_nowait(self, item):
        self.entered.set()
        if not self.release.wait(1):
            raise RuntimeError("Test admission was not released.")
        return super().put_nowait(item)


class CloseWinsLock:
    """Makes the close caller acquire the lifecycle lock before launch."""

    def __init__(self):
        self._lock = threading.Lock()
        self.launch_waiting = threading.Event()
        self.release_launch = threading.Event()
        self._launch_thread: int | None = None

    def acquire(self):
        current = threading.get_ident()
        if self._launch_thread is None:
            self._launch_thread = current
            self.launch_waiting.set()
            if not self.release_launch.wait(1):
                raise RuntimeError("Test launch was not released.")
        return self._lock.acquire()

    def release(self):
        self._lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()


class FakeProcess:
    def __init__(self, pipe):
        self.pipe = pipe
        self.exitcode = 0
        self.started = self.terminated = self.killed = False

    def start(self):
        self.started = True

    def is_alive(self):
        return self.pipe.alive

    def terminate(self):
        self.terminated = True
        self.pipe.alive = False

    def kill(self):
        self.killed = True
        self.pipe.alive = False

    def join(self, timeout=None):
        pass


class Context:
    def __init__(self, parent, child=None):
        self.parent = parent
        self.child = child or Pipe()
        self.event = threading.Event()
        self.process = FakeProcess(parent)

    def Pipe(self, duplex):
        self.duplex = duplex
        return self.parent, self.child

    def Event(self):
        return self.event

    def Process(self, **kwargs):
        self.process_args = kwargs
        return self.process


def wait_for(predicate, timeout=1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def poll_until(service, timeout=1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = service.poll()
        if result is not None:
            return result
        time.sleep(0.005)
    return service.poll()


class RecognitionWorkerTests(unittest.TestCase):
    def setUp(self):
        FakeMatcher.hits = (LabelHit("bank", 0.9, (1, 2, 3, 4)),)
        FakeMatcher.error = None
        FakeMatcher.instances.clear()

    def test_worker_warms_once_and_returns_metadata_only(self):
        request = b'{"kind":"match","request_id":1,"width":8,"height":8,"timeout":1.0}'
        pipe = Pipe([request, bytes(8 * 8 * 3)])
        gate = threading.Event()
        gate.set()

        _worker(pipe, Path("/model"), LABELS, gate, FakeMatcher)

        self.assertEqual(json.loads(pipe.sent[0]), {"kind": "ready"})
        result = json.loads(pipe.sent[1])
        self.assertEqual(result, {
            "kind": "result", "request_id": 1,
            "hits": [{"label_id": "bank", "score": 0.9, "box": [1, 2, 3, 4]}],
        })
        self.assertEqual(FakeMatcher.instances[0].frames, [(8, 8, bytes(8 * 8 * 3), 1.0)])
        self.assertEqual(FakeMatcher.instances[0].warmups, 1)
        self.assertTrue(FakeMatcher.instances[0].closed)
        self.assertTrue(pipe.closed)

    def test_ready_is_withheld_until_model_initialization_finishes(self):
        entered, release = threading.Event(), threading.Event()

        class BlockingMatcher(FakeMatcher):
            def warmup(self):
                entered.set()
                if not release.wait(1):
                    raise RuntimeError("Test warmup was not released.")
                super().warmup()

        pipe = Pipe()
        gate = threading.Event()
        gate.set()
        thread = threading.Thread(target=_worker, args=(pipe, Path("/model"), LABELS, gate, BlockingMatcher))
        thread.start()
        try:
            self.assertTrue(entered.wait(1))
            self.assertEqual(pipe.sent, [])
        finally:
            release.set()
            thread.join(1)
        self.assertFalse(thread.is_alive())
        self.assertEqual(json.loads(pipe.sent[0]), {"kind": "ready"})
        self.assertTrue(FakeMatcher.instances[0].closed)

    def test_model_initialization_failure_never_announces_ready(self):
        class BrokenMatcher(FakeMatcher):
            def warmup(self):
                raise RuntimeError("SENSITIVE_MODEL_MARKER /private/model")

        pipe = Pipe()
        gate = threading.Event()
        gate.set()
        _worker(pipe, Path("/model"), LABELS, gate, BrokenMatcher)
        self.assertEqual(len(pipe.sent), 1)
        self.assertEqual(json.loads(pipe.sent[0]), {"kind": "error", "error": WARMUP_ERROR})
        self.assertNotIn("SENSITIVE_", pipe.sent[0].decode())
        self.assertNotIn("/private/", pipe.sent[0].decode())
        self.assertTrue(FakeMatcher.instances[0].closed)
        self.assertTrue(pipe.closed)

    def test_worker_fault_never_serializes_native_error_details(self):
        FakeMatcher.error = RuntimeError("SENSITIVE_NATIVE_MARKER /private/frame")
        request = b'{"kind":"match","request_id":1,"width":8,"height":8,"timeout":1.0}'
        pipe = Pipe([request, bytes(8 * 8 * 3)])
        gate = threading.Event()
        gate.set()

        _worker(pipe, Path("/model"), LABELS, gate, FakeMatcher)

        serialized = pipe.sent[1].decode()
        self.assertEqual(json.loads(serialized), {"kind": "error", "error": WORKER_ERROR, "request_id": 1})
        self.assertNotIn("SENSITIVE_", serialized)
        self.assertNotIn("/private/", serialized)

    def test_malformed_result_and_unknown_label_are_rejected(self):
        for payload in (
            b'{"kind":"result","request_id":1,"hits":[{"label_id":"unknown","score":0.9,"box":[1,2,3,4]}]}',
            b'{"kind":"result","request_id":1,"hits":[{"label_id":"bank","score":true,"box":[1,2,3,4]}]}',
            b'{"kind":"result","request_id":2,"hits":[]}',
        ):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                _read_message(Pipe([payload]), set(LABELS), 8, 8, 1)


class RecognitionServiceTests(unittest.TestCase):
    def test_start_submit_poll_and_hard_close_use_background_lifecycle(self):
        parent = LoopPipe()
        context = Context(parent)
        service = RecognitionService(Path("/model"), LABELS, _context=context)

        service.start()
        self.assertTrue(wait_for(lambda: service.ready))
        service.submit(8, 8, bytes(8 * 8 * 3))
        result = poll_until(service)
        self.assertEqual(result, RecognitionResult((LabelHit("bank", 0.9, (1, 2, 3, 4)),)))
        service.close()

        self.assertTrue(context.process.started)
        self.assertTrue(context.event.is_set())
        self.assertTrue(context.process.terminated)
        self.assertFalse(service.ready)

    def test_cancel_drops_pending_and_late_results(self):
        parent = LoopPipe(respond=False)
        context = Context(parent)
        service = RecognitionService(Path("/model"), LABELS, _context=context)
        service.start()
        self.assertTrue(wait_for(lambda: service.ready))
        service.submit(8, 8, bytes(8 * 8 * 3))
        with self.assertRaises(RuntimeError):
            service.submit(8, 8, bytes(8 * 8 * 3))
        service.cancel()
        parent.packets.append(b'{"kind":"result","request_id":1,"hits":[]}')

        self.assertIsNone(service.poll())
        self.assertTrue(context.process.terminated)
        self.assertFalse(service.ready)

    def test_warmup_timeout_and_start_fault_return_safe_error(self):
        parent = LoopPipe(ready=False)
        context = Context(parent)
        service = RecognitionService(Path("/model"), LABELS, _context=context,
                                     warmup_timeout=0.02)
        service.start()
        result = poll_until(service)
        self.assertEqual(result, RecognitionResult(error=WARMUP_ERROR))
        self.assertTrue(context.process.terminated)

        parent = LoopPipe()
        context = Context(parent)
        context.process.start = lambda: (_ for _ in ()).throw(RuntimeError("spawn /private"))
        service = RecognitionService(Path("/model"), LABELS, _context=context)
        service.start()
        safe = poll_until(service)
        self.assertEqual(safe, RecognitionResult(error=WARMUP_ERROR))

    def test_match_deadline_terminates_worker_and_returns_safe_timeout(self):
        parent = LoopPipe(respond=False)
        context = Context(parent)
        service = RecognitionService(Path("/model"), LABELS, _context=context)
        service.start()
        self.assertTrue(wait_for(lambda: service.ready))
        service.submit(8, 8, bytes(8 * 8 * 3), timeout=0.01)

        self.assertEqual(poll_until(service), RecognitionResult(error=TIMEOUT_ERROR))
        self.assertTrue(context.process.terminated)
        self.assertFalse(service.ready)

    def test_total_deadline_kills_worker_when_ipc_write_or_framed_read_blocks(self):
        for parent in (BlockingSendPipe(), BlockingReadPipe()):
            with self.subTest(pipe=type(parent).__name__):
                context = Context(parent)
                service = RecognitionService(Path("/model"), LABELS, _context=context)
                try:
                    service.start()
                    self.assertTrue(wait_for(lambda: service.ready))
                    service.submit(8, 8, bytes(8 * 8 * 3), timeout=0.02)
                    self.assertTrue(wait_for(parent.blocked.is_set))
                    self.assertEqual(poll_until(service), RecognitionResult(error=TIMEOUT_ERROR))
                    self.assertTrue(context.process.terminated)
                    self.assertFalse(service.ready)
                finally:
                    parent.release.set()
                    service.close()

    def test_close_before_launch_does_not_create_a_child(self):
        parent = LoopPipe()
        context = Context(parent)
        service = RecognitionService(Path("/model"), LABELS, _context=context)
        lifecycle_lock = CloseWinsLock()
        service._close_lock = lifecycle_lock

        service.start()
        self.assertTrue(lifecycle_lock.launch_waiting.wait(1))
        close = threading.Thread(target=service.close)
        close.start()
        self.assertTrue(wait_for(lambda: not close.is_alive() or service._stopped.is_set()))
        try:
            self.assertTrue(service._stopped.is_set())
        finally:
            lifecycle_lock.release_launch.set()
        close.join(1)

        self.assertTrue(wait_for(lambda: not service._thread.is_alive()))
        self.assertFalse(context.process.started)
        self.assertTrue(parent.closed)
        self.assertTrue(context.child.closed)

    def test_close_racing_enqueue_drains_admitted_request_and_drops_result(self):
        parent = LoopPipe(respond=False)
        context = Context(parent)
        service = RecognitionService(Path("/model"), LABELS, _context=context)
        admission = BlockingAdmissionQueue()
        service._requests = admission
        service.start()
        self.assertTrue(wait_for(lambda: service.ready))

        submit = threading.Thread(target=service.submit, args=(8, 8, bytes(8 * 8 * 3)))
        submit.start()
        self.assertTrue(admission.entered.wait(1))
        cancel = threading.Thread(target=service.cancel)
        cancel.start()
        admission.release.set()
        submit.join(1)
        cancel.join(1)

        self.assertFalse(submit.is_alive())
        self.assertFalse(cancel.is_alive())
        self.assertTrue(service._requests.empty())
        parent.packets.append(b'{"kind":"result","request_id":1,"hits":[]}')
        self.assertIsNone(service.poll())
        self.assertTrue(context.process.terminated)

    def test_close_defers_pipe_close_and_drops_pixels_during_blocked_send(self):
        parent = BlockingSendPipe()
        context = Context(parent)
        service = RecognitionService(Path("/model"), LABELS, _context=context)
        try:
            service.start()
            self.assertTrue(wait_for(lambda: service.ready))
            service.submit(8, 8, bytes(8 * 8 * 3), timeout=1)
            self.assertTrue(parent.blocked.wait(1))
            service.close()
            self.assertFalse(parent.closed)

            parent.release.set()
            self.assertTrue(wait_for(lambda: parent.closed))
            self.assertEqual(len(parent.sent), 1)
            self.assertTrue(context.process.terminated)
        finally:
            parent.release.set()
            service.close()
        self.assertEqual(parent.close_calls, 1)


class RecognitionServiceNativeCanaryTests(unittest.TestCase):
    def test_pinned_model_warmed_worker_returns_synthetic_label_metadata(self):
        model_path = os.environ.get("AFK_GRINDER_TEST_OCR_MODEL_DIR")
        if not model_path:
            self.skipTest("Set AFK_GRINDER_TEST_OCR_MODEL_DIR to run the pinned worker canary.")
        from PIL import Image, ImageDraw, ImageFont

        image = Image.new("RGB", (800, 400), "white")
        draw = ImageDraw.Draw(image)
        draw.text((60, 70), "BANK", fill="black", font=ImageFont.load_default(size=64))
        service = RecognitionService(Path(model_path), {"bank": r"bank"})
        try:
            service.start()
            self.assertTrue(wait_for(lambda: service.ready, timeout=10))
            service.submit(800, 400, image.tobytes("raw", "BGR"))
            cold = poll_until(service, timeout=4)
            service.submit(800, 400, image.tobytes("raw", "BGR"))
            warm = poll_until(service, timeout=2)
        finally:
            service.close()

        for result in (cold, warm):
            self.assertEqual(result.error, "")
            self.assertEqual(tuple(hit.label_id for hit in result.hits), ("bank",))
            self.assertTrue(all(0 <= hit.score <= 1 and len(hit.box) == 4 for hit in result.hits))
