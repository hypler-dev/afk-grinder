"""Native observation process boundaries tested without native operations."""

import json
import queue
import threading
import time
import unittest
from unittest.mock import Mock, patch

from afk_grinder.capture import CapturedWindow
from afk_grinder.capture.service import BackgroundJob, JobResult, MAX_FRAME_BYTES, _read_result, _worker
from afk_grinder.models import Target

TARGET = Target(123, "window", "RobloxPlayer", "com.roblox.RobloxPlayer")


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
            raise OSError("bad message length")
        return packet

    def send_bytes(self, packet):
        self.sent.append(packet)

    def close(self):
        self.closed = True


class CaptureServiceTests(unittest.TestCase):
    def context(self, packets):
        reader, writer = Pipe(packets), Pipe()
        process = Mock(exitcode=0)
        process.is_alive.return_value = False
        context = Mock()
        context.Pipe.return_value = reader, writer
        context.Event.return_value = threading.Event()
        context.Process.return_value = process
        return context, reader, writer, process

    def test_status_result_published_once_after_child_exit(self):
        context, reader, writer, process = self.context([b'{"kind":"sdk","report":{"native_input":false}}'])
        job = BackgroundJob("sdk", _context=context)
        job._thread.join(timeout=1)
        result = job.poll()
        self.assertEqual(result.report, {"native_input": False})
        self.assertIsNone(job.poll())
        self.assertTrue(job.done)
        process.join.assert_called_once()
        self.assertTrue(reader.closed)
        self.assertTrue(writer.closed)

    def test_cancel_drops_already_queued_and_late_frame_results(self):
        context, _, _, _ = self.context([b'{"kind":"sdk","report":{"native_input":false}}'])
        job = BackgroundJob("sdk", _context=context)
        job._thread.join(timeout=1)
        job.cancel()
        self.assertIsNone(job.poll())
        self.assertTrue(job.done)
        self.assertTrue(job._results.empty())

    def test_cancel_discards_frame_finishing_after_cancel(self):
        context, _, _, _ = self.context([])
        reading, release = threading.Event(), threading.Event()
        frame = CapturedWindow(TARGET, "99", (0, 0, 2, 1), (2, 1), "screen", (1, 1),
                               b"\x01\x02\x03" * 2, "BGR8", 10)

        def delayed_result(*args):
            reading.set()
            self.assertTrue(release.wait(1))
            return JobResult(frame=frame)

        with patch("afk_grinder.capture.service._read_result", side_effect=delayed_result):
            job = BackgroundJob("capture", TARGET, _context=context)
            try:
                self.assertTrue(reading.wait(1))
                job.cancel()
            finally:
                release.set()
                job._thread.join(timeout=1)
        self.assertFalse(job._thread.is_alive())
        self.assertTrue(job._results.empty())
        self.assertIsNone(job.poll())

    def test_cancel_and_read_teardown_close_reader_once(self):
        context, reader, _, _ = self.context([])
        reading, release_read = threading.Event(), threading.Event()
        closing, release_close = threading.Event(), threading.Event()
        close_calls = []

        def delayed_result(*args):
            reading.set()
            self.assertTrue(release_read.wait(1))
            return JobResult(report={"native_input": False})

        def delayed_close():
            close_calls.append(True)
            closing.set()
            self.assertTrue(release_close.wait(1))
            reader.closed = True

        reader.close = delayed_close
        with patch("afk_grinder.capture.service._read_result", side_effect=delayed_result):
            job = BackgroundJob("sdk", _context=context)
            try:
                self.assertTrue(reading.wait(1))
                job.cancel()
                self.assertTrue(closing.wait(1))
                release_read.set()
            finally:
                release_close.set()
                job._thread.join(timeout=1)
        self.assertFalse(job._thread.is_alive())
        self.assertEqual(len(close_calls), 1)
        self.assertIsNone(job.poll())

    def test_outer_deadline_never_publishes_success_after_timeout(self):
        context, _, _, _ = self.context([b'{"kind":"sdk","report":{"native_input":false}}'])
        job = BackgroundJob("sdk", _context=context)
        job._thread.join(timeout=1)
        job._deadline = time.monotonic() - 1
        result = job.poll()
        self.assertIn("timed out", result.error)
        self.assertIsNone(result.report)
        self.assertEqual(result.diagnostic.as_ipc(), {
            "code": "timeout", "stage": "worker_deadline", "error_type": "timeout_error",
        })
        self.assertIsNone(job.poll())

    def test_malformed_or_oversized_ipc_and_unexpected_operation_rejected(self):
        for packets, operation in (([b"[]"], "sdk"), ([b"x" * 16385], "sdk"),
                                   ([b'{"kind":"sdk","report":{"native_input":true}}'], "sdk"),
                                   ([b'{"kind":"sdk","report":{"native_input":false}}'], "capture")):
            with self.subTest(operation=operation, first=packets[0][:30]), self.assertRaises((ValueError, OSError)):
                _read_result(Pipe(packets), operation, TARGET)

    def test_frame_roundtrip_has_only_bounded_metadata_and_raw_bytes(self):
        frame = CapturedWindow(TARGET, "99", (0, 0, 2, 1), (2, 1), "screen", (1, 1),
                               b"\x01\x02\x03" * 2, "BGR8", 10)
        pipe = Pipe()
        backend = Mock()
        backend.snapshot.return_value = frame
        with patch("afk_grinder.capture.service.sys.platform", "darwin"), \
             patch("afk_grinder.capture.macos.MacOSCapture", return_value=backend):
            gate = threading.Event()
            gate.set()
            _worker(pipe, "capture", TARGET, gate, time.monotonic() + 1)
        result = _read_result(Pipe(pipe.sent), "capture", TARGET)
        self.assertEqual(result.frame, frame)
        self.assertEqual(len(pipe.sent), 2)
        self.assertNotIn("pixels", json.loads(pipe.sent[0]))
        self.assertLessEqual(len(pipe.sent[1]), MAX_FRAME_BYTES)
        self.assertTrue(pipe.closed)

    def test_failure_packet_preserves_actionable_permission_message(self):
        result = _read_result(Pipe([b'{"kind":"error","error":"Screen Recording permission is required"}']), "capture", TARGET)
        self.assertIn("Screen Recording", result.error)
        self.assertIsNone(result.frame)
        self.assertIsNone(result.diagnostic)

    def test_failure_diagnostic_survives_memory_only_ipc(self):
        result = _read_result(Pipe([
            b'{"kind":"error","error":"Screen Recording permission is required",'
            b'"diagnostic":{"code":"permission","stage":"preflight","error_type":"capture_error"}}'
        ]), "capture", TARGET)

        self.assertEqual(result.error, "Screen Recording permission is required")
        self.assertEqual(result.diagnostic.code, "permission")
        self.assertEqual(result.diagnostic.stage, "preflight")
        self.assertEqual(result.diagnostic.error_type, "capture_error")

    def test_malformed_capture_diagnostics_are_rejected(self):
        headers = (
            b'{"kind":"error","error":"failed","diagnostic":{"code":"other","stage":"preflight","error_type":"capture_error"}}',
            b'{"kind":"error","error":"failed","diagnostic":{"code":"permission","stage":"other","error_type":"capture_error"}}',
            b'{"kind":"error","error":"failed","diagnostic":{"code":"permission","stage":"preflight","error_type":"other"}}',
            b'{"kind":"error","error":"failed","diagnostic":{"code":"permission","stage":"preflight","error_type":"capture_error","detail":"private"}}',
        )
        for header in headers:
            with self.subTest(header=header), self.assertRaisesRegex(ValueError, "diagnostic"):
                _read_result(Pipe([header]), "capture", TARGET)

    def test_unexpected_worker_error_exports_only_allowlisted_diagnostic(self):
        pipe = Pipe()
        backend = Mock()
        backend.snapshot.side_effect = AttributeError("/private/user/window title")
        with patch("afk_grinder.capture.service.sys.platform", "darwin"), \
             patch("afk_grinder.capture.macos.MacOSCapture", return_value=backend):
            gate = threading.Event()
            gate.set()
            _worker(pipe, "capture", TARGET, gate, time.monotonic() + 1)

        header = json.loads(pipe.sent[0])
        self.assertEqual(header["diagnostic"], {
            "code": "unexpected", "stage": "worker", "error_type": "attribute_error",
        })
        self.assertNotIn("private", json.dumps(header["diagnostic"]))
        result = _read_result(Pipe(pipe.sent), "capture", TARGET)
        self.assertEqual(result.diagnostic.error_type, "attribute_error")

    def test_error_or_hung_teardown_never_returns_success(self):
        context, _, _, process = self.context([b'{"kind":"sdk","report":{"native_input":false}}'])
        process.exitcode = 1
        job = BackgroundJob("sdk", _context=context)
        job._thread.join(timeout=1)
        result = job.poll()
        self.assertTrue(result.error)
        self.assertEqual(result.diagnostic.stage, "worker_exit")
        self.assertEqual(result.diagnostic.error_type, "runtime_error")

    def test_ipc_decode_failure_has_safe_parent_stage(self):
        context, _, _, _ = self.context([])
        job = BackgroundJob("capture", TARGET, _context=context)
        job._thread.join(timeout=1)
        result = job.poll()
        self.assertTrue(result.error)
        self.assertEqual(result.diagnostic.as_ipc(), {
            "code": "unexpected", "stage": "ipc_read", "error_type": "unexpected",
        })

    def test_process_start_failure_closes_both_pipes(self):
        context, reader, writer, process = self.context([])
        process.start.side_effect = RuntimeError("spawn failed")
        job = BackgroundJob("sdk", _context=context)
        job._thread.join(timeout=1)
        self.assertIn("Could not start", job.poll().error)
        self.assertTrue(reader.closed and writer.closed)

    def test_blocked_spawn_returns_job_and_deadline_cancels_late_child(self):
        context, reader, writer, process = self.context([])
        starting, release, alive = threading.Event(), threading.Event(), threading.Event()

        def blocked_start():
            starting.set()
            self.assertTrue(release.wait(1))
            alive.set()

        process.start.side_effect = blocked_start
        process.is_alive.side_effect = alive.is_set
        process.terminate.side_effect = alive.clear
        job = BackgroundJob("sdk", _context=context)
        try:
            self.assertTrue(starting.wait(1))
            self.assertTrue(job._thread.is_alive())
            self.assertIsNone(job.poll())
            job._deadline = time.monotonic() - 1
            self.assertIn("timed out", job.poll().error)
            self.assertTrue(job.done)
            self.assertTrue(job._thread.is_alive())
        finally:
            release.set()
            job._thread.join(timeout=1)
        self.assertFalse(job._thread.is_alive())
        process.terminate.assert_called_once()
        self.assertTrue(reader.closed and writer.closed)
        self.assertTrue(job._results.empty())

    def test_child_booted_during_blocked_start_never_receives_native_grant(self):
        context, _, _, process = self.context([])
        starting, release = threading.Event(), threading.Event()
        child_pipe = Pipe()
        child_threads = []

        def blocked_start():
            args = context.Process.call_args.kwargs["args"]
            child = threading.Thread(target=_worker,
                                     args=(child_pipe, *args[1:]), daemon=True)
            child_threads.append(child)
            child.start()
            starting.set()
            self.assertTrue(release.wait(1))

        process.start.side_effect = blocked_start
        with patch("afk_grinder.capture.macos.MacOSCapture") as backend:
            job = BackgroundJob("capture", TARGET, timeout=0.05, _context=context)
            try:
                self.assertTrue(starting.wait(1))
                self.assertFalse(job._start_gate.is_set())
                child_threads[0].join(timeout=1)
                self.assertFalse(child_threads[0].is_alive())
                self.assertTrue(child_pipe.closed)
                # Event timeout wakeups and monotonic clock ticks need not
                # coincide. Test the parent's deadline independently.
                job._deadline = time.monotonic() - 1
                self.assertIn("timed out", job.poll().error)
            finally:
                release.set()
                job._thread.join(timeout=1)
            backend.assert_not_called()
        self.assertFalse(job._start_gate.is_set())
        self.assertEqual(child_pipe.sent, [])

    def test_programmatic_invalid_operation_target_and_deadline_rejected(self):
        for operation, target, timeout in (("shell", None, 1), ("capture", None, 1),
                                           ("sdk", None, float("nan")), ("sdk", None, 16)):
            with self.subTest(operation=operation, timeout=timeout), self.assertRaises(ValueError):
                BackgroundJob(operation, target, timeout=timeout)


if __name__ == "__main__":
    unittest.main()
