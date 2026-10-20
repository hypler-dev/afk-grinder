"""Adapter-only checks using fake native modules. No OS input is sent."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afk_grinder.backends import create_backend
from afk_grinder.backends.macos import MacOSBackend
from afk_grinder.backends.windows import WindowsBackend


class FakeObjC:
    @staticmethod
    def autorelease_pool():
        return nullcontext()


class FakeApplicationServices:
    def __init__(self, trusted: bool = True) -> None:
        self.trusted = trusted
        self.front_process_status = 0
        self.process_pid_status = 0
        self.front_process: object | None = "front"
        self.process_ids: dict[object, int] = {"front": 101}

    def AXIsProcessTrusted(self) -> bool:
        return self.trusted

    def GetFrontProcess(self, unused) -> tuple[int, object | None]:
        return self.front_process_status, self.front_process

    def GetProcessPID(self, process_serial_number, unused) -> tuple[int, int | None]:
        return self.process_pid_status, self.process_ids.get(process_serial_number)


class FakeExecutableURL:
    def __init__(self, name: str | None) -> None:
        self.name = name

    def lastPathComponent(self) -> str | None:
        return self.name


class FakeRunningApplication:
    def __init__(
        self,
        pid: int,
        *,
        bundle_identifier: str | None = "com.roblox.RobloxPlayer",
        executable: str | None = "RobloxPlayer",
    ) -> None:
        self.pid = pid
        self.bundle_identifier = bundle_identifier
        self.executable = executable

    def processIdentifier(self) -> int:
        return self.pid

    def bundleIdentifier(self) -> str | None:
        return self.bundle_identifier

    def executableURL(self) -> FakeExecutableURL | None:
        return None if self.executable is None else FakeExecutableURL(self.executable)


class FakeRunningApplicationResolver:
    def __init__(self, applications: dict[int, FakeRunningApplication]) -> None:
        self.applications = applications

    def runningApplicationWithProcessIdentifier_(self, pid: int) -> FakeRunningApplication | None:
        return self.applications.get(pid)


class TrapWorkspace:
    @staticmethod
    def sharedWorkspace():
        raise AssertionError("NSWorkspace must not be used for foreground process reads")


class FakeAppKit:
    def __init__(self, applications: dict[int, FakeRunningApplication]) -> None:
        self.NSRunningApplication = FakeRunningApplicationResolver(applications)
        self.NSWorkspace = TrapWorkspace


class FakeQuartz:
    kCGHIDEventTap = 1
    kCGEventSourceStateHIDSystemState = 2
    kCGEventLeftMouseDown = 3
    kCGEventLeftMouseUp = 4
    kCGEventRightMouseDown = 5
    kCGEventRightMouseUp = 6
    kCGMouseButtonLeft = 0
    kCGMouseButtonRight = 1

    def __init__(self, *, listen: bool = True, post: bool = True) -> None:
        self.listen = listen
        self.post = post
        self.keyboard_event: object | None = object()
        self.mouse_event: object | None = object()
        self.mouse_event_requests: list[tuple[object, object, object, object]] = []
        self.posted: list[object] = []
        self.post_error: Exception | None = None
        self.escape = False
        self.escape_error: Exception | None = None

    def CGPreflightListenEventAccess(self) -> bool:
        return self.listen

    def CGPreflightPostEventAccess(self) -> bool:
        return self.post

    def CGEventSourceKeyState(self, source, key_code):
        if self.escape_error:
            raise self.escape_error
        if key_code != 53:
            raise AssertionError("Only Escape may be queried")
        return self.escape

    def CGEventCreateKeyboardEvent(self, source, key_code, down):
        return self.keyboard_event

    def CGEventCreateMouseEvent(self, source, event_type, location, mouse_button):
        self.mouse_event_requests.append((source, event_type, location, mouse_button))
        return self.mouse_event

    def CGEventPost(self, tap, event) -> None:
        if self.post_error is not None:
            raise self.post_error
        self.posted.append(event)


def fake_macos_backend(
    *, listen: bool = True, post: bool = True, trusted: bool = True
) -> tuple[MacOSBackend, FakeQuartz, FakeApplicationServices, FakeAppKit]:
    backend = object.__new__(MacOSBackend)
    quartz = FakeQuartz(listen=listen, post=post)
    backend._Quartz = quartz
    application_services = FakeApplicationServices(trusted)
    app_kit = FakeAppKit({101: FakeRunningApplication(101)})
    backend._ApplicationServices = application_services
    backend._AppKit = app_kit
    backend._objc = FakeObjC()
    return backend, quartz, application_services, app_kit


class MacOSBackendTests(unittest.TestCase):
    def test_mouse_down_at_posts_exact_supplied_point(self) -> None:
        backend, quartz, _, _ = fake_macos_backend()

        backend.mouse_down_at("right", 12.5, 99.25)

        self.assertEqual(
            quartz.mouse_event_requests,
            [(None, quartz.kCGEventRightMouseDown, (12.5, 99.25), quartz.kCGMouseButtonRight)],
        )
        self.assertEqual(quartz.posted, [quartz.mouse_event])

    def test_mouse_down_at_rejects_invalid_values_before_native_event(self) -> None:
        backend, quartz, _, _ = fake_macos_backend()

        for button, x, y in (("middle", 1.0, 2.0), ("left", True, 2.0), ("left", 1.0, float("nan"))):
            with self.subTest(button=button, x=x, y=y):
                with self.assertRaises(ValueError):
                    backend.mouse_down_at(button, x, y)

        self.assertEqual(quartz.mouse_event_requests, [])
        self.assertEqual(quartz.posted, [])

    def test_escape_state_and_fail_closed_errors(self) -> None:
        backend, quartz, _, _ = fake_macos_backend()
        self.assertFalse(backend.escape_pressed())
        quartz.escape = True
        self.assertTrue(backend.escape_pressed())
        quartz.listen = False
        with self.assertRaisesRegex(RuntimeError, "Input Monitoring"):
            backend.escape_pressed()
        quartz.listen = True
        quartz.escape_error = OSError("Native read failed")
        with self.assertRaisesRegex(RuntimeError, "Escape state read failed"):
            backend.escape_pressed()

    def test_readiness_reports_denied_preflights(self) -> None:
        backend, _, _, _ = fake_macos_backend(listen=False, post=False, trusted=False)

        problems = backend.readiness()

        self.assertEqual(len(problems), 3)
        self.assertTrue(any("Accessibility permission" in problem for problem in problems))
        self.assertTrue(any("Input Monitoring permission" in problem for problem in problems))

    def test_missing_listen_permission_blocks_down_but_not_up(self) -> None:
        backend, quartz, _, _ = fake_macos_backend(listen=False)

        with self.assertRaisesRegex(RuntimeError, "Input Monitoring permission"):
            backend.key_down("w")
        backend.key_up("w")

        self.assertEqual(len(quartz.posted), 1)

    def test_none_and_native_post_errors_are_explicit(self) -> None:
        backend, quartz, _, _ = fake_macos_backend()
        quartz.keyboard_event = None
        with self.assertRaisesRegex(RuntimeError, "could not create event"):
            backend.key_down("w")

        quartz.keyboard_event = object()
        quartz.post_error = OSError("native post failure")
        with self.assertRaisesRegex(RuntimeError, "event post failed"):
            backend.key_down("w")

    def test_foreground_uses_live_pid_on_same_backend_and_worker_thread(self) -> None:
        backend, _, application_services, app_kit = fake_macos_backend()
        app_kit.NSRunningApplication.applications[202] = FakeRunningApplication(
            202,
            bundle_identifier="com.example.other",
            executable="OtherApp",
        )

        first = backend.foreground()
        application_services.front_process = "next"
        application_services.process_ids["next"] = 202
        result: list[object] = []
        worker = threading.Thread(target=lambda: result.append(backend.foreground()))
        worker.start()
        worker.join()

        self.assertEqual(first.pid, 101)
        self.assertEqual(result[0].pid, 202)
        self.assertEqual(result[0].identifier, "com.example.other")

    def test_foreground_native_query_errors_fail_closed(self) -> None:
        backend, _, application_services, _ = fake_macos_backend()
        application_services.front_process_status = -1
        with self.assertRaisesRegex(RuntimeError, "GetFrontProcess returned status -1"):
            backend.foreground()

        application_services.front_process_status = 0
        application_services.process_pid_status = -2
        with self.assertRaisesRegex(RuntimeError, "GetProcessPID returned status -2"):
            backend.foreground()

    def test_foreground_identity_errors_fail_closed(self) -> None:
        backend, _, application_services, app_kit = fake_macos_backend()
        app_kit.NSRunningApplication.applications[101] = FakeRunningApplication(
            101, bundle_identifier=None
        )
        with self.assertRaisesRegex(RuntimeError, "incomplete process metadata"):
            backend.foreground()

        app_kit.NSRunningApplication.applications[101] = FakeRunningApplication(999)
        with self.assertRaisesRegex(RuntimeError, "returned PID 999 for queried PID 101"):
            backend.foreground()

        application_services.process_ids["front"] = 303
        with self.assertRaisesRegex(RuntimeError, "found no process for PID 303"):
            backend.foreground()

    def test_foreground_missing_executable_metadata_fails_closed(self) -> None:
        backend, _, _, app_kit = fake_macos_backend()
        application = app_kit.NSRunningApplication.applications[101]
        application.executable = None
        with self.assertRaisesRegex(RuntimeError, "incomplete executable metadata"):
            backend.foreground()

        application.executableURL = lambda: FakeExecutableURL(None)
        with self.assertRaisesRegex(RuntimeError, "incomplete executable metadata"):
            backend.foreground()

        application.executableURL = lambda: FakeExecutableURL("")
        with self.assertRaisesRegex(RuntimeError, "incomplete executable metadata"):
            backend.foreground()

    def test_missing_foreground_functions_and_resolver_fail_closed(self) -> None:
        backend, _, application_services, app_kit = fake_macos_backend()
        application_services.GetFrontProcess = None
        application_services.GetProcessPID = None
        app_kit.NSRunningApplication = None

        problems = backend.readiness()

        self.assertTrue(any("GetFrontProcess is unavailable" in problem for problem in problems))
        self.assertTrue(any("GetProcessPID is unavailable" in problem for problem in problems))
        self.assertTrue(any("NSRunningApplication resolver is unavailable" in problem for problem in problems))
        with self.assertRaisesRegex(RuntimeError, "GetFrontProcess is unavailable"):
            backend.foreground()


class WindowsBackendTests(unittest.TestCase):
    def _positioned_backend(self, metrics: dict[int, int] | None = None):
        backend = object.__new__(WindowsBackend)
        captured: list[tuple[object, str]] = []
        contexts: list[object] = []

        class User32:
            def SetThreadDpiAwarenessContext(self, context):
                contexts.append(context)
                return 101 if context == -4 else 202

            def GetSystemMetrics(self, metric):
                return (metrics or {76: -100, 77: -50, 78: 300, 79: 200})[metric]

        class Input:
            def __init__(self) -> None:
                self.type = 0
                self.mi = None

        backend._user32 = User32()
        backend._INPUT = Input
        backend._MOUSEINPUT = lambda *values: values
        backend._send_input = lambda record, operation: captured.append((record, operation))
        return backend, captured, contexts

    def test_mouse_down_at_normalizes_virtual_desktop_edges_and_restores_context(self) -> None:
        backend, captured, contexts = self._positioned_backend()

        backend.mouse_down_at("left", -100.0, -50.0)
        backend.mouse_down_at("right", 199.0, 149.0)

        self.assertEqual(captured[0][0].mi[:2], (0, 0))
        self.assertEqual(captured[1][0].mi[:2], (65535, 65535))
        expected_flags = (
            backend._MOUSEEVENTF_MOVE
            | backend._MOUSEEVENTF_ABSOLUTE
            | backend._MOUSEEVENTF_VIRTUALDESK
        )
        self.assertEqual(captured[0][0].mi[3], expected_flags | backend._MOUSEEVENTF_LEFTDOWN)
        self.assertEqual(captured[1][0].mi[3], expected_flags | backend._MOUSEEVENTF_RIGHTDOWN)
        self.assertEqual(contexts, [-4, 101, -4, 101])

    def test_mouse_down_at_restores_context_after_metric_error_and_sends_no_event(self) -> None:
        backend, captured, contexts = self._positioned_backend()

        def metric_failure(metric):
            raise OSError("bad metric")

        backend._user32.GetSystemMetrics = metric_failure

        with self.assertRaisesRegex(RuntimeError, "GetSystemMetrics failed"):
            backend.mouse_down_at("left", 1.0, 1.0)

        self.assertEqual(contexts, [-4, 101])
        self.assertEqual(captured, [])

    def test_mouse_down_at_fails_closed_for_missing_context_and_invalid_bounds(self) -> None:
        backend, captured, contexts = self._positioned_backend()
        backend._user32.SetThreadDpiAwarenessContext = None

        with self.assertRaisesRegex(RuntimeError, "SetThreadDpiAwarenessContext is unavailable"):
            backend.mouse_down_at("left", 1.0, 1.0)

        self.assertEqual(contexts, [])
        self.assertEqual(captured, [])

        backend, captured, contexts = self._positioned_backend()
        with self.assertRaisesRegex(ValueError, "outside the virtual desktop"):
            backend.mouse_down_at("left", -101.0, -50.0)

        self.assertEqual(contexts, [-4, 101])
        self.assertEqual(captured, [])

    def test_mouse_down_at_rejects_invalid_values_without_native_calls(self) -> None:
        backend, captured, contexts = self._positioned_backend()

        for button, x, y in (("middle", 1.0, 2.0), ("left", True, 2.0), ("left", 1.0, float("inf"))):
            with self.subTest(button=button, x=x, y=y):
                with self.assertRaises(ValueError):
                    backend.mouse_down_at(button, x, y)

        self.assertEqual(contexts, [])
        self.assertEqual(captured, [])

    def test_send_input_failure_is_explicit(self) -> None:
        backend = object.__new__(WindowsBackend)

        class User32:
            @staticmethod
            def SendInput(count, pointer, size):
                return 0

        class Ctypes:
            @staticmethod
            def byref(record):
                return record

            @staticmethod
            def sizeof(record):
                return 1

            @staticmethod
            def get_last_error():
                return 5

            @staticmethod
            def FormatError(error):
                return "access denied"

        backend._user32 = User32()
        backend._ctypes = Ctypes()

        with self.assertRaisesRegex(RuntimeError, "sent 0 of 1 input.*access denied"):
            backend._send_input(object(), "mouse_down_at('left', 1.0, 2.0)")

    def test_legacy_mouse_buttons_keep_button_only_flags(self) -> None:
        backend = object.__new__(WindowsBackend)
        captured: list[object] = []

        class Input:
            def __init__(self) -> None:
                self.type = 0
                self.mi = None

        backend._INPUT = Input
        backend._MOUSEINPUT = lambda *values: values
        backend._send_input = lambda record, operation: captured.append(record)

        backend.mouse_down("left")
        backend.mouse_up("right")

        self.assertEqual(captured[0].mi, (0, 0, 0, backend._MOUSEEVENTF_LEFTDOWN, 0, 0))
        self.assertEqual(captured[1].mi, (0, 0, 0, backend._MOUSEEVENTF_RIGHTUP, 0, 0))

    def test_arrow_keys_set_extended_flag(self) -> None:
        backend = object.__new__(WindowsBackend)
        captured: list[object] = []

        class Input:
            def __init__(self) -> None:
                self.type = 0
                self.ki = None

        backend._INPUT = Input
        backend._KEYBDINPUT = lambda *values: values
        backend._send_input = lambda record, operation: captured.append(record)

        backend._send_key("left", is_key_up=False)
        backend._send_key("right", is_key_up=True)

        self.assertEqual(captured[0].ki[2], backend._KEYEVENTF_EXTENDEDKEY)
        self.assertEqual(
            captured[1].ki[2], backend._KEYEVENTF_EXTENDEDKEY | backend._KEYEVENTF_KEYUP
        )


class FactoryTests(unittest.TestCase):
    def test_unsupported_platform_needs_no_native_import(self) -> None:
        with patch("afk_grinder.backends.sys.platform", "linux"):
            with self.assertRaisesRegex(RuntimeError, "Windows and macOS"):
                create_backend()
