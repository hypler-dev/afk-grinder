"""Disposable capture/SDK processes with memory-only, bounded frame IPC.

The UI polls a queue. Native calls, pipe reads and process teardown never run
on Tk's event thread. Messages contain JSON and BGR bytes, not pickled results.
"""

from dataclasses import dataclass, replace
import json
import math
import multiprocessing
from multiprocessing.connection import Connection
import queue
import sys
import threading
import time
from typing import Any

from afk_grinder.models import Target
from afk_grinder.recognition.maa_adapter import SDKError
from . import CaptureDiagnostic, CaptureError, CapturedWindow, capture_error_type

MAX_FRAME_BYTES = 16_000_000 * 3
MAX_HEADER_BYTES = 16_384
OPTIONAL_SDK_UNAVAILABLE_MESSAGE = "Recognition is optional. Install the locked recognition extra first."
GENERIC_WORKER_ERROR_MESSAGE = "Preview or SDK check failed. No input was sent."


@dataclass(frozen=True)
class JobResult:
    """One parent-owned job result.

    Timing samples are taken only by the parent after IPC read and successful
    child teardown. They are never child IPC fields or exported UI state.
    """

    frame: CapturedWindow | None = None
    report: dict[str, Any] | None = None
    error: str = ""
    diagnostic: CaptureDiagnostic | None = None
    received_at: float | None = None
    completed_at: float | None = None


def _worker(connection: Connection, operation: str, target: Target | None,
            start_gate: Any, deadline: float) -> None:
    """Only fixed application operations are accepted; no plugins or pipelines."""
    try:
        # A child may boot before Process.start returns a signalable handle.
        # Do not import or touch native APIs until the parent grants this gate.
        if not start_gate.wait(timeout=max(0, deadline - time.monotonic())):
            return
        if time.monotonic() >= deadline:
            return
        if operation == "capture" and target is not None and target.is_roblox:
            if sys.platform == "darwin":
                from .macos import MacOSCapture

                backend = MacOSCapture()
            elif sys.platform == "win32":
                from .windows import WindowsCapture

                backend = WindowsCapture()
            else:
                raise RuntimeError("Window capture requires Windows or macOS.")
            if time.monotonic() >= deadline:
                return
            frame = backend.snapshot(target)
            header = {"kind": "frame", "window_id": frame.window_id,
                      "native_rect": frame.native_rect, "physical_size": frame.physical_size,
                      "monitor_id": frame.monitor_id, "scale": frame.scale,
                      "captured_at": frame.captured_at, "region_kind": frame.region_kind,
                      "content_verified": frame.content_verified,
                      "capture_expiry_stage": frame.capture_expiry_stage}
            connection.send_bytes(json.dumps(header, allow_nan=False).encode("utf-8"))
            connection.send_bytes(frame.pixels)
        elif operation == "sdk":
            from afk_grinder.recognition.maa_adapter import probe_sdk

            report = probe_sdk()
            connection.send_bytes(json.dumps({"kind": "sdk", "report": report}, allow_nan=False).encode("utf-8"))
        else:
            raise ValueError("Unsupported observation operation.")
    except Exception as error:
        try:
            diagnostic = error.diagnostic if isinstance(error, CaptureError) else CaptureDiagnostic(
                code="unexpected", stage="worker", error_type=capture_error_type(error)
            )
            message = (
                OPTIONAL_SDK_UNAVAILABLE_MESSAGE
                if operation == "sdk" and isinstance(error, SDKError)
                and str(error) == OPTIONAL_SDK_UNAVAILABLE_MESSAGE
                else GENERIC_WORKER_ERROR_MESSAGE
            )
            connection.send_bytes(json.dumps({
                "kind": "error", "error": message,
                "diagnostic": diagnostic.as_ipc(),
            }).encode("utf-8"))
        except (OSError, EOFError, BrokenPipeError):
            pass
    finally:
        connection.close()


def _read_result(connection: Connection, operation: str, target: Target | None) -> JobResult:
    header = json.loads(connection.recv_bytes(MAX_HEADER_BYTES).decode("utf-8"))
    if not isinstance(header, dict):
        raise ValueError("Invalid observation header.")
    if header.get("kind") == "error":
        message = header.get("error")
        if not isinstance(message, str) or len(message) > 500:
            raise ValueError("Invalid observation error.")
        if "diagnostic" not in header:
            if set(header) != {"kind", "error"}:
                raise ValueError("Invalid observation error.")
            return JobResult(error=message)
        if set(header) != {"kind", "error", "diagnostic"}:
            raise ValueError("Invalid observation error.")
        raw_diagnostic = header["diagnostic"]
        if not isinstance(raw_diagnostic, dict) or set(raw_diagnostic) != {"code", "stage", "error_type"}:
            raise ValueError("Invalid capture diagnostic.")
        if not all(isinstance(value, str) for value in raw_diagnostic.values()):
            raise ValueError("Invalid capture diagnostic.")
        try:
            diagnostic = CaptureDiagnostic(**raw_diagnostic)
        except ValueError as error:
            raise ValueError("Invalid capture diagnostic.") from error
        return JobResult(error=message, diagnostic=diagnostic)
    if operation == "sdk" and header.get("kind") == "sdk":
        report = header.get("report")
        if not isinstance(report, dict) or report.get("native_input") is not False:
            raise ValueError("Invalid SDK observation report.")
        return JobResult(report=report)
    if operation != "capture" or target is None or header.get("kind") != "frame":
        raise ValueError("Unexpected observation operation result.")
    expected = {"kind", "window_id", "native_rect", "physical_size", "monitor_id", "scale",
                "captured_at", "region_kind", "content_verified"}
    if set(header) not in (expected, expected | {"capture_expiry_stage"}):
        raise ValueError("Unexpected frame metadata.")
    for field in ("window_id", "monitor_id"):
        if not isinstance(header[field], str) or not 0 < len(header[field]) <= 128:
            raise ValueError("Invalid capture identity.")
    frame = CapturedWindow(target=target, window_id=header["window_id"],
                          native_rect=tuple(header["native_rect"]),
                          physical_size=tuple(header["physical_size"]), monitor_id=header["monitor_id"],
                          scale=tuple(header["scale"]), pixels=connection.recv_bytes(MAX_FRAME_BYTES),
                          format="BGR8", captured_at=header["captured_at"],
                          region_kind=header["region_kind"], content_verified=header["content_verified"],
                          capture_expiry_stage=header.get("capture_expiry_stage"))
    return JobResult(frame=frame)


