"""Windows backend using documented Win32 input and foreground APIs.

API references: GetForegroundWindow, QueryFullProcessImageNameW, GetAsyncKeyState,
and SendInput in the Microsoft Win32 documentation.
"""

from __future__ import annotations

import ntpath
import sys
from typing import Any

from afk_grinder.models import BUTTONS, KEYS, Target


class WindowsBackend:
    """Bounded Win32 keyboard and mouse adapter; never acquires focus."""

    _PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    _VK_ESCAPE = 0x1B
    _INPUT_MOUSE = 0
    _INPUT_KEYBOARD = 1
    _KEYEVENTF_EXTENDEDKEY = 0x0001
    _KEYEVENTF_KEYUP = 0x0002
    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004
    _MOUSEEVENTF_RIGHTDOWN = 0x0008
    _MOUSEEVENTF_RIGHTUP = 0x0010

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
