"""Windows backend using documented Win32 input and foreground APIs.

API references: GetForegroundWindow, QueryFullProcessImageNameW, GetAsyncKeyState,
and SendInput in the Microsoft Win32 documentation.
"""

from __future__ import annotations

import ntpath
import math
import sys
from typing import Any

from afk_grinder.models import BUTTONS, KEYS, Target


class WindowsBackend:
    """Bounded Win32 keyboard and mouse adapter; never acquires focus."""

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _GWL_EXSTYLE = -20
    _WS_EX_TOOLWINDOW = 0x00000080
    _MAX_DISCOVERY_WINDOWS = 4096
    _VK_ESCAPE = 0x1B
    _INPUT_MOUSE = 0
    _INPUT_KEYBOARD = 1
    _KEYEVENTF_EXTENDEDKEY = 0x0001
    _KEYEVENTF_KEYUP = 0x0002
    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004
    _MOUSEEVENTF_RIGHTDOWN = 0x0008
    _MOUSEEVENTF_RIGHTUP = 0x0010
    _MOUSEEVENTF_MOVE = 0x0001
    _MOUSEEVENTF_VIRTUALDESK = 0x4000
    _MOUSEEVENTF_ABSOLUTE = 0x8000
    _SM_XVIRTUALSCREEN = 76
    _SM_YVIRTUALSCREEN = 77
    _SM_CXVIRTUALSCREEN = 78
    _SM_CYVIRTUALSCREEN = 79
    _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
    _ABSOLUTE_MAXIMUM = 65535

    _KEY_CODES = {
        "w": 0x57,
        "a": 0x41,
        "s": 0x53,
        "d": 0x44,
        "e": 0x45,
        "space": 0x20,
        "up": 0x26,
        "down": 0x28,
        "left": 0x25,
        "right": 0x27,
    }

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows backend requires Windows (sys.platform == 'win32').")
        try:
            import ctypes
            from ctypes import wintypes

            self._ctypes = ctypes
            self._wintypes = wintypes
            self._user32 = ctypes.WinDLL("user32", use_last_error=True)
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._configure_types_and_apis()
        except (ImportError, OSError, AttributeError) as error:
            raise RuntimeError(f"Windows native API initialization failed: {error}") from error

    def _configure_types_and_apis(self) -> None:
        ctypes = self._ctypes
        wintypes = self._wintypes
        ulong_ptr = ctypes.c_size_t

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class INPUT_UNION(ctypes.Union):
            _fields_ = [
                ("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT),
            ]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("u",)
            _fields_ = [("type", wintypes.DWORD), ("u", INPUT_UNION)]

        self._MOUSEINPUT = MOUSEINPUT
        self._KEYBDINPUT = KEYBDINPUT
        self._INPUT = INPUT

        self._user32.GetForegroundWindow.argtypes = []
        self._user32.GetForegroundWindow.restype = wintypes.HWND
        self._WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        self._user32.EnumWindows.argtypes = [self._WNDENUMPROC, wintypes.LPARAM]
        self._user32.EnumWindows.restype = wintypes.BOOL
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.IsWindowVisible.argtypes = [wintypes.HWND]
        self._user32.IsWindowVisible.restype = wintypes.BOOL
        self._user32.IsIconic.argtypes = [wintypes.HWND]
        self._user32.IsIconic.restype = wintypes.BOOL
        self._user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self._user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        self._user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(INPUT),
            ctypes.c_int,
        ]
        self._user32.SendInput.restype = wintypes.UINT
        get_system_metrics = getattr(self._user32, "GetSystemMetrics", None)
        if callable(get_system_metrics):
            get_system_metrics.argtypes = [ctypes.c_int]
            get_system_metrics.restype = ctypes.c_int
        set_thread_dpi_awareness_context = getattr(
            self._user32, "SetThreadDpiAwarenessContext", None
        )
        if callable(set_thread_dpi_awareness_context):
            set_thread_dpi_awareness_context.argtypes = [ctypes.c_void_p]
            set_thread_dpi_awareness_context.restype = ctypes.c_void_p
        self._kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD),
        ]
        self._kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self._kernel32.CloseHandle.restype = wintypes.BOOL

    def foreground(self) -> Target | None:
        """Return active process identity, or ``None`` when it cannot be verified."""
        hwnd = self._user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = self._wintypes.DWORD()
        if not self._user32.GetWindowThreadProcessId(hwnd, self._ctypes.byref(pid)) or not pid.value:
            return None
        handle = self._kernel32.OpenProcess(
            self._PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid.value,
        )
        if not handle:
            return None
        try:
            capacity = 32768
            path = self._ctypes.create_unicode_buffer(capacity)
            path_length = self._wintypes.DWORD(capacity)
            if not self._kernel32.QueryFullProcessImageNameW(
                handle, 0, path, self._ctypes.byref(path_length)
            ):
                return None
            executable = ntpath.basename(path.value)
            if not executable:
                return None
            hwnd_value = self._ctypes.cast(hwnd, self._ctypes.c_void_p).value
            if hwnd_value is None:
                return None
            return Target(
                pid=int(pid.value),
                token=str(hwnd_value),
                executable=executable,
                identifier="win32",
            )
        finally:
            self._kernel32.CloseHandle(handle)

    def discover_targets(self) -> tuple[Target, ...]:
        """List verified Roblox windows without focusing, prompting, or sending input."""
        targets: dict[tuple[int, str, str, str], Target] = {}
        callback_count = 0
        capped = False
        callback_error: RuntimeError | None = None

        def inspect_window(hwnd: Any, _lparam: Any) -> bool:
            nonlocal callback_count, capped, callback_error
            callback_count += 1
            try:
                target = self._discovered_window_target(hwnd)
                if target is not None:
                    targets[(target.pid, target.token, target.executable, target.identifier)] = target
            except RuntimeError as error:
                callback_error = error
                return False
            if callback_count >= self._MAX_DISCOVERY_WINDOWS:
                capped = True
                return False
            return True

        try:
            callback_factory = getattr(self, "_WNDENUMPROC", None)
            callback = callback_factory(inspect_window) if callable(callback_factory) else inspect_window
            enumerated = self._user32.EnumWindows(callback, 0)
            if callback_error is not None:
                raise callback_error
            if not enumerated:
                if capped:
                    raise RuntimeError(
                        "Windows target discovery stopped after "
                        f"{self._MAX_DISCOVERY_WINDOWS} windows."
                    )
                raise RuntimeError("Windows target discovery failed: EnumWindows returned false.")
            return tuple(sorted(targets.values(), key=lambda target: (
                target.pid,
                target.token,
                target.executable,
                target.identifier,
            )))
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"Windows target discovery failed: {error}") from error

    def _discovered_window_target(self, hwnd: Any) -> Target | None:
        """Resolve one eligible top-level HWND to an exact Roblox executable."""
        try:
            if (
                not hwnd
                or not self._user32.IsWindow(hwnd)
                or not self._user32.IsWindowVisible(hwnd)
                or self._user32.IsIconic(hwnd)
            ):
                return None
            self._ctypes.set_last_error(0)
            extended_style = int(self._user32.GetWindowLongPtrW(hwnd, self._GWL_EXSTYLE))
            if not extended_style and self._ctypes.get_last_error():
                raise RuntimeError("Windows window check failed: extended style is unavailable.")
            if extended_style & self._WS_EX_TOOLWINDOW:
                return None
            pid = self._wintypes.DWORD()
            if not self._user32.GetWindowThreadProcessId(hwnd, self._ctypes.byref(pid)) or not pid.value:
                return None
            handle = self._kernel32.OpenProcess(
                self._PROCESS_QUERY_LIMITED_INFORMATION,
                False,
                pid.value,
            )
            if not handle:
                return None
            try:
                capacity = 32768
                path = self._ctypes.create_unicode_buffer(capacity)
                path_length = self._wintypes.DWORD(capacity)
                if not self._kernel32.QueryFullProcessImageNameW(
                    handle, 0, path, self._ctypes.byref(path_length)
                ):
                    return None
                executable = ntpath.basename(path.value)
                if executable.casefold() not in {"robloxplayer.exe", "robloxplayerbeta.exe"}:
                    return None
                hwnd_value = self._ctypes.cast(hwnd, self._ctypes.c_void_p).value
                if hwnd_value is None:
                    return None
                return Target(
                    pid=int(pid.value),
                    token=str(hwnd_value),
                    executable=executable,
                    identifier="win32",
                )
            finally:
                self._kernel32.CloseHandle(handle)
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(f"Windows target discovery window check failed: {error}") from error

    def readiness(self) -> list[str]:
        """Return startup errors. Windows needs no consent preflight API here."""
        return []

    def escape_pressed(self) -> bool:
        """Read Escape's current high-bit state; low transition bit is ignored."""
        return bool(int(self._user32.GetAsyncKeyState(self._VK_ESCAPE)) & 0x8000)

    def key_down(self, key: str) -> None:
        self._send_key(key, is_key_up=False)

    def key_up(self, key: str) -> None:
        self._send_key(key, is_key_up=True)

    def mouse_down(self, button: str) -> None:
        self._send_mouse(button, is_mouse_up=False)

    def mouse_down_at(self, button: str, x: float, y: float) -> None:
        """Move and press in one virtual-desktop absolute input record."""
        self._validate_button(button)
        self._validate_native_point(x, y)
        origin_x, origin_y, width, height = self._virtual_desktop_metrics()
        maximum_x = origin_x + width - 1
        maximum_y = origin_y + height - 1
        if not origin_x <= x <= maximum_x or not origin_y <= y <= maximum_y:
            raise ValueError("Native mouse coordinate is outside the virtual desktop.")
        dx = self._normalize_absolute_coordinate(x, origin_x, width)
        dy = self._normalize_absolute_coordinate(y, origin_y, height)
        button_flag = {
            "left": self._MOUSEEVENTF_LEFTDOWN,
            "right": self._MOUSEEVENTF_RIGHTDOWN,
        }[button]
        record = self._INPUT()
        record.type = self._INPUT_MOUSE
        record.mi = self._MOUSEINPUT(
            dx,
            dy,
            0,
            self._MOUSEEVENTF_MOVE
            | self._MOUSEEVENTF_ABSOLUTE
            | self._MOUSEEVENTF_VIRTUALDESK
            | button_flag,
            0,
            0,
        )
        self._send_input(record, f"mouse_down_at({button!r}, {x!r}, {y!r})")

    def mouse_up(self, button: str) -> None:
        self._send_mouse(button, is_mouse_up=True)

    def _send_key(self, key: str, *, is_key_up: bool) -> None:
        self._validate_key(key)
        flags = self._KEYEVENTF_KEYUP if is_key_up else 0
        if key in {"up", "down", "left", "right"}:
            flags |= self._KEYEVENTF_EXTENDEDKEY
        record = self._INPUT()
        record.type = self._INPUT_KEYBOARD
        record.ki = self._KEYBDINPUT(self._KEY_CODES[key], 0, flags, 0, 0)
        operation = "key_up" if is_key_up else "key_down"
        self._send_input(record, f"{operation}({key!r})")

    def _send_mouse(self, button: str, *, is_mouse_up: bool) -> None:
        self._validate_button(button)
        flags: dict[tuple[str, bool], int] = {
            ("left", False): self._MOUSEEVENTF_LEFTDOWN,
            ("left", True): self._MOUSEEVENTF_LEFTUP,
            ("right", False): self._MOUSEEVENTF_RIGHTDOWN,
            ("right", True): self._MOUSEEVENTF_RIGHTUP,
        }
        record = self._INPUT()
        record.type = self._INPUT_MOUSE
        record.mi = self._MOUSEINPUT(0, 0, 0, flags[(button, is_mouse_up)], 0, 0)
        operation = "mouse_up" if is_mouse_up else "mouse_down"
        self._send_input(record, f"{operation}({button!r})")

    def _send_input(self, record: Any, operation: str) -> None:
        sent = self._user32.SendInput(1, self._ctypes.byref(record), self._ctypes.sizeof(record))
        if sent != 1:
            error_code = self._ctypes.get_last_error()
            detail = self._ctypes.FormatError(error_code).strip() if error_code else "unknown error"
            raise RuntimeError(
                f"Windows SendInput {operation} failed: sent {sent} of 1 input ({detail})."
            )

    def _virtual_desktop_metrics(self) -> tuple[int, int, int, int]:
        set_context = getattr(self._user32, "SetThreadDpiAwarenessContext", None)
        get_metrics = getattr(self._user32, "GetSystemMetrics", None)
        if not callable(set_context):
            raise RuntimeError(
                "Windows positioned mouse unavailable: "
                "SetThreadDpiAwarenessContext is unavailable."
            )
        if not callable(get_metrics):
            raise RuntimeError(
                "Windows positioned mouse unavailable: GetSystemMetrics is unavailable."
            )
        try:
            prior_context = set_context(self._DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2)
        except Exception as error:
            raise RuntimeError(
                "Windows positioned mouse unavailable: "
                f"SetThreadDpiAwarenessContext failed: {error}"
            ) from error
        if not prior_context:
            raise RuntimeError(
                "Windows positioned mouse unavailable: "
                "SetThreadDpiAwarenessContext returned no prior context."
            )
        try:
            origin_x = int(get_metrics(self._SM_XVIRTUALSCREEN))
            origin_y = int(get_metrics(self._SM_YVIRTUALSCREEN))
            width = int(get_metrics(self._SM_CXVIRTUALSCREEN))
            height = int(get_metrics(self._SM_CYVIRTUALSCREEN))
            if width <= 1 or height <= 1:
                raise RuntimeError(
                    "Windows positioned mouse unavailable: "
                    "virtual desktop dimensions must both exceed one pixel."
                )
            return origin_x, origin_y, width, height
        except RuntimeError:
            raise
        except Exception as error:
            raise RuntimeError(
                "Windows positioned mouse unavailable: GetSystemMetrics failed: "
                f"{error}"
            ) from error
        finally:
            try:
                restored_context = set_context(prior_context)
            except Exception as error:
                raise RuntimeError(
                    "Windows positioned mouse unavailable: "
                    f"could not restore thread DPI awareness context: {error}"
                ) from error
            if not restored_context:
                raise RuntimeError(
                    "Windows positioned mouse unavailable: "
                    "could not restore thread DPI awareness context."
                )

    @classmethod
    def _normalize_absolute_coordinate(cls, coordinate: float, origin: int, size: int) -> int:
        return round((coordinate - origin) * cls._ABSOLUTE_MAXIMUM / (size - 1))

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