class BackgroundJob:
    """One cancellable native observation with an outer process deadline.

    ``poll`` is nonblocking and returns one result at most. Cancel/Close drops
    queued and late results immediately; process cleanup runs off the UI thread.
    """

    def __init__(self, operation: str, target: Target | None = None, *, timeout: float = 15.0,
                 _context: Any = None):
        if operation not in {"capture", "sdk"}:
            raise ValueError("Only capture or SDK diagnostics are supported.")
        if operation == "capture" and (target is None or not target.is_roblox):
            raise ValueError("An explicitly bound Roblox process is required.")
        if not math.isfinite(timeout) or not 0 < timeout <= 15:
            raise ValueError("Observation deadline must be at most 15 seconds.")
        self._deadline = time.monotonic() + timeout
        self._finished = False
        self._cancelled = threading.Event()
        self._result_lock = threading.Lock()
        self._cleanup_lock = threading.Lock()
        self._reader_close_lock = threading.Lock()
        self._results: queue.Queue[JobResult] = queue.Queue(maxsize=1)
        context = _context or multiprocessing.get_context("spawn")
        reader, writer = context.Pipe(duplex=False)
        self._reader = reader
        self._start_gate = context.Event()
        self._process = context.Process(target=_worker,
                                        args=(writer, operation, target, self._start_gate, self._deadline),
                                        daemon=True)
        self._thread = threading.Thread(target=self._launch, args=(writer, operation, target), daemon=True)
        self._thread.start()

    def _launch(self, writer: Connection, operation: str, target: Target | None) -> None:
        try:
            self._process.start()
        except Exception:
            self._close_reader()
            self._publish(JobResult(error="Could not start preview or SDK check. No input was sent."))
        else:
            writer.close()
            with self._result_lock:
                permitted = not self._cancelled.is_set() and time.monotonic() < self._deadline
                if permitted:
                    self._start_gate.set()
            if not permitted:
                self._terminate()
            else:
                self._read(operation, target)
        finally:
            writer.close()

    @property
    def done(self) -> bool:
        with self._result_lock:
            return self._finished

    def _close_reader(self) -> None:
        # Connection.close is not thread-safe. Cancellation and normal read
        # teardown must not close the same descriptor concurrently.
        with self._reader_close_lock:
            if not self._reader.closed:
                self._reader.close()

    def _publish(self, result: JobResult) -> None:
        with self._result_lock:
            if not self._cancelled.is_set():
                self._results.put_nowait(result)

    def _read(self, operation: str, target: Target | None) -> None:
        stage = "ipc_read"
        try:
            result = _read_result(self._reader, operation, target)
            received_at = time.monotonic()
            stage = "worker_exit"
            # Do not publish success until native destructors have exited too.
            self._process.join(timeout=max(0, self._deadline - time.monotonic()))
            if self._process.is_alive():
                raise TimeoutError("Observation process did not finish before its deadline.")
            if self._process.exitcode != 0:
                raise RuntimeError("Observation process exited unsuccessfully.")
            result = replace(result, received_at=received_at, completed_at=time.monotonic())
        except Exception as error:
            result = JobResult(error="Preview or SDK check failed. No input was sent.",
                               diagnostic=CaptureDiagnostic(
                                   code="timeout" if isinstance(error, TimeoutError) else "unexpected",
                                   stage=stage, error_type=capture_error_type(error),
                               ))
        finally:
            self._close_reader()
            if self._process.is_alive():
                self._terminate()
        self._publish(result)

    def poll(self) -> JobResult | None:
        with self._result_lock:
            if self._finished:
                return None
            timed_out = time.monotonic() >= self._deadline
            if not timed_out:
                try:
                    result = self._results.get_nowait()
                except queue.Empty:
                    return None
                self._finish_locked()
                return result
            self._finish_locked()
        threading.Thread(target=self._terminate, daemon=True).start()
        return JobResult(error="Preview or SDK check timed out. No input was sent.",
                         diagnostic=CaptureDiagnostic(code="timeout", stage="worker_deadline",
                                                      error_type="timeout_error"))

    def _finish_locked(self) -> None:
        self._finished = True
        self._cancelled.set()
        while True:
            try:
                self._results.get_nowait()
            except queue.Empty:
                break

    def cancel(self) -> None:
        with self._result_lock:
            if self._finished:
                return
            self._finish_locked()
        threading.Thread(target=self._terminate, daemon=True).start()

    def _terminate(self) -> None:
        with self._cleanup_lock:
            try:
                if self._process.is_alive():
                    self._process.terminate()
                    self._process.join(timeout=0.2)
                if self._process.is_alive():
                    self._process.kill()
                    self._process.join(timeout=0.2)
            finally:
                self._close_reader()
