"""Adapter-only checks using fake native modules. No OS input is sent."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path
import sys
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

    def AXIsProcessTrusted(self) -> bool:
        return self.trusted


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

    def CGEventPost(self, tap, event) -> None:
        if self.post_error is not None:
            raise self.post_error
        self.posted.append(event)


def fake_macos_backend(
    *, listen: bool = True, post: bool = True, trusted: bool = True
) -> tuple[MacOSBackend, FakeQuartz]:
    backend = object.__new__(MacOSBackend)
    quartz = FakeQuartz(listen=listen, post=post)
    backend._Quartz = quartz
    backend._ApplicationServices = FakeApplicationServices(trusted)
    backend._objc = FakeObjC()
    return backend, quartz


class MacOSBackendTests(unittest.TestCase):
    def test_escape_state_and_fail_closed_errors(self) -> None:
        backend, quartz = fake_macos_backend()
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
        backend, _ = fake_macos_backend(listen=False, post=False, trusted=False)

        problems = backend.readiness()

        self.assertEqual(len(problems), 3)
        self.assertTrue(any("Accessibility permission" in problem for problem in problems))
        self.assertTrue(any("Input Monitoring permission" in problem for problem in problems))

    def test_missing_listen_permission_blocks_down_but_not_up(self) -> None:
        backend, quartz = fake_macos_backend(listen=False)

        with self.assertRaisesRegex(RuntimeError, "Input Monitoring permission"):
            backend.key_down("w")
        backend.key_up("w")

        self.assertEqual(len(quartz.posted), 1)

    def test_none_and_native_post_errors_are_explicit(self) -> None:
        backend, quartz = fake_macos_backend()
        quartz.keyboard_event = None
        with self.assertRaisesRegex(RuntimeError, "could not create event"):
            backend.key_down("w")

        quartz.keyboard_event = object()
        quartz.post_error = OSError("native post failure")
        with self.assertRaisesRegex(RuntimeError, "event post failed"):
            backend.key_down("w")


class WindowsBackendTests(unittest.TestCase):
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
