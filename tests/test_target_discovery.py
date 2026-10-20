"""Read-only native target-discovery checks using fake platform APIs."""

from __future__ import annotations

from contextlib import nullcontext
import ctypes
from ctypes import wintypes
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afk_grinder.backends.macos import MacOSBackend
from afk_grinder.backends.windows import WindowsBackend


class FakeObjC:
    @staticmethod
    def autorelease_pool():
        return nullcontext()


class FakeMacApplication:
    def __init__(
        self,
        pid: int,
        *,
        bundle: str | None = "com.roblox.RobloxPlayer",
        executable: str | None = "RobloxPlayer",
        terminated: bool = False,
    ) -> None:
        self.pid = pid
        self.bundle = bundle
        self.executable = executable
        self.terminated = terminated

    def processIdentifier(self) -> int:
        return self.pid

    def bundleIdentifier(self) -> str | None:
        return self.bundle

    def executableURL(self):
        if self.executable is None:
            return None

        class URL:
            def __init__(self, component: str) -> None:
                self.component = component

            def lastPathComponent(self) -> str:
                return self.component

        return URL(self.executable)

    def isTerminated(self) -> bool:
        return self.terminated


class FakeMacResolver:
    def __init__(
        self,
        applications: dict[int, FakeMacApplication],
        enumerated: list[FakeMacApplication],
    ) -> None:
        self.applications = applications
        self.enumerated = enumerated
        self.enumeration_error: Exception | None = None

    def runningApplicationsWithBundleIdentifier_(self, bundle: str):
        if self.enumeration_error is not None:
            raise self.enumeration_error
        if bundle != "com.roblox.RobloxPlayer":
            raise AssertionError("Discovery must enumerate only the Roblox bundle.")
        return self.enumerated

    def runningApplicationWithProcessIdentifier_(self, pid: int) -> FakeMacApplication | None:
        return self.applications.get(pid)


def fake_macos_backend(
    applications: dict[int, FakeMacApplication], enumerated: list[FakeMacApplication]
) -> tuple[MacOSBackend, FakeMacResolver]:
    backend = object.__new__(MacOSBackend)
    resolver = FakeMacResolver(applications, enumerated)
    backend._AppKit = type("AppKit", (), {"NSRunningApplication": resolver})()
    backend._objc = FakeObjC()
    return backend, resolver


class MacTargetDiscoveryTests(unittest.TestCase):
    def test_zero_and_one_candidate(self) -> None:
        backend, _ = fake_macos_backend({}, [])
        self.assertEqual(backend.discover_targets(), ())

        application = FakeMacApplication(41)
        backend, _ = fake_macos_backend({41: application}, [application])
        self.assertEqual(
            backend.discover_targets()[0].__dict__,
            {"pid": 41, "token": "41", "executable": "RobloxPlayer", "identifier": "com.roblox.RobloxPlayer"},
        )

    def test_multiple_filters_unrelated_invalid_terminated_and_deduplicates(self) -> None:
        first = FakeMacApplication(9, executable="RobloxPlayer")
        second = FakeMacApplication(3, executable="RobloxPlayerBeta")
        unrelated = FakeMacApplication(11, bundle="com.example.other", executable="Other")
        invalid = FakeMacApplication(0)
        terminated = FakeMacApplication(12, terminated=True)
        backend, _ = fake_macos_backend(
            {9: first, 3: second, 11: unrelated, 12: terminated},
            [first, second, first, unrelated, invalid, terminated],
        )

        targets = backend.discover_targets()

        self.assertEqual([(target.pid, target.token) for target in targets], [(3, "3"), (9, "9")])

    def test_pid_replacement_and_native_enumerator_failure_fail_closed(self) -> None:
        stale = FakeMacApplication(50)
        replacement = FakeMacApplication(51)
        backend, resolver = fake_macos_backend({50: replacement}, [stale])
        self.assertEqual(backend.discover_targets(), ())

        resolver.enumeration_error = OSError("native enumeration failed")
        with self.assertRaisesRegex(RuntimeError, "target discovery failed"):
            backend.discover_targets()


class FakeWindow:
    def __init__(
        self,
        *,
        exists: bool = True,
        visible: bool = True,
        minimized: bool = False,
        extended_style: int = 0,
        pid: int = 0,
    ) -> None:
        self.exists = exists
        self.visible = visible
        self.minimized = minimized
        self.extended_style = extended_style
        self.pid = pid


class FakeCtypes:
    def __init__(self) -> None:
        self.last_error = 0

    def __getattr__(self, name):
        return getattr(ctypes, name)

    def set_last_error(self, value):
        self.last_error = value

    def get_last_error(self):
        return self.last_error


