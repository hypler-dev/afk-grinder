"""macOS backend using AppKit and Quartz through PyObjC.

API references: GetFrontProcess, GetProcessPID, NSRunningApplication,
AXIsProcessTrusted, CGPreflightListenEventAccess, CGEventSourceKeyState, and
CGEventPost.
"""

from __future__ import annotations

import importlib
import math
import sys
from typing import Any

from afk_grinder.models import BUTTONS, KEYS, Target


class MacOSBackend:
    """Bounded macOS input adapter; never changes application focus or requests consent."""

    _ESCAPE_KEY_CODE = 53
    _KEY_CODES = {
        "w": 13,
        "a": 0,
        "s": 1,
        "d": 2,
        "e": 14,
        "space": 49,
        "up": 126,
        "down": 125,
        "left": 123,
        "right": 124,
    }

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise RuntimeError("macOS backend requires macOS (sys.platform == 'darwin').")
        try:
            self._AppKit = importlib.import_module("AppKit")
            self._Quartz = importlib.import_module("Quartz")
            self._ApplicationServices = importlib.import_module("ApplicationServices")
            self._objc = importlib.import_module("objc")
        except ImportError as error:
            raise RuntimeError(
                "macOS native backend requires PyObjC packages AppKit, Quartz, "
                "ApplicationServices, and objc."
            ) from error
        except Exception as error:
            raise RuntimeError(f"macOS native API initialization failed: {error}") from error

    def foreground(self) -> Target | None:
        """Return live front-process identity without inspecting a window title."""
        try:
            with self._objc.autorelease_pool():
                get_front_process = self._foreground_function("GetFrontProcess")
                status, process_serial_number = get_front_process(None)
                if status != 0:
                    raise RuntimeError(
                        "macOS foreground process query failed: "
                        f"GetFrontProcess returned status {status}."
                    )
                if process_serial_number is None:
                    raise RuntimeError(
                        "macOS foreground process query failed: "
                        "GetFrontProcess returned no process serial number."
                    )

                get_process_pid = self._foreground_function("GetProcessPID")
                status, pid = get_process_pid(process_serial_number, None)
                if status != 0:
                    raise RuntimeError(
                        "macOS foreground process query failed: "
                        f"GetProcessPID returned status {status}."
                    )
                pid = int(pid)
                if pid <= 0:
                    raise RuntimeError(
                        "macOS foreground process query failed: "
                        "GetProcessPID returned an invalid process identifier."
                    )

                resolver_type = getattr(self._AppKit, "NSRunningApplication", None)
                resolver = getattr(resolver_type, "runningApplicationWithProcessIdentifier_", None)
                if not callable(resolver):
                    raise RuntimeError(
                        "macOS foreground identity unavailable: "
                        "NSRunningApplication resolver is unavailable."
                    )
                application = resolver(pid)
                if application is None:
                    raise RuntimeError(
                        "macOS foreground identity unavailable: "
                        f"NSRunningApplication found no process for PID {pid}."
                    )
                resolved_pid = int(application.processIdentifier())
                if resolved_pid != pid:
                    raise RuntimeError(
                        "macOS foreground identity unavailable: "
                        f"NSRunningApplication returned PID {resolved_pid} for queried PID {pid}."
                    )
                bundle_identifier = application.bundleIdentifier()
                executable_url = application.executableURL()
                if not bundle_identifier:
                    raise RuntimeError(
                        "macOS foreground identity unavailable: "
                        "NSRunningApplication returned incomplete process metadata."
                    )
                if executable_url is None:
                    raise RuntimeError(
                        "macOS foreground identity unavailable: "
                        "NSRunningApplication returned incomplete executable metadata."
                    )
                executable_component = executable_url.lastPathComponent()
                if not executable_component:
                    raise RuntimeError(
                        "macOS foreground identity unavailable: "
                        "NSRunningApplication returned incomplete executable metadata."
                    )
                executable = str(executable_component)
                return Target(
                    pid=pid,
                    token=str(pid),
                    executable=executable,
                    identifier=str(bundle_identifier),
                )
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"macOS foreground process query failed: {error}") from error

    def discover_targets(self) -> tuple[Target, ...]:
        """List currently verified Roblox processes without changing focus or permissions."""
        try:
            with self._objc.autorelease_pool():
                resolver_type = getattr(self._AppKit, "NSRunningApplication", None)
                enumerate_applications = getattr(
                    resolver_type, "runningApplicationsWithBundleIdentifier_", None
                )
                if not callable(enumerate_applications):
                    raise RuntimeError(
                        "macOS target discovery unavailable: "
                        "NSRunningApplication bundle enumerator is unavailable."
                    )
                applications = enumerate_applications("com.roblox.RobloxPlayer")
                if applications is None:
                    raise RuntimeError(
                        "macOS target discovery failed: "
                        "NSRunningApplication returned no application list."
                    )

                targets: dict[tuple[int, str, str, str], Target] = {}
                for application in applications:
                    target = self._discovered_target(application)
                    if target is not None:
                        targets[(target.pid, target.token, target.executable, target.identifier)] = target
                return tuple(sorted(targets.values(), key=lambda target: (
                    target.pid,
                    target.token,
                    target.executable,
                    target.identifier,
                )))
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"macOS target discovery failed: {error}") from error

    def _discovered_target(self, candidate: Any) -> Target | None:
        """Re-resolve one enumerated PID before exposing a stable target."""
        try:
            candidate_pid = int(candidate.processIdentifier())
            candidate_terminated = getattr(candidate, "isTerminated", None)
            if candidate_pid <= 0 or not callable(candidate_terminated) or candidate_terminated():
                return None

            resolver_type = getattr(self._AppKit, "NSRunningApplication", None)
            resolver = getattr(resolver_type, "runningApplicationWithProcessIdentifier_", None)
            if not callable(resolver):
                raise RuntimeError(
                    "macOS target discovery unavailable: "
                    "NSRunningApplication resolver is unavailable."
                )
            application = resolver(candidate_pid)
            if application is None:
                return None
            resolved_pid = int(application.processIdentifier())
            terminated = getattr(application, "isTerminated", None)
            if (
                resolved_pid != candidate_pid
                or resolved_pid <= 0
                or not callable(terminated)
                or terminated()
            ):
                return None
            bundle_identifier = application.bundleIdentifier()
            executable_url = application.executableURL()
            if bundle_identifier != "com.roblox.RobloxPlayer" or executable_url is None:
                return None
            executable_component = executable_url.lastPathComponent()
            if not executable_component:
                return None
            return Target(
                pid=resolved_pid,
                token=str(resolved_pid),
                executable=str(executable_component),
                identifier="com.roblox.RobloxPlayer",
            )
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"macOS target discovery identity check failed: {error}") from error

    def readiness(self) -> list[str]:
        """Check existing permissions only; this method never triggers a macOS prompt."""
        problems: list[str] = []
        self._append_permission_problem(
            problems,
            "AXIsProcessTrusted",
            "Accessibility permission is required for native input control.",
            self._ApplicationServices,
        )
        self._append_permission_problem(
            problems,
            "CGPreflightListenEventAccess",
            "Input Monitoring permission is required to read Escape emergency stop.",
            self._Quartz,
        )
        self._append_permission_problem(
            problems,
            "CGPreflightPostEventAccess",
            "Accessibility permission is required to post native input events.",
            self._Quartz,
        )
        self._append_foreground_readiness_problems(problems)
        return problems

    def escape_pressed(self) -> bool:
        """Read physical Escape state. Missing read permission fails closed."""
        self._ensure_escape_readiness()
        try:
            with self._objc.autorelease_pool():
                return bool(
                    self._Quartz.CGEventSourceKeyState(
                        self._Quartz.kCGEventSourceStateHIDSystemState,
                        self._ESCAPE_KEY_CODE,
                    )
                )
        except Exception as error:
            raise RuntimeError(f"macOS Escape state read failed: {error}") from error

    def key_down(self, key: str) -> None:
        self._send_key(key, is_key_up=False)

    def key_up(self, key: str) -> None:
        self._send_key(key, is_key_up=True)

    def mouse_down(self, button: str) -> None:
        self._send_mouse(button, is_mouse_up=False)

    def mouse_down_at(self, button: str, x: float, y: float) -> None:
        """Press ``button`` at a supplied native top-left coordinate."""
        self._validate_button(button)
        self._validate_native_point(x, y)
        self._ensure_input_readiness()
        operation = f"mouse_down_at({button!r}, {x!r}, {y!r})"
        try:
            with self._objc.autorelease_pool():
                event_type, mouse_button = self._mouse_parameters(button, is_mouse_up=False)
                event = self._Quartz.CGEventCreateMouseEvent(
                    None, event_type, (x, y), mouse_button
                )
                self._post_event(event, operation)
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"macOS {operation} failed: {error}") from error

    def mouse_up(self, button: str) -> None:
        self._send_mouse(button, is_mouse_up=True)

    def _send_key(self, key: str, *, is_key_up: bool) -> None:
        self._validate_key(key)
        if is_key_up:
            self._ensure_post_readiness()
        else:
            self._ensure_input_readiness()
        operation = "key_up" if is_key_up else "key_down"
        try:
            with self._objc.autorelease_pool():
                event = self._Quartz.CGEventCreateKeyboardEvent(
                    None, self._KEY_CODES[key], not is_key_up
                )
                self._post_event(event, f"{operation}({key!r})")
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"macOS {operation}({key!r}) failed: {error}") from error

    def _send_mouse(self, button: str, *, is_mouse_up: bool) -> None:
        self._validate_button(button)
        if is_mouse_up:
            self._ensure_post_readiness()
        else:
            self._ensure_input_readiness()
        operation = "mouse_up" if is_mouse_up else "mouse_down"
        try:
            with self._objc.autorelease_pool():
                current_event = self._Quartz.CGEventCreate(None)
                if current_event is None:
                    raise RuntimeError("macOS could not create current-pointer event.")
                location = self._Quartz.CGEventGetLocation(current_event)
                event_type, mouse_button = self._mouse_parameters(button, is_mouse_up)
                event = self._Quartz.CGEventCreateMouseEvent(
                    None, event_type, location, mouse_button
                )
                self._post_event(event, f"{operation}({button!r})")
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"macOS {operation}({button!r}) failed: {error}") from error

    def _post_event(self, event: Any, operation: str) -> None:
        if event is None:
            raise RuntimeError(f"macOS could not create event for {operation}.")
        try:
            self._Quartz.CGEventPost(self._Quartz.kCGHIDEventTap, event)
        except Exception as error:
            raise RuntimeError(f"macOS event post failed for {operation}: {error}") from error

    def _ensure_input_readiness(self) -> None:
        problems = self.readiness()
        if problems:
            raise RuntimeError("macOS native input unavailable: " + " ".join(problems))

    def _ensure_escape_readiness(self) -> None:
        check = getattr(self._Quartz, "CGPreflightListenEventAccess", None)
        if not callable(check):
            raise RuntimeError(
                "macOS Escape state unavailable: CGPreflightListenEventAccess is unavailable."
            )
        try:
            allowed = bool(check())
        except Exception as error:
            raise RuntimeError(f"macOS Escape permission check failed: {error}") from error
        if not allowed:
            raise RuntimeError(
                "macOS Escape state unavailable: Input Monitoring permission is required."
            )

    def _ensure_post_readiness(self) -> None:
        problems: list[str] = []
        self._append_permission_problem(
            problems,
            "AXIsProcessTrusted",
            "Accessibility permission is required for native input control.",
            self._ApplicationServices,
        )
        self._append_permission_problem(
            problems,
            "CGPreflightPostEventAccess",
            "Accessibility permission is required to post native input events.",
            self._Quartz,
        )
        if problems:
            raise RuntimeError("macOS native input unavailable: " + " ".join(problems))

    def _append_permission_problem(
        self, problems: list[str], check_name: str, message: str, module: Any
    ) -> None:
        check = getattr(module, check_name, None)
        if not callable(check):
            problems.append(f"{check_name} is unavailable; cannot verify permission. {message}")
            return
        try:
            if not bool(check()):
                problems.append(message)
        except Exception as error:
            problems.append(f"{check_name} failed: {error}. {message}")

    def _append_foreground_readiness_problems(self, problems: list[str]) -> None:
        for function_name in ("GetFrontProcess", "GetProcessPID"):
            if not callable(getattr(self._ApplicationServices, function_name, None)):
                problems.append(
                    f"{function_name} is unavailable; cannot verify the live foreground process."
                )
        resolver_type = getattr(self._AppKit, "NSRunningApplication", None)
        resolver = getattr(resolver_type, "runningApplicationWithProcessIdentifier_", None)
        if not callable(resolver):
            problems.append(
                "NSRunningApplication resolver is unavailable; "
                "cannot verify foreground process identity."
            )

    def _foreground_function(self, function_name: str) -> Any:
        function = getattr(self._ApplicationServices, function_name, None)
        if not callable(function):
            raise RuntimeError(
                "macOS foreground process unavailable: "
                f"{function_name} is unavailable."
            )
        return function

    def _mouse_parameters(self, button: str, is_mouse_up: bool) -> tuple[Any, Any]:
        if button == "left":
            event_type = (
                self._Quartz.kCGEventLeftMouseUp
                if is_mouse_up
                else self._Quartz.kCGEventLeftMouseDown
            )
            return event_type, self._Quartz.kCGMouseButtonLeft
        event_type = (
            self._Quartz.kCGEventRightMouseUp
            if is_mouse_up
            else self._Quartz.kCGEventRightMouseDown
        )
        return event_type, self._Quartz.kCGMouseButtonRight

    @staticmethod
    def _validate_key(key: str) -> None:
        if key not in KEYS:
            raise ValueError(f"Unsupported key {key!r}; allowed keys: {', '.join(sorted(KEYS))}.")

    @staticmethod
    def _validate_button(button: str) -> None:
        if button not in BUTTONS:
            raise ValueError(
                f"Unsupported mouse button {button!r}; allowed buttons: {', '.join(sorted(BUTTONS))}."
            )

    @staticmethod
    def _validate_native_point(x: float, y: float) -> None:
        for name, value in (("x", x), ("y", y)):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"Native mouse coordinate {name} must be a finite number.")
            if not math.isfinite(value):
                raise ValueError(f"Native mouse coordinate {name} must be finite.")
