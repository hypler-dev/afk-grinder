"""Pinned MaaFramework boundary with no native input or screen capture path.

Native calls and destructors can block. Run the diagnostic in its disposable
subprocess; polling a job alone is not a hard native-call timeout.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from typing import Any

PINNED_MAA_VERSION = "5.14.3"
MAA_SOURCE_REVISION = "8963191215ca49d6b037802acd07d20a4213160a"
FRAME_CACHE_LIMIT = 2
REPLACEMENT_PROBE = "afk-grinder-sdk-replacement-v1"


class SDKError(RuntimeError):
    """The optional recognition SDK is unavailable or failed closed."""


def wait_for_job(job: Any, timeout: float = 2.0) -> None:
    """Poll SDK status without using its unbounded Job.wait method."""
    if not math.isfinite(timeout) or not 0 < timeout <= 5:
        raise ValueError("SDK job timeout must be finite and at most five seconds.")
    deadline = time.monotonic() + timeout
    while True:
        if job.done:
            if not job.succeeded:
                raise SDKError("SDK operation failed.")
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SDKError("SDK operation exceeded its deadline.")
        time.sleep(min(0.01, remaining))


def read_only_controller_type(base: type) -> type:
    """Adapt only our in-memory frames; every input callback rejects requests."""

    class ReadOnlyController(base):
        def __init__(self, frame: Any):
            self._frame = frame
            super().__init__()

        def connect(self) -> bool:
            return True

        def connected(self) -> bool:
            return True

        def request_uuid(self) -> str:
            return "afk-grinder-recognition-only"

        def get_features(self) -> int:
            return 0

        def screencap(self) -> Any:
            return self._frame.copy()

        def start_app(self, intent: str) -> bool:
            return False

        def stop_app(self, intent: str) -> bool:
            return False

        def click(self, x: int, y: int) -> bool:
            return False

        def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int) -> bool:
            return False

        def touch_down(self, contact: int, x: int, y: int, pressure: int) -> bool:
            return False

        def touch_move(self, contact: int, x: int, y: int, pressure: int) -> bool:
            return False

        def touch_up(self, contact: int) -> bool:
            return False

        def click_key(self, keycode: int) -> bool:
            return False

        def input_text(self, text: str) -> bool:
            return False

        def key_down(self, keycode: int) -> bool:
            return False

        def key_up(self, keycode: int) -> bool:
            return False

        def scroll(self, dx: int, dy: int) -> bool:
            return False

        def relative_move(self, dx: int, dy: int) -> bool:
            return False

        def shell(self, cmd: str, timeout: int) -> None:
            return None

    return ReadOnlyController


def _probe_replacement_marker(library: Any) -> str:
    """Check the inert export in the already loaded private test library."""
    import ctypes

    try:
        marker = library.framework().AfkGrinderReplacementProbe
        marker.argtypes = []
        marker.restype = ctypes.c_char_p
        value = marker()
    except (AttributeError, OSError, TypeError) as error:
        raise SDKError("Private SDK replacement marker is unavailable.") from error
    if value != REPLACEMENT_PROBE.encode("ascii"):
        raise SDKError("Private SDK replacement marker did not match.")
    return REPLACEMENT_PROBE


def probe_sdk(*, require_replacement: bool = False) -> dict[str, Any]:
    """Exercise real lifecycle on a synthetic frame, without OS controllers.

    This function belongs in the disposable diagnostic process, never in the
    UI or live input worker. It does not import Toolkit or load resource packs.
    """
    if type(require_replacement) is not bool:
        raise SDKError("SDK replacement diagnostic mode must be a boolean.")
    if "MAAFW_BINARY_PATH" in os.environ:
        raise SDKError("Remove MAAFW_BINARY_PATH; external SDK overrides are disabled.")
    try:
        version = importlib.metadata.version("MaaFw").removeprefix("v")
    except importlib.metadata.PackageNotFoundError as exc:
        raise SDKError("Recognition is optional. Install the locked recognition extra first.") from exc
    if version != PINNED_MAA_VERSION:
        raise SDKError(f"Expected MaaFw {PINNED_MAA_VERSION}; found {version}.")
    if importlib.util.find_spec("maa") is None:
        raise SDKError("Recognition is optional. Install the locked recognition extra first.")
    try:
        library = importlib.import_module("maa.library").Library
        tasker_type = importlib.import_module("maa.tasker").Tasker
        resource_type = importlib.import_module("maa.resource").Resource
        controller_base = importlib.import_module("maa.controller").CustomController
        definitions = importlib.import_module("maa.define")
        numpy = importlib.import_module("numpy")
        native_version = library.version().removeprefix("v")
        if native_version != PINNED_MAA_VERSION:
            raise SDKError(f"Expected native SDK {PINNED_MAA_VERSION}; found {native_version}.")
        tasker = tasker_type()  # Initializes the pinned binding's global option signatures.
        settings = (
            ("set_log_dir", ""),
            ("set_save_draw", False),
            ("set_save_on_error", False),
            ("set_debug_mode", False),
            ("set_stdout_level", definitions.LoggingLevelEnum.Off),
            ("set_reco_image_cache_limit", FRAME_CACHE_LIMIT),
        )
        for name, value in settings:
            if not getattr(tasker_type, name)(value):
                raise SDKError(f"SDK refused required option {name}.")
        resource = resource_type()
        if not resource.set_cpu():
            raise SDKError("SDK refused CPU-only resource configuration.")
        controller = read_only_controller_type(controller_base)(numpy.zeros((2, 2, 3), dtype=numpy.uint8))
        wait_for_job(controller.post_connection())
        if not tasker.bind(resource, controller):
            raise SDKError("SDK refused recognition-only controller binding.")
        wait_for_job(tasker.post_stop())
        report = {
            "sdk_version": version,
            "native_version": native_version,
            "source_revision": MAA_SOURCE_REVISION,
            "cpu_only": True,
            "frame_cache_limit": FRAME_CACHE_LIMIT,
            "persistent_images": False,
            "persistent_logs": False,
            "native_input": False,
            "capture_source": "synthetic",
            "custom_controller": "input callbacks disabled",
            "cancellation": "passed",
        }
        if require_replacement:
            report["replacement_probe"] = _probe_replacement_marker(library)
        return report
    except SDKError:
        raise
    except Exception as exc:
        raise SDKError(f"SDK initialization failed ({type(exc).__name__}).") from exc


def diagnostic(timeout: float = 15.0) -> dict[str, Any]:
    """Bound SDK loading, execution, and native teardown with process isolation."""
    if not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ValueError("SDK diagnostic deadline must be at most 30 seconds.")
    command = [sys.executable]
    if not getattr(sys, "frozen", False):
        command += ["-m", "afk_grinder"]
    # Windows windowed executables have no stdout/stderr. A private, temporary
    # status file works in both source and frozen apps; it never contains pixels.
    with tempfile.TemporaryDirectory(prefix="afk-grinder-sdk-") as directory:
        report_path = Path(directory) / "report.json"
        command += ["--sdk-worker", "--sdk-report", str(report_path)]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        except subprocess.TimeoutExpired as exc:
            raise SDKError("SDK diagnostic timed out; its process was terminated.") from exc
        try:
            if report_path.is_symlink() or report_path.stat().st_size > 4096:
                raise ValueError("Invalid SDK report file")
            payload = json.loads(report_path.read_text(encoding="utf-8"))
            if result.returncode or payload.get("ok") is not True:
                message = payload.get("error", "SDK diagnostic failed; no input was enabled.")
                if not isinstance(message, str) or len(message) > 500:
                    raise ValueError("Invalid SDK error report")
                raise SDKError(message)
            report = payload["report"]
            if not isinstance(report, dict) or report.get("native_input") is not False:
                raise ValueError("Invalid SDK report")
            return report
        except SDKError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
            raise SDKError("SDK diagnostic returned an invalid report.") from exc