class FakeUser32:
    def __init__(self, windows: dict[int, FakeWindow], enumeration: list[int]) -> None:
        self.windows = windows
        self.enumeration = enumeration
        self.fail_enumeration = False
        self.style_error = False
        self.ctypes = None

    @staticmethod
    def _value(hwnd) -> int:
        return int(hwnd.value)

    def EnumWindows(self, callback, _lparam) -> bool:
        for value in self.enumeration:
            if not callback(ctypes.c_void_p(value), 0):
                return False
        return not self.fail_enumeration

    def IsWindow(self, hwnd) -> bool:
        return self.windows[self._value(hwnd)].exists

    def IsWindowVisible(self, hwnd) -> bool:
        return self.windows[self._value(hwnd)].visible

    def IsIconic(self, hwnd) -> bool:
        return self.windows[self._value(hwnd)].minimized

    def GetWindowLongPtrW(self, hwnd, _index) -> int:
        if self.style_error:
            self.ctypes.set_last_error(5)
            return 0
        return self.windows[self._value(hwnd)].extended_style

    def GetWindowThreadProcessId(self, hwnd, pid_pointer) -> int:
        pid = self.windows[self._value(hwnd)].pid
        if pid:
            pid_pointer._obj.value = pid
            return 1
        return 0


class FakeKernel32:
    def __init__(self, paths: dict[int, str | None]) -> None:
        self.paths = paths
        self.closed: list[int] = []
        self.query_error: Exception | None = None

    def OpenProcess(self, _access, _inherit, pid: int):
        return ctypes.c_void_p(pid) if pid in self.paths else None

    def QueryFullProcessImageNameW(self, handle, _flags, path, _length) -> bool:
        if self.query_error is not None:
            raise self.query_error
        executable_path = self.paths[handle.value]
        if executable_path is None:
            return False
        path.value = executable_path
        return True

    def CloseHandle(self, handle) -> bool:
        self.closed.append(int(handle.value))
        return True


def fake_windows_backend(
    windows: dict[int, FakeWindow], enumeration: list[int], paths: dict[int, str | None]
) -> tuple[WindowsBackend, FakeUser32, FakeKernel32]:
    backend = object.__new__(WindowsBackend)
    user32 = FakeUser32(windows, enumeration)
    kernel32 = FakeKernel32(paths)
    backend._ctypes = FakeCtypes()
    user32.ctypes = backend._ctypes
    backend._wintypes = wintypes
    backend._user32 = user32
    backend._kernel32 = kernel32
    backend._WNDENUMPROC = lambda callback: callback
    return backend, user32, kernel32


class WindowsTargetDiscoveryTests(unittest.TestCase):
    def test_style_error_is_not_a_valid_zero_style(self) -> None:
        backend, user32, kernel32 = fake_windows_backend(
            {1: FakeWindow(pid=20)}, [1], {20: r"C:\\RobloxPlayer.exe"}
        )
        backend._ctypes.set_last_error(123)
        self.assertEqual(len(backend.discover_targets()), 1)
        user32.style_error = True
        with self.assertRaisesRegex(RuntimeError, "extended style is unavailable"):
            backend.discover_targets()
        self.assertEqual(kernel32.closed, [20])

    def test_zero_and_one_candidate(self) -> None:
        backend, _, _ = fake_windows_backend({}, [], {})
        self.assertEqual(backend.discover_targets(), ())

        backend, _, _ = fake_windows_backend(
            {100: FakeWindow(pid=90)}, [100], {90: r"C:\\RobloxPlayerBeta.exe"}
        )
        target = backend.discover_targets()[0]
        self.assertEqual((target.pid, target.token, target.executable), (90, "100", "RobloxPlayerBeta.exe"))

    def test_filters_unrelated_invalid_windows_and_deduplicates(self) -> None:
        tool_window = WindowsBackend._WS_EX_TOOLWINDOW
        windows = {
            1: FakeWindow(pid=10),
            2: FakeWindow(visible=False, pid=11),
            3: FakeWindow(minimized=True, pid=12),
            4: FakeWindow(extended_style=tool_window, pid=13),
            5: FakeWindow(exists=False, pid=14),
            6: FakeWindow(pid=0),
            7: FakeWindow(pid=15),
        }
        backend, _, _ = fake_windows_backend(
            windows,
            [1, 1, 2, 3, 4, 5, 6, 7],
            {10: r"C:\\RobloxPlayer.exe", 15: r"C:\\Other.exe"},
        )

        targets = backend.discover_targets()

        self.assertEqual([(target.pid, target.token) for target in targets], [(10, "1")])

    def test_pid_replacement_keeps_distinct_window_tokens_and_closes_handles(self) -> None:
        backend, _, kernel32 = fake_windows_backend(
            {100: FakeWindow(pid=20), 200: FakeWindow(pid=20), 300: FakeWindow(pid=21)},
            [200, 100, 300],
            {
                20: r"C:\\RobloxPlayerBeta.exe",
                21: None,
            },
        )

        targets = backend.discover_targets()

        self.assertEqual([(target.pid, target.token) for target in targets], [(20, "100"), (20, "200")])
        self.assertEqual(kernel32.closed, [20, 20, 21])

    def test_native_failures_do_not_become_empty_success(self) -> None:
        backend, user32, _ = fake_windows_backend({}, [], {})
        user32.fail_enumeration = True
        with self.assertRaisesRegex(RuntimeError, "EnumWindows returned false"):
            backend.discover_targets()

        backend, _, _ = fake_windows_backend(
            {1: FakeWindow(pid=20)}, [1], {20: r"C:\\RobloxPlayer.exe"}
        )
        backend._kernel32.query_error = OSError("native path query failed")
        with self.assertRaisesRegex(RuntimeError, "window check failed"):
            backend.discover_targets()
