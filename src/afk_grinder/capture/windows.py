"""Window-client capture through documented Win32 APIs.

``PrintWindow`` is synchronous and can block, so this adapter belongs on the
observation worker.  It captures only the pinned window's client area and has
no desktop or focus-changing fallback.
"""

from __future__ import annotations

import ctypes
import sys
from contextlib import contextmanager
from time import monotonic
from typing import Iterator

from afk_grinder.capture import CaptureError, CapturedWindow, WindowBinding, bgrx_to_bgr, build_frame
from afk_grinder.models import Target


class WindowsCapture:
    _DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = ctypes.c_void_p(-4)
    _PW_CLIENTONLY = 0x00000001
    _DIB_RGB_COLORS = 0

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("Windows capture requires Windows (sys.platform == 'win32').")
        from ctypes import wintypes

        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self._configure_native_types()

    def _configure_native_types(self) -> None:
        wintypes = self._wintypes
        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]
        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                       ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG),
                       ("biHeight", wintypes.LONG), ("biPlanes", wintypes.WORD),
                       ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                       ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                       ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                       ("biClrImportant", wintypes.DWORD)]
        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 1)]
        self._POINT, self._RECT, self._BITMAPINFO = POINT, RECT, BITMAPINFO
        u = self._user32
        u.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        u.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        u.IsWindow.argtypes, u.IsWindow.restype = [wintypes.HWND], wintypes.BOOL
        u.IsIconic.argtypes, u.IsIconic.restype = [wintypes.HWND], wintypes.BOOL
        u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        u.GetWindowThreadProcessId.restype = wintypes.DWORD
        u.GetClientRect.argtypes, u.GetClientRect.restype = [wintypes.HWND, ctypes.POINTER(RECT)], wintypes.BOOL
        u.ClientToScreen.argtypes, u.ClientToScreen.restype = [wintypes.HWND, ctypes.POINTER(POINT)], wintypes.BOOL
        u.MonitorFromWindow.argtypes, u.MonitorFromWindow.restype = [wintypes.HWND, wintypes.DWORD], wintypes.HMONITOR
        u.GetDpiForWindow.argtypes, u.GetDpiForWindow.restype = [wintypes.HWND], wintypes.UINT
        u.PrintWindow.argtypes, u.PrintWindow.restype = [wintypes.HWND, wintypes.HDC, wintypes.UINT], wintypes.BOOL
        g = self._gdi32
        g.CreateCompatibleDC.argtypes, g.CreateCompatibleDC.restype = [wintypes.HDC], wintypes.HDC
        g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        g.CreateDIBSection.restype = wintypes.HBITMAP
        g.SelectObject.argtypes, g.SelectObject.restype = [wintypes.HDC, wintypes.HGDIOBJ], wintypes.HGDIOBJ
        g.DeleteObject.argtypes, g.DeleteObject.restype = [wintypes.HGDIOBJ], wintypes.BOOL
        g.DeleteDC.argtypes, g.DeleteDC.restype = [wintypes.HDC], wintypes.BOOL

    def discover(self, target: Target) -> WindowBinding:
        self._require_roblox(target)
        with self._per_monitor_v2():
            return self._read_binding(target)

    def capture(self, binding: WindowBinding) -> CapturedWindow:
        started_at = monotonic()
        self._require_roblox(binding.target)
        with self._per_monitor_v2():
            before = self._read_binding(binding.target)
            if before != binding:
                raise CaptureError("Windows bound client geometry changed before capture.")
            pixels = self._print_client_bgr(binding)
            width, height = binding.native_rect[2:]
            if len(pixels) != width * height * 3:
                raise CaptureError("Windows client capture returned an unexpected pixel buffer size.")
            if not any(pixels):
                raise CaptureError("Windows client capture was all black; refusing an invalid frame.")
            after = self._read_binding(binding.target)
            if after != binding:
                raise CaptureError("Windows bound client geometry changed during capture.")
        return build_frame(binding, physical_size=(width, height), pixels=pixels, captured_at=started_at)

    def snapshot(self, target: Target) -> CapturedWindow:
        return self.capture(self.discover(target))

    @staticmethod
    def _require_roblox(target: Target) -> None:
        if not target.is_roblox:
            raise CaptureError("Windows capture accepts only a verified Roblox target.")

    @contextmanager
    def _per_monitor_v2(self) -> Iterator[None]:
        previous = self._user32.SetThreadDpiAwarenessContext(
            self._DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
        )
        if not previous:
            raise CaptureError("Windows could not establish Per-Monitor-V2 DPI awareness before geometry.")
        try:
            yield
        finally:
            self._user32.SetThreadDpiAwarenessContext(previous)

    def _read_binding(self, target: Target) -> WindowBinding:
        try:
            hwnd_value = int(target.token)
        except (TypeError, ValueError) as error:
            raise CaptureError("Windows target does not contain a stable window handle.") from error
        hwnd = self._wintypes.HWND(hwnd_value)
        if not self._user32.IsWindow(hwnd):
            raise CaptureError("Windows bound window no longer exists.")
        if self._user32.IsIconic(hwnd):
            raise CaptureError("Windows bound window is minimized; client capture is unavailable.")
        pid = self._wintypes.DWORD()
        if not self._user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or pid.value != target.pid:
            raise CaptureError("Windows bound window identity no longer matches the target process.")
        rect = self._RECT()
        if not self._user32.GetClientRect(hwnd, ctypes.byref(rect)):
            raise CaptureError("Windows could not read bound client bounds.")
        width, height = rect.right - rect.left, rect.bottom - rect.top
        if width <= 0 or height <= 0:
            raise CaptureError("Windows bound client bounds are empty or unknown.")
        if width * height > 16_000_000:
            raise CaptureError("Windows client capture exceeds the 16,000,000-pixel safety limit.")
        origin = self._POINT(rect.left, rect.top)
        if not self._user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            raise CaptureError("Windows could not resolve bound client origin.")
        monitor = self._user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
        if not monitor:
            raise CaptureError("Windows could not resolve monitor for the bound client window.")
        dpi = int(self._user32.GetDpiForWindow(hwnd))
        if dpi <= 0:
            raise CaptureError("Windows could not resolve DPI for the bound client window.")
        monitor_value = ctypes.cast(monitor, ctypes.c_void_p).value
        if monitor_value is None:
            raise CaptureError("Windows monitor identity is unavailable.")
        return WindowBinding(
            target=target,
            window_id=str(hwnd_value),
            native_rect=(int(origin.x), int(origin.y), int(width), int(height)),
            monitor_id=str(monitor_value),
            scale=(dpi / 96.0, dpi / 96.0),
        )

    def _print_client_bgr(self, binding: WindowBinding) -> bytes:
        hwnd = self._wintypes.HWND(int(binding.window_id))
        width, height = binding.native_rect[2:]
        info = self._BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(info.bmiHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # top-down, packed rows
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0  # BI_RGB, little-endian BGRX
        bits = ctypes.c_void_p()
        dc = self._gdi32.CreateCompatibleDC(None)
        if not dc:
            raise CaptureError("Windows could not create a client capture device context.")
        bitmap = old = None
        try:
            bitmap = self._gdi32.CreateDIBSection(dc, ctypes.byref(info), self._DIB_RGB_COLORS,
                                                  ctypes.byref(bits), None, 0)
            if not bitmap or not bits.value:
                raise CaptureError("Windows could not allocate a client capture bitmap.")
            old = self._gdi32.SelectObject(dc, bitmap)
            if not old:
                raise CaptureError("Windows could not select a client capture bitmap.")
            if not self._user32.PrintWindow(hwnd, dc, self._PW_CLIENTONLY):
                raise CaptureError("Windows PrintWindow client capture failed.")
            raw = ctypes.string_at(bits, width * height * 4)
            return bgrx_to_bgr(raw, width * height)
        finally:
            if old:
                self._gdi32.SelectObject(dc, old)
            if bitmap:
                self._gdi32.DeleteObject(bitmap)
            self._gdi32.DeleteDC(dc)
