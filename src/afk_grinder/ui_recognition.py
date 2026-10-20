"""Recognition setup preview UI with no input or persistent image path."""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable
from time import monotonic
from typing import Any
from tkinter import ttk

from afk_grinder.capture import CapturedWindow
from afk_grinder.capture.service import BackgroundJob, JobResult
from afk_grinder.models import Target
from afk_grinder.recognition.frame_geometry import layout_from_capture
from afk_grinder.recognition.observation import Calibration, Layout, ObservationTracker, Rect


class RecognitionSetup:
    """Small, cancellable window-only preview and geometry dialog."""

    _POLL_MS = 20
    _TARGET_POLL_MS = 100
    _FRESH_SECONDS = 0.5
    _REFERENCE_SIZE = (1280, 720)
    _REFERENCE_RATIO = _REFERENCE_SIZE[0] / _REFERENCE_SIZE[1]
    _PREVIEW_MAX_WIDTH = 560
    _PREVIEW_MAX_HEIGHT = 360
    _KEY_STEP = 8

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
        self._layout: Layout | None = None
        self._tracker = ObservationTracker()
        self._calibration: Calibration | None = None
        self._selection: Rect | None = None
        self._pending_roi: Rect | None = None
        self._pending_layout: Layout | None = None
        self._drag_start: tuple[float, float] | None = None
        self._last_captured_at: float | None = None
        self._preview_pixels: bytearray | None = None
        self._photo: tk.PhotoImage | None = None
        self._display_box: tuple[int, int, int, int] | None = None

        self.window = tk.Toplevel(parent)
        self.window.title("Recognition setup")
        self.window.geometry("620x700")
        self.window.minsize(440, 560)
        self.window.transient(parent.winfo_toplevel())
        self.window.resizable(True, True)
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self.window.bind("<Escape>", self._on_escape)
        self.window.bind("<Configure>", self._on_configure)
        self.window.grab_set()

        self._target_var = tk.StringVar(value="No Roblox window selected.")
        self._status_var = tk.StringVar(value="Bind Roblox, then take a preview.")
        self._sdk_var = tk.StringVar(value="SDK check has not run.")
        self._preview_var = tk.StringVar(value="Snapshot\nPreview only. Game layout recognition is not configured yet.")
        self._frame_note_var = tk.StringVar(value="Snapshot preview stays in memory. Game layout recognition is not configured yet.")
        self._selection_var = tk.StringVar(value="Area: none selected.")
        self._geometry_var = tk.StringVar(value="Anchors: not configured. Targets: not configured.")
        self._wrap_labels: list[ttk.Label] = []
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
        ttk.Label(outer, text="Recognition setup", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        self._label(outer, "Captures only selected Roblox window. Preview stays in memory. Nothing is saved, uploaded, or used for input.", row=1, pady=(3, 8))

        controls = ttk.Frame(outer)
        controls.grid(row=2, column=0, sticky="ew")
        controls.columnconfigure(0, weight=1)
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(2, weight=1)
        self.bind_button = ttk.Button(controls, text="Bind Roblox", command=self._start_binding)
        self.capture_button = ttk.Button(controls, text="Capture preview", command=self.capture_preview)
        self.check_button = ttk.Button(controls, text="Refresh and check area", command=self.refresh_and_check_area)
        self.full_button = ttk.Button(controls, text="Use full preview", command=self.use_full_preview)
        self.reset_button = ttk.Button(controls, text="Reset area", command=self.reset_area)
        self.sdk_button = ttk.Button(controls, text="Check recognition SDK", command=self.run_sdk_check)
        self.close_button = ttk.Button(controls, text="Close", command=self.close)
        self.bind_button.grid(row=0, column=0, sticky="ew", padx=(0, 4), pady=(0, 4))
        self.capture_button.grid(row=0, column=1, sticky="ew", padx=(0, 4), pady=(0, 4))
        self.close_button.grid(row=0, column=2, sticky="ew", pady=(0, 4))
        self.check_button.grid(row=1, column=0, columnspan=2, sticky="ew", padx=(0, 4), pady=(0, 4))
        self.full_button.grid(row=1, column=2, sticky="ew", pady=(0, 4))
        self.reset_button.grid(row=2, column=0, sticky="ew", padx=(0, 4))
        self.sdk_button.grid(row=2, column=1, columnspan=2, sticky="ew")

        self._label(outer, self._target_var, row=3, pady=(3, 0), variable=True)
        preview = ttk.LabelFrame(outer, text="Snapshot", padding=6)
        preview.grid(row=4, column=0, sticky="nsew", pady=(8, 0))
        preview.columnconfigure(0, weight=1)
        preview.rowconfigure(0, weight=1, minsize=96)
        self.preview_canvas = tk.Canvas(preview, width=520, height=260, highlightthickness=1, highlightbackground="#00d9ff", highlightcolor="#00d9ff", takefocus=True)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self._preview_item = self.preview_canvas.create_text(260, 130, text=self._preview_var.get(), justify="center", width=500)
        self._photo_item = self.preview_canvas.create_image(0, 0, anchor="nw", state="hidden")
        self._selection_item = self.preview_canvas.create_rectangle(0, 0, 0, 0, outline="#00d9ff", width=2, state="hidden")
        self.preview_canvas.bind("<ButtonPress-1>", self._on_preview_press)
        self.preview_canvas.bind("<B1-Motion>", self._on_preview_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_preview_release)
        self.preview_canvas.bind("<Return>", self._on_canvas_activate)
        self.preview_canvas.bind("<space>", self._on_canvas_activate)
        self.preview_canvas.bind("<r>", self._on_canvas_reset)
        self.preview_canvas.bind("<R>", self._on_canvas_reset)
        for sequence, delta in (("<Left>", (-1, 0)), ("<Right>", (1, 0)), ("<Up>", (0, -1)), ("<Down>", (0, 1))):
            self.preview_canvas.bind(sequence, lambda event, delta=delta: self._on_arrow(delta, False))
            self.preview_canvas.bind(f"<Shift-{sequence[1:]}", lambda event, delta=delta: self._on_arrow(delta, True))
        self._label(preview, self._frame_note_var, row=1, pady=(5, 0), variable=True)
        self._label(preview, self._selection_var, row=2, pady=(3, 0), variable=True)
        self._label(outer, "Tab Snapshot: Enter/Space centers 16:9. Arrows move; Shift+arrows resize; R resets. Letterbox unavailable.", row=5, pady=(5, 0))
        self._label(outer, "Demo ref 1280 × 720 (16:9). No minimum supported size; not game support.", row=6, pady=(2, 0))
        self._label(outer, self._geometry_var, row=7, pady=(3, 0), variable=True)
        self._label(outer, self._sdk_var, row=8, pady=(3, 0), variable=True)
        self._label(outer, self._status_var, row=9, pady=(3, 0), variable=True)

    def _label(self, parent: tk.Misc, value: str | tk.StringVar, *, row: int, pady: tuple[int, int], variable: bool = False) -> None:
        label = ttk.Label(parent, textvariable=value if variable else None, text="" if variable else value, wraplength=560)
        label.grid(row=row, column=0, sticky="w", pady=pady)
        self._wrap_labels.append(label)

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
        self._start_capture_job(target, "capture")

    def refresh_and_check_area(self) -> None:
        if self._closed or self._job is not None or self._input_busy() or self._binding_pending():
            return
        target = self._safe_target()
        if target is None or self._selection is None or self._layout is None:
            self._status_var.set("Select a 16:9 area before checking it.")
            return
        self._pending_roi = self._selection
        self._pending_layout = self._layout
        self._clear_preview(clear_pending=False)
        self._start_capture_job(target, "check")

    def _start_capture_job(self, target: Target, kind: str) -> None:
        try:
            job = self._job_factory("capture", target)
        except Exception:
            self._clear_preview()
            self._status_var.set("Could not start preview. No input was sent.")
            self._refresh()
            return
        self._start_job(job, kind)
        self._status_var.set("Taking fresh window-only preview. No input was sent." if kind == "capture" else "Refreshing selected area. Old pixels and calibration were cleared.")

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
        elif kind == "check":
            self._handle_check_result(result)
        else:
            self._handle_sdk_result(result)
        self._refresh()

    def _handle_capture_result(self, result: JobResult) -> None:
        if result.error or result.frame is None:
            self._clear_preview()
            self._status_var.set(self._capture_error(result.error))
            return
        if not self._frame_has_current_target(result.frame):
            self._clear_preview()
            self._status_var.set("Selected Roblox window changed. Take a new preview.")
            return
        if self._accept_snapshot(result.frame):
            if self._tracker.latest is None:
                self._status_var.set("Snapshot is historical reference only. Edit area, then refresh and check it.")
            else:
                self._status_var.set("Snapshot ready in memory. Select a 16:9 area, then refresh and check it.")

    def _handle_check_result(self, result: JobResult) -> None:
        pending_roi, pending_layout = self._pending_roi, self._pending_layout
        self._pending_roi = self._pending_layout = None
        if result.error or result.frame is None:
            self._clear_preview()
            self._status_var.set("Area check failed. Select an area from a new preview.")
            return
        if not self._frame_has_current_target(result.frame):
            self._clear_preview()
            self._status_var.set("Selected Roblox window changed. Select an area from a new preview.")
            return
        now = monotonic()
        if not self._valid_frame_time(result.frame, now, require_fresh=True):
            self._clear_preview()
            self._status_var.set("Fresh area check failed. Recapture and select the area again.")
            return
        try:
            layout = layout_from_capture(result.frame)
        except (TypeError, ValueError):
            self._clear_preview()
            self._status_var.set("Area check failed. Capture geometry was invalid; recapture.")
            return
        if pending_roi is None or pending_layout is None or layout != pending_layout:
            self._clear_preview()
            self._status_var.set("Window layout changed. Select the area again from a new preview.")
            return
        try:
            observation = self._tracker.accept(layout, result.frame.pixels, result.frame.captured_at, now, self._FRESH_SECONDS)
            calibration = self._tracker.calibrate(self._REFERENCE_SIZE, pending_roi, now=now)
        except ValueError:
            self._clear_preview()
            self._status_var.set("Fresh area check failed. Recapture and select the area again.")
            return
        self._snapshot = result.frame
        self._last_captured_at = result.frame.captured_at
        self._layout = observation.layout
        self._calibration = calibration
        self._selection = pending_roi
        self._set_frame_note(result.frame)
        self._selection_var.set(self._selection_text(pending_roi))
        self._geometry_var.set("Snapshot geometry matches reference. Anchors: not configured. Targets: not configured.")
        self._preview_var.set("Snapshot")
        self._update_preview_text()
        self._render_preview()
        self._status_var.set("Fresh matching-frame geometry check completed. Preview evidence only; no input was sent.")

    def _frame_has_current_target(self, frame: CapturedWindow) -> bool:
        target = self._safe_target()
        return target is not None and frame.target == target

    def _accept_snapshot(self, frame: CapturedWindow) -> bool:
        now = monotonic()
        try:
            layout = layout_from_capture(frame)
        except (TypeError, ValueError):
            self._clear_preview()
            self._status_var.set("Preview geometry was invalid. Capture a new preview.")
            return False
        if not self._valid_frame_time(frame, now, require_fresh=False):
            self._clear_preview()
            self._status_var.set("Preview timing was invalid. Capture a new preview.")
            return False
        self._snapshot = frame
        self._layout = layout
        self._last_captured_at = frame.captured_at
        self._calibration = None
        self._set_frame_note(frame)
        self._preview_var.set("Snapshot")
        self._update_preview_text()
        self._render_preview()
        if now - frame.captured_at > self._FRESH_SECONDS:
            self._tracker.invalidate()
            self._mark_historical()
            return True
        try:
            self._tracker.accept(layout, frame.pixels, frame.captured_at, now, self._FRESH_SECONDS)
        except ValueError:
            self._clear_preview()
            self._status_var.set("Preview timing was invalid. Capture a new preview.")
            return False
        return True

    def _valid_frame_time(self, frame: CapturedWindow, now: float, *, require_fresh: bool) -> bool:
        if (not math.isfinite(frame.captured_at) or frame.captured_at > now
                or (self._last_captured_at is not None and frame.captured_at <= self._last_captured_at)):
            return False
        return not require_fresh or now - frame.captured_at <= self._FRESH_SECONDS

    def _set_frame_note(self, frame: CapturedWindow) -> None:
        if frame.region_kind == "window-unverified" or not frame.content_verified:
            self._frame_note_var.set("Snapshot. Preview includes window frame. Game content bounds are not verified.")
        else:
            self._frame_note_var.set("Snapshot preview stays in memory. Game layout recognition is not configured yet.")

    @staticmethod
    def _capture_error(error: str) -> str:
        lowered = error.casefold()
        if "screen recording" in lowered or "permission" in lowered:
            return "Screen Recording permission needed. Open System Settings, allow it, then retry."
        if "timeout" in lowered or "timed out" in lowered:
            return "Preview timed out. Check the selected Roblox window, then try again."
        if any(word in lowered for word in ("multiple", "more than one", "ambiguous")):
            return "More than one matching Roblox window is available. Bind the intended window, then try again."
        if any(word in lowered for word in ("geometry", "bounds", "dimensions", "size", "rect")):
            return "Preview geometry was invalid. Rebind or resize Roblox, then try again."
        if any(word in lowered for word in ("conversion", "convert", "bgr", "pixel buffer")):
            return "Preview conversion failed. Try again."
        return "Could not take preview. No input was sent."

    def _handle_sdk_result(self, result: JobResult) -> None:
        self._sdk_var.set("SDK unavailable. Input remains disabled." if result.error or result.report is None else "SDK compatible. Synthetic only; input remains disabled.")

    def _is_fresh(self) -> bool:
        latest = self._tracker.latest
        return latest is not None and self._layout is not None and latest.layout == self._layout and 0 <= monotonic() - latest.captured_at <= self._FRESH_SECONDS

    def _mark_historical(self) -> None:
        if self._snapshot is None:
            return
        if self._tracker.latest is not None:
            self._tracker.invalidate()
        self._calibration = None
        if self._layout is not None and (
            self._layout.region_kind == "window-unverified" or not self._layout.content_verified
        ):
            self._frame_note_var.set(
                "Snapshot. Preview includes window frame. Game content bounds are not verified. "
                "Historical reference only."
            )
        else:
            self._frame_note_var.set("Snapshot historical reference only. Edit area, then refresh and check a fresh frame.")
        if self._selection is not None:
            self._selection_var.set("Area retained for historical reference only.")
        self._geometry_var.set("Historical reference only. Anchors: not configured. Targets: not configured.")
        self._status_var.set("Snapshot is historical reference only. Edit area, then refresh and check a fresh frame.")
        self._refresh()

    def _on_preview_press(self, event: tk.Event[tk.Misc]) -> str:
        point = self._canvas_to_pixel(event.x, event.y)
        if point is None:
            self._status_var.set("Select inside displayed image; letterbox space is excluded.")
            return "break"
        self.preview_canvas.focus_set()
        self._drag_start = point
        self._selection = None
        self._calibration = None
        self._geometry_var.set("Anchors: not configured. Targets: not configured.")
        self._draw_selection()
        return "break"

    def _on_preview_drag(self, event: tk.Event[tk.Misc]) -> str:
        if self._drag_start is None:
            return "break"
        point = self._canvas_to_pixel(event.x, event.y)
        if point is not None:
            self._selection = self._drag_selection(self._drag_start, point)
            self._selection_var.set(self._selection_text(self._selection))
            self._draw_selection()
        return "break"

    def _on_preview_release(self, _event: tk.Event[tk.Misc]) -> str:
        if self._drag_start is None:
            return "break"
        self._drag_start = None
        if self._selection is None or min(self._selection.width, self._selection.height) < 8:
            self.reset_area()
            self._status_var.set("Drag a larger 16:9 area inside the displayed image.")
        else:
            self._status_var.set("Area selected. Refresh and check area when ready.")
        self._refresh()
        return "break"

    def _on_canvas_activate(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        if self._snapshot is None or self._layout is None or self._selection is not None:
            return "break"
        width, height = self._snapshot.physical_size
        if width / height >= self._REFERENCE_RATIO:
            roi_height = float(height)
            roi_width = roi_height * self._REFERENCE_RATIO
        else:
            roi_width = float(width)
            roi_height = roi_width / self._REFERENCE_RATIO
        self._selection = Rect((width - roi_width) / 2, (height - roi_height) / 2, roi_width, roi_height)
        self._calibration = None
        self._selection_var.set(self._selection_text(self._selection))
        self._geometry_var.set("Anchors: not configured. Targets: not configured.")
        self._draw_selection()
        self._status_var.set("Centered 16:9 area selected. Refresh and check area when ready.")
        self._refresh()
        return "break"

    def _on_canvas_reset(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        self.reset_area()
        self._status_var.set("Area reset.")
        return "break"

    def _drag_selection(self, start: tuple[float, float], end: tuple[float, float]) -> Rect:
        assert self._snapshot is not None
        width, height = self._snapshot.physical_size
        dx, dy = end[0] - start[0], end[1] - start[1]
        direction_x, direction_y = (1 if dx >= 0 else -1), (1 if dy >= 0 else -1)
        candidate_width = max(0.001, abs(dx), abs(dy) * self._REFERENCE_RATIO)
        candidate_height = candidate_width / self._REFERENCE_RATIO
        max_width = (width - start[0]) if direction_x > 0 else start[0]
        max_height = (height - start[1]) if direction_y > 0 else start[1]
        scale = min(1.0, max_width / candidate_width if candidate_width else 0, max_height / candidate_height if candidate_height else 0)
        candidate_width *= scale
        candidate_height *= scale
        x = start[0] if direction_x > 0 else start[0] - candidate_width
        y = start[1] if direction_y > 0 else start[1] - candidate_height
        return Rect(max(0, x), max(0, y), candidate_width, candidate_height)

    def _on_arrow(self, direction: tuple[int, int], resize: bool) -> str:
        if self._selection is None or self._snapshot is None:
            return "break"
        width, height = self._snapshot.physical_size
        roi = self._selection
        if resize:
            delta = direction[0] * self._KEY_STEP + direction[1] * self._KEY_STEP * self._REFERENCE_RATIO
            new_width = min(width, max(8 * self._REFERENCE_RATIO, roi.width + delta))
            new_height = new_width / self._REFERENCE_RATIO
            if roi.x + new_width > width:
                new_width, new_height = width - roi.x, (width - roi.x) / self._REFERENCE_RATIO
            if roi.y + new_height > height:
                new_height, new_width = height - roi.y, (height - roi.y) * self._REFERENCE_RATIO
            self._selection = Rect(roi.x, roi.y, new_width, new_height)
        else:
            self._selection = Rect(min(max(0, roi.x + direction[0] * self._KEY_STEP), width - roi.width), min(max(0, roi.y + direction[1] * self._KEY_STEP), height - roi.height), roi.width, roi.height)
        self._calibration = None
        self._selection_var.set(self._selection_text(self._selection))
        self._geometry_var.set("Anchors: not configured. Targets: not configured.")
        self._draw_selection()
        self._status_var.set("Area adjusted. Refresh and check area when ready.")
        return "break"

    def use_full_preview(self) -> None:
        if self._snapshot is None or self._layout is None:
            return
        if self._layout.region_kind == "window-unverified" or not self._layout.content_verified:
            self._status_var.set("Raw window preview needs a manual area; full crop is not automatic.")
            return
        width, height = self._snapshot.physical_size
        if abs((width / height) - self._REFERENCE_RATIO) > 0.01:
            self._status_var.set("Preview is not 16:9. Drag a 16:9 area inside it.")
            return
        self._selection = Rect(0, 0, width, height)
        self._calibration = None
        self._selection_var.set(self._selection_text(self._selection))
        self._draw_selection()
        self._status_var.set("Full verified preview selected. Refresh and check area when ready.")
        self._refresh()

    def reset_area(self) -> None:
        self._selection = None
        self._calibration = None
        self._selection_var.set("Area: none selected.")
        self._geometry_var.set("Anchors: not configured. Targets: not configured.")
        if hasattr(self, "preview_canvas"):
            self.preview_canvas.itemconfigure(self._selection_item, state="hidden")
        self._refresh()

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
        elif self._snapshot is not None and self._tracker.latest is not None and not self._is_fresh():
            self._mark_historical()
        self._refresh()
        self._schedule_target_poll()

    def _refresh(self) -> None:
        if self._closed:
            return
        target = self._safe_target()
        binding, input_busy, working = self._binding_pending(), self._input_busy(), self._job is not None
        if binding:
            self._target_var.set("Binding Roblox window. Focus it yourself; no input will be sent.")
        elif target is None:
            self._target_var.set("No Roblox window selected.")
        else:
            self._target_var.set("Roblox window selected.")
        disabled = input_busy or binding or working
        self.bind_button.configure(state="disabled" if disabled else "normal")
        self.capture_button.configure(state="normal" if target is not None and not disabled else "disabled")
        self.check_button.configure(state="normal" if self._selection is not None and self._layout is not None and not disabled else "disabled")
        can_full = self._snapshot is not None and self._layout is not None and self._layout.region_kind == "client" and self._layout.content_verified
        self.full_button.configure(state="normal" if can_full and not disabled else "disabled")
        self.reset_button.configure(state="normal" if self._selection is not None and not disabled else "disabled")
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
        wraplength = max(320, self.window.winfo_width() - 40)
        for label in self._wrap_labels:
            label.configure(wraplength=wraplength)
        if self._snapshot is not None and not self._closed:
            self._render_preview()
        else:
            self._center_preview_text()

    def _center_preview_text(self) -> None:
        width, height = max(1, self.preview_canvas.winfo_width()), max(1, self.preview_canvas.winfo_height())
        self.preview_canvas.coords(self._preview_item, width // 2, height // 2)
        self.preview_canvas.itemconfigure(self._preview_item, width=max(1, width - 20))

    def _update_preview_text(self) -> None:
        self.preview_canvas.itemconfigure(self._preview_item, text=self._preview_var.get())

    def _render_preview(self) -> None:
        frame = self._snapshot
        if frame is None or self._closed:
            return
        canvas_width, canvas_height = max(1, self.preview_canvas.winfo_width()), max(1, self.preview_canvas.winfo_height())
        source_width, source_height = frame.physical_size
        factor = max(1, math.ceil(source_width / min(canvas_width, self._PREVIEW_MAX_WIDTH)), math.ceil(source_height / min(canvas_height, self._PREVIEW_MAX_HEIGHT)))
        rgb, width, height = self._bgr_to_rgb_subsample(frame.pixels, source_width, source_height, factor)
        self._preview_pixels = rgb
        self._photo = tk.PhotoImage(data=b"P6\n%d %d\n255\n" % (width, height) + bytes(rgb), format="PPM")
        x, y = max(0, (canvas_width - width) // 2), max(0, (canvas_height - height) // 2)
        self._display_box = (x, y, width, height)
        self.preview_canvas.itemconfigure(self._preview_item, state="hidden")
        self.preview_canvas.itemconfigure(self._photo_item, image=self._photo, state="normal")
        self.preview_canvas.coords(self._photo_item, x, y)
        self._draw_selection()

    def _canvas_to_pixel(self, x: int, y: int) -> tuple[float, float] | None:
        if self._snapshot is None or self._display_box is None:
            return None
        left, top, width, height = self._display_box
        if not left <= x < left + width or not top <= y < top + height:
            return None
        source_width, source_height = self._snapshot.physical_size
        return (min(source_width - 0.001, max(0.0, (x - left) * source_width / width)), min(source_height - 0.001, max(0.0, (y - top) * source_height / height)))

    def _draw_selection(self) -> None:
        if self._selection is None or self._display_box is None or self._snapshot is None:
            self.preview_canvas.itemconfigure(self._selection_item, state="hidden")
            return
        left, top, display_width, display_height = self._display_box
        source_width, source_height = self._snapshot.physical_size
        roi = self._selection
        self.preview_canvas.coords(self._selection_item, left + roi.x * display_width / source_width, top + roi.y * display_height / source_height, left + (roi.x + roi.width) * display_width / source_width, top + (roi.y + roi.height) * display_height / source_height)
        self.preview_canvas.itemconfigure(self._selection_item, state="normal")

    @staticmethod
    def _selection_text(roi: Rect) -> str:
        return f"Area: {roi.width:.0f} × {roi.height:.0f} pixels (16:9 preview reference)."

    @staticmethod
    def _bgr_to_rgb_subsample(pixels: bytes, width: int, height: int, factor: int) -> tuple[bytearray, int, int]:
        output_width, output_height = (width + factor - 1) // factor, (height + factor - 1) // factor
        output = bytearray(output_width * output_height * 3)
        destination = 0
        for y in range(0, height, factor):
            source = y * width * 3
            for x in range(0, width, factor):
                offset = source + x * 3
                output[destination], output[destination + 1], output[destination + 2] = pixels[offset + 2], pixels[offset + 1], pixels[offset]
                destination += 3
        return output, output_width, output_height

    def _clear_preview(self, *, clear_pending: bool = True) -> None:
        self._snapshot = self._layout = None
        self._tracker.invalidate()
        self._calibration = self._selection = self._drag_start = None
        self._preview_pixels = self._photo = self._display_box = None
        if clear_pending:
            self._pending_roi = self._pending_layout = None
        self._selection_var.set("Area: none selected.")
        self._geometry_var.set("Anchors: not configured. Targets: not configured.")
        if not self._closed:
            self.preview_canvas.itemconfigure(self._photo_item, image="", state="hidden")
            self.preview_canvas.itemconfigure(self._selection_item, state="hidden")
            self.preview_canvas.itemconfigure(self._preview_item, state="normal")
            self._preview_var.set("Snapshot\nPreview only. Game layout recognition is not configured yet.")
            self._frame_note_var.set("Snapshot preview stays in memory. Game layout recognition is not configured yet.")
            self._update_preview_text()
            self._center_preview_text()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for timer in (self._target_after, self._resize_after):
            if timer is not None:
                try:
                    self.window.after_cancel(timer)
                except tk.TclError:
                    pass
        self._target_after = self._resize_after = None
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
