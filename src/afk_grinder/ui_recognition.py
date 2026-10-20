"""Recognition setup preview UI with no input or persistent image path."""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable
from typing import Any
from tkinter import ttk

from afk_grinder.capture import CapturedWindow
from afk_grinder.capture.service import BackgroundJob, JobResult
from afk_grinder.models import Target


class RecognitionSetup:
    """Small, cancellable window-only preview dialog.

    Captured pixels stay in this object until they are replaced, cancelled, or
    closed.  This component never focuses Roblox or passes pixels to input.
    """

    _POLL_MS = 20
    _TARGET_POLL_MS = 100
    _PREVIEW_MAX_WIDTH = 560
    _PREVIEW_MAX_HEIGHT = 360

    def __init__(
        self,
        parent: tk.Misc,
        *,
        get_target: Callable[[], Target | None],
        begin_binding: Callable[[], None],
        cancel_binding: Callable[[], object],
        binding_pending: Callable[[], bool],
        input_busy: Callable[[], bool],
        job_factory: Callable[..., BackgroundJob] = BackgroundJob,
    ) -> None:
        self._parent = parent
        self._get_target = get_target
        self._begin_binding = begin_binding
        self._cancel_binding = cancel_binding
        self._binding_pending = binding_pending
        self._input_busy = input_busy
        self._job_factory = job_factory
        self._closed = False
        self._job: BackgroundJob | Any | None = None
        self._job_kind = ""
        self._job_token = 0
        self._job_after: str | None = None
        self._target_after: str | None = None
        self._resize_after: str | None = None
        self._target: Target | None = None
        self._snapshot: CapturedWindow | None = None
        self._preview_pixels: bytearray | None = None
        self._photo: tk.PhotoImage | None = None

        self.window = tk.Toplevel(parent)
        self.window.title("Recognition setup")
        self.window.transient(parent.winfo_toplevel())
        self.window.resizable(True, True)
        self.window.minsize(440, 490)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", self._on_escape)
        self.window.bind("<Configure>", self._on_configure)
        self.window.grab_set()

        self._target_var = tk.StringVar(value="No Roblox window selected.")
        self._status_var = tk.StringVar(value="Bind Roblox, then take a preview.")
        self._sdk_var = tk.StringVar(value="SDK check has not run.")
        self._preview_var = tk.StringVar(
            value="Snapshot\nPreview only. Game layout recognition is not configured yet."
        )
        self._frame_note_var = tk.StringVar(
            value="Snapshot preview stays in memory. Game layout recognition is not configured yet."
        )
        self._build()
        self._target = self._safe_target()
        self._refresh()
        self._schedule_target_poll()
        self.bind_button.focus_set()

    def _build(self) -> None:
        outer = ttk.Frame(self.window, padding=12)
        outer.grid(sticky="nsew")
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)

        ttk.Label(outer, text="Recognition setup", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            outer,
            text=("Captures only selected Roblox window. Preview stays in memory. "
                  "Nothing is saved, uploaded, or used for input."),
            wraplength=560,
        ).grid(row=1, column=0, sticky="w", pady=(3, 8))

        controls = ttk.Frame(outer)
        controls.grid(row=2, column=0, sticky="ew")
        self.bind_button = ttk.Button(controls, text="Bind Roblox", command=self._start_binding)
        self.bind_button.grid(row=0, column=0, sticky="w")
        self.capture_button = ttk.Button(
            controls, text="Capture preview", command=self.capture_preview, state="disabled"
        )
        self.capture_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        self.sdk_button = ttk.Button(controls, text="Check recognition SDK", command=self.run_sdk_check)
        self.sdk_button.grid(row=0, column=2, sticky="w", padx=(8, 0))
        self.close_button = ttk.Button(controls, text="Close", command=self.close)
        self.close_button.grid(row=0, column=3, sticky="w", padx=(8, 0))

        ttk.Label(outer, textvariable=self._target_var, wraplength=560).grid(
            row=3, column=0, sticky="w", pady=(6, 0)
        )
        preview = ttk.LabelFrame(outer, text="Snapshot", padding=6)
        preview.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(
            preview, width=520, height=300, highlightthickness=0, takefocus=False
        )
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self._preview_item = self.preview_canvas.create_text(
            260, 150, text=self._preview_var.get(), justify="center", width=500
        )
        self._photo_item = self.preview_canvas.create_image(0, 0, anchor="nw", state="hidden")
        ttk.Label(preview, textvariable=self._frame_note_var, wraplength=540).grid(
            row=1, column=0, sticky="w", pady=(5, 0)
        )
        ttk.Label(
            outer,
            text="Preview only. Game layout recognition is not configured yet.",
            wraplength=560,
        ).grid(row=5, column=0, sticky="w", pady=(7, 0))
        ttk.Label(outer, textvariable=self._sdk_var, wraplength=560).grid(
            row=6, column=0, sticky="w", pady=(4, 0))
        ttk.Label(outer, textvariable=self._status_var, wraplength=560).grid(
            row=7, column=0, sticky="w", pady=(4, 0))

    def _safe_target(self) -> Target | None:
        try:
            target = self._get_target()
        except Exception:
            return None
        return target if target is not None and target.is_roblox else None

    def _start_binding(self) -> None:
        if self._closed or self._input_busy() or self._binding_pending():
            return
        self.cancel_work()
        self._clear_preview()
        self._status_var.set("Binding started. Focus Roblox yourself; no input will be sent.")
        self._begin_binding()
        self._refresh()

    def capture_preview(self) -> None:
        if self._closed or self._job is not None or self._input_busy() or self._binding_pending():
            return
        target = self._safe_target()
        if target is None:
            self._clear_preview()
            self._status_var.set("Select a Roblox window before taking a preview.")
            self._refresh()
            return
        self._clear_preview()
        try:
            job = self._job_factory("capture", target)
        except Exception:
            self._status_var.set("Could not start preview. No input was sent.")
            self._refresh()
            return
        self._start_job(job, "capture")
        self._status_var.set("Taking window-only preview. No input will be sent.")

    def run_sdk_check(self) -> None:
        if self._closed or self._job is not None or self._input_busy() or self._binding_pending():
            return
        try:
            job = self._job_factory("sdk")
        except Exception:
            self._sdk_var.set("Recognition SDK unavailable. No input was enabled.")
            self._refresh()
            return
        self._start_job(job, "sdk")
        self._sdk_var.set("Checking recognition SDK with synthetic pixels only.")

    def _start_job(self, job: BackgroundJob | Any, kind: str) -> None:
        self._job_token += 1
        self._job = job
        self._job_kind = kind
        self._schedule_job_poll(self._job_token)
        self._refresh()

    def _schedule_job_poll(self, token: int) -> None:
        self._job_after = self.window.after(self._POLL_MS, lambda: self._poll_job(token))

    def _poll_job(self, token: int) -> None:
        self._job_after = None
        if self._closed or token != self._job_token or self._job is None:
            return
        job = self._job
        try:
            result = job.poll()
        except Exception:
            result = JobResult(error="Preview or SDK check failed. No input was sent.")
        if result is None:
            self._schedule_job_poll(token)
            return
        kind = self._job_kind
        self._job = None
        self._job_kind = ""
        if kind == "capture":
            self._handle_capture_result(result)
        else:
            self._handle_sdk_result(result)
        self._refresh()

    def _handle_capture_result(self, result: JobResult) -> None:
        frame = result.frame
        current_target = self._safe_target()
        if result.error or frame is None:
            self._clear_preview()
            self._status_var.set(self._capture_error(result.error))
            return
        if current_target is None or frame.target != current_target:
            self._clear_preview()
            self._status_var.set("Selected Roblox window changed. Take a new preview.")
            return
        self._snapshot = frame
        self._status_var.set("Snapshot ready in memory. No input was sent.")
        if frame.region_kind == "window-unverified" or not frame.content_verified:
            self._preview_var.set(
                "Snapshot\nPreview includes window frame. Game content bounds are not verified."
            )
            self._frame_note_var.set(
                "Snapshot. Preview includes window frame. Game content bounds are not verified."
            )
        else:
            self._preview_var.set("Snapshot")
            self._frame_note_var.set(
                "Snapshot preview stays in memory. Game layout recognition is not configured yet."
            )
        self._update_preview_text()
        self._render_preview()

    @staticmethod
    def _capture_error(error: str) -> str:
        lowered = error.casefold()
        if "screen recording" in lowered or "permission" in lowered:
            return "Screen Recording permission needed. Open System Settings, allow Screen Recording, then try again."
        return "Could not take preview. No input was sent."

    def _handle_sdk_result(self, result: JobResult) -> None:
        report = result.report
        if result.error or report is None:
            self._sdk_var.set("Recognition SDK unavailable. No input was enabled.")
            return
        self._sdk_var.set("Recognition SDK compatibility passed. Synthetic check only; input stays disabled.")

    def cancel_work(self) -> None:
        self._job_token += 1
        if self._job_after is not None:
            try:
                self.window.after_cancel(self._job_after)
            except tk.TclError:
                pass
            self._job_after = None
        job, self._job = self._job, None
        self._job_kind = ""
        if job is not None:
            try:
                job.cancel()
            except Exception:
                pass
        self._clear_preview()
        self._refresh()

    def _schedule_target_poll(self) -> None:
        self._target_after = self.window.after(self._TARGET_POLL_MS, self._poll_target)

    def _poll_target(self) -> None:
        self._target_after = None
        if self._closed:
            return
        target = self._safe_target()
        if target != self._target:
            self._target = target
            self.cancel_work()
            self._status_var.set("Selected Roblox window changed. Take a new preview.")
        self._refresh()
        self._schedule_target_poll()

    def _refresh(self) -> None:
        if self._closed:
            return
        target = self._safe_target()
        binding = self._binding_pending()
        input_busy = self._input_busy()
        working = self._job is not None
        if binding:
            self._target_var.set("Binding Roblox window. Focus it yourself; no input will be sent.")
        elif target is None:
            self._target_var.set("No Roblox window selected.")
        else:
            self._target_var.set("Roblox window selected.")
        disabled = input_busy or binding or working
        self.bind_button.configure(state="disabled" if disabled else "normal")
        self.capture_button.configure(
            state="normal" if target is not None and not disabled else "disabled"
        )
        self.sdk_button.configure(state="disabled" if disabled else "normal")
        self.close_button.configure(state="normal")

    def _on_escape(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if self._job is not None:
            self.cancel_work()
            self._status_var.set("Preview check cancelled. No input was sent.")
        elif self._binding_pending():
            self._cancel_binding()
            self._status_var.set("Binding cancelled. No input was sent.")
            self._refresh()
        else:
            self.close()
        return "break"

    def _on_configure(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if self._closed or self._resize_after is not None:
            return
        self._resize_after = self.window.after_idle(self._rerender_after_resize)

    def _rerender_after_resize(self) -> None:
        self._resize_after = None
        if self._snapshot is not None and not self._closed:
            self._render_preview()
        else:
            self._center_preview_text()

    def _center_preview_text(self) -> None:
        width = max(1, self.preview_canvas.winfo_width())
        height = max(1, self.preview_canvas.winfo_height())
        self.preview_canvas.coords(self._preview_item, width // 2, height // 2)
        self.preview_canvas.itemconfigure(self._preview_item, width=max(1, width - 20))

    def _update_preview_text(self) -> None:
        self.preview_canvas.itemconfigure(self._preview_item, text=self._preview_var.get())

    def _render_preview(self) -> None:
        frame = self._snapshot
        if frame is None or self._closed:
            return
        canvas_width = max(1, self.preview_canvas.winfo_width())
        canvas_height = max(1, self.preview_canvas.winfo_height())
        source_width, source_height = frame.physical_size
        display_width = min(canvas_width, self._PREVIEW_MAX_WIDTH)
        display_height = min(canvas_height, self._PREVIEW_MAX_HEIGHT)
        factor = max(1, math.ceil(source_width / display_width), math.ceil(source_height / display_height))
        rgb, width, height = self._bgr_to_rgb_subsample(frame.pixels, source_width, source_height, factor)
        ppm = b"P6\n%d %d\n255\n" % (width, height) + bytes(rgb)
        self._preview_pixels = rgb
        self._photo = tk.PhotoImage(data=ppm, format="PPM")
        x = max(0, (canvas_width - width) // 2)
        y = max(0, (canvas_height - height) // 2)
        self.preview_canvas.itemconfigure(self._preview_item, state="hidden")
        self.preview_canvas.itemconfigure(self._photo_item, image=self._photo, state="normal")
        self.preview_canvas.coords(self._photo_item, x, y)

    @staticmethod
    def _bgr_to_rgb_subsample(
        pixels: bytes, width: int, height: int, factor: int
    ) -> tuple[bytearray, int, int]:
        """Convert packed BGR8 with one integer subsample factor, no image library."""
        output_width = (width + factor - 1) // factor
        output_height = (height + factor - 1) // factor
        output = bytearray(output_width * output_height * 3)
        destination = 0
        for y in range(0, height, factor):
            source = y * width * 3
            for x in range(0, width, factor):
                offset = source + x * 3
                output[destination] = pixels[offset + 2]
                output[destination + 1] = pixels[offset + 1]
                output[destination + 2] = pixels[offset]
                destination += 3
        return output, output_width, output_height

    def _clear_preview(self) -> None:
        self._snapshot = None
        self._preview_pixels = None
        self._photo = None
        if not self._closed:
            self.preview_canvas.itemconfigure(self._photo_item, image="", state="hidden")
            self.preview_canvas.itemconfigure(self._preview_item, state="normal")
            self._preview_var.set(
                "Snapshot\nPreview only. Game layout recognition is not configured yet."
            )
            self._frame_note_var.set(
                "Snapshot preview stays in memory. Game layout recognition is not configured yet."
            )
            self._update_preview_text()
            self._center_preview_text()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._target_after is not None:
            try:
                self.window.after_cancel(self._target_after)
            except tk.TclError:
                pass
            self._target_after = None
        if self._resize_after is not None:
            try:
                self.window.after_cancel(self._resize_after)
            except tk.TclError:
                pass
            self._resize_after = None
        self.cancel_work()
        try:
            self._cancel_binding()
        except Exception:
            pass
        try:
            self.window.grab_release()
        except tk.TclError:
            pass
        try:
            self.window.destroy()
        except tk.TclError:
            pass
