"""Tk controls for short, supervised input tests.

The worker thread owns all input work.  This module only reads its status queue
from Tk's event loop and never asks Tk widgets to update from that worker.
"""

from __future__ import annotations

import queue
import sys
import tkinter as tk
from tkinter import messagebox, ttk

from .engine import Runner, Status
from .models import Backend, Target, Workflow
from .templates import COUNTDOWN_SECONDS, DEFAULT_TEMPLATE, parse_template


_BACKEND_UNSET = object()
_POLL_MS = 20
_MAX_LOG_LINES = 100


class App:
    """Small desktop UI.  ``backend=None`` is useful for dry-run GUI tests."""

    def __init__(self, root: tk.Misc, backend: Backend | None | object = _BACKEND_UNSET):
        self.root = root
        self.backend: Backend | None
        self._backend_available = True
        if backend is _BACKEND_UNSET:
            try:
                from .backends import create_backend

                self.backend = create_backend()
            except Exception:
                self.backend = None
                self._backend_available = False
        else:
            self.backend = backend  # type: ignore[assignment]

        self.runner = Runner(self.backend)
        self.target: Target | None = None
        self._binding_after: str | None = None
        self._validation_after: str | None = None
        self._poll_after: str | None = None
        self._run_locked = False
        self._terminal_received = False
        self._closing = False
        self._close_error_acknowledged = False
        self._log_lines: list[str] = []
        self._readiness_ok = False

        self.mode_var = tk.StringVar(master=root, value="dry")
        self.confirm_var = tk.BooleanVar(master=root, value=False)
        self.status_var = tk.StringVar(master=root, value="Ready for a dry run.")
        self.validation_var = tk.StringVar(master=root, value="")
        self.target_var = tk.StringVar(master=root, value="No Roblox target bound.")
        self.readiness_var = tk.StringVar(master=root, value="Refresh before a live run.")
        self._workflow: Workflow | None = None

        self._build()
        self.mode_var.trace_add("write", self._on_mode_change)
        self.confirm_var.trace_add("write", self._on_confirmation_change)
        self._load_default()
        self._on_mode_change()
        if self.backend is None:
            self.readiness_var.set("Live input unavailable. Dry run still works.")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<Escape>", self._on_escape)
        if sys.platform == "darwin":
            self.root.createcommand("::tk::mac::Quit", self._on_close)
            self.root.bind("<Command-q>", self._on_quit_key)

    def _build(self) -> None:
        self.root.title("AFK Grinder — Supervised Input Test")
        self.root.geometry("800x800")
        self.root.minsize(640, 620)

        outer = ttk.Frame(self.root, padding=12)
        outer.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(5, weight=1)

        ttk.Label(outer, text="Local supervised input test", style="Title.TLabel").grid(
            row=0, column=0, sticky="w")
        ttk.Label(
            outer,
            text="No login automation. No recording. You keep Roblox and gameplay under your control.",
            wraplength=740,
        ).grid(row=1, column=0, sticky="w", pady=(2, 10))

        mode = ttk.LabelFrame(outer, text="Mode", padding=8)
        mode.grid(row=2, column=0, sticky="ew")
        self.dry_radio = ttk.Radiobutton(
            mode, text="DRY RUN — no OS input", value="dry", variable=self.mode_var,
            command=self._on_mode_change,
        )
        self.dry_radio.grid(row=0, column=0, sticky="w", padx=(0, 18))
        self.live_radio = ttk.Radiobutton(
            mode, text="LIVE INPUT — Roblox only", value="live", variable=self.mode_var,
            command=self._on_mode_change,
        )
        self.live_radio.grid(row=0, column=1, sticky="w")

        self.live_frame = ttk.LabelFrame(outer, text="Live target and checks", padding=8)
        self.live_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.live_frame.columnconfigure(0, weight=1)
        self.bind_button = ttk.Button(self.live_frame, text="Bind Roblox after 3 seconds", command=self._begin_binding)
        self.bind_button.grid(row=0, column=0, sticky="w")
        ttk.Label(self.live_frame, textvariable=self.target_var, wraplength=710).grid(
            row=1, column=0, sticky="w", pady=(4, 0))
        self.refresh_button = ttk.Button(self.live_frame, text="Refresh readiness", command=self._refresh_readiness)
        self.refresh_button.grid(row=2, column=0, sticky="w", pady=(7, 0))
        ttk.Label(self.live_frame, textvariable=self.readiness_var, wraplength=710).grid(
            row=3, column=0, sticky="w", pady=(4, 0))
        self.confirm_check = ttk.Checkbutton(
            self.live_frame,
            text="I confirm I am signed in, gameplay is visible, and chat and menus are closed.",
            variable=self.confirm_var,
        )
        self.confirm_check.grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Label(
            self.live_frame,
            text="This is your manual check; the app does not inspect Roblox.",
            wraplength=710,
        ).grid(row=5, column=0, sticky="w", pady=(2, 0))

        editor_frame = ttk.LabelFrame(outer, text="Workflow JSON", padding=8)
        editor_frame.grid(row=4, column=0, sticky="ew", pady=(8, 0))
        editor_frame.columnconfigure(0, weight=1)
        self.load_button = ttk.Button(editor_frame, text="Load default", command=self._load_default)
        self.load_button.grid(row=0, column=0, sticky="w")
        self.validate_button = ttk.Button(editor_frame, text="Validate", command=self._validate)
        self.validate_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(
            editor_frame,
            text="Actions: hold_key (allowed movement keys), wait, click (fixed 80 ms at current pointer).",
            wraplength=710,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        ttk.Label(editor_frame, textvariable=self.validation_var, wraplength=710).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(3, 0))

        text_frame = ttk.Frame(outer)
        text_frame.grid(row=5, column=0, sticky="nsew", pady=(8, 0))
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.editor = tk.Text(text_frame, height=14, wrap="none", undo=True)
        self.editor.grid(row=0, column=0, sticky="nsew")
        editor_scroll = ttk.Scrollbar(text_frame, orient="vertical", command=self.editor.yview)
        editor_scroll.grid(row=0, column=1, sticky="ns")
        self.editor.configure(yscrollcommand=editor_scroll.set)
        self.editor.bind("<<Modified>>", self._on_editor_modified)

        action = ttk.Frame(outer)
        action.grid(row=6, column=0, sticky="ew", pady=(8, 0))
        action.columnconfigure(2, weight=1)
        self.start_button = ttk.Button(action, text="Start dry run", command=self._start)
        self.start_button.grid(row=0, column=0, sticky="w")
        self.stop_button = ttk.Button(action, text="Stop", command=self._stop, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="w", padx=(8, 0))
        ttk.Label(action, textvariable=self.status_var, wraplength=520).grid(row=0, column=2, sticky="w", padx=(12, 0))

        log_frame = ttk.LabelFrame(outer, text="Status log", padding=6)
        log_frame.grid(row=7, column=0, sticky="ew", pady=(8, 0))
        log_frame.columnconfigure(0, weight=1)
        self.log = tk.Text(log_frame, height=6, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="ew")

        self._setup_controls: tuple[tk.Widget, ...] = (
            self.dry_radio, self.live_radio, self.bind_button, self.refresh_button,
            self.confirm_check, self.load_button, self.validate_button, self.editor,
        )

    def _load_default(self) -> None:
        if self._run_locked:
            return
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", DEFAULT_TEMPLATE)
        self.editor.edit_modified(False)
        self._validate()

    def _on_editor_modified(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if not self.editor.edit_modified():
            return
        self.editor.edit_modified(False)
        if self._run_locked:
            return
        if self._validation_after is not None:
            self.root.after_cancel(self._validation_after)
        self._validation_after = self.root.after(250, self._validate)

    def _validate(self) -> bool:
        self._validation_after = None
        try:
            workflow = parse_template(self.editor.get("1.0", "end-1c"))
        except (TypeError, ValueError) as exc:
            self._workflow = None
            self.validation_var.set(f"Template error: {exc}")
            self._refresh_controls()
            return False
        self._workflow = workflow
        action_ms = sum(step.duration_ms for step in workflow.steps)
        total_ms = action_ms + int(COUNTDOWN_SECONDS * 1000)
        self.validation_var.set(
            f"Valid: {len(workflow.steps)} steps; actions {action_ms / 1000:.2f}s; "
            f"including 3.00s countdown {total_ms / 1000:.2f}s / 30.00s cap."
        )
        self._refresh_controls()
        return True

    def _on_mode_change(self, *_unused: object) -> None:
        live = self.mode_var.get() == "live"
        if live:
            self.live_frame.grid()
            self.start_button.configure(text="Start live run")
        else:
            self.live_frame.grid_remove()
            self.confirm_var.set(False)
            self.start_button.configure(text="Start dry run")
        self._refresh_controls()

    def _on_confirmation_change(self, *_unused: object) -> None:
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        """Keep every start gate visible in widget state, without idle polling."""
        busy = self._run_locked or self._binding_after is not None or self._closing
        for widget in self._setup_controls:
            widget.configure(state="disabled" if busy else "normal")
        if busy:
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="normal")
            return

        live_ready = (
            self.backend is not None
            and self.target is not None
            and self.target.is_roblox
            and self.confirm_var.get()
            and self._readiness_ok
            and not self.runner.cleanup_failed
        )
        can_start = self._workflow is not None and (
            self.mode_var.get() == "dry" or live_ready
        )
        self.start_button.configure(state="normal" if can_start else "disabled")
        self.stop_button.configure(state="disabled")

    def _refresh_readiness(self) -> bool:
        if self.backend is None:
            self._readiness_ok = False
            self.readiness_var.set("Live input unavailable. Dry run still works.")
            self._refresh_controls()
            return False
        try:
            problems = self.backend.readiness()
        except Exception:
            self._readiness_ok = False
            self.readiness_var.set("Could not check native readiness. Live input remains unavailable.")
            self._refresh_controls()
            return False
        if problems:
            self._readiness_ok = False
            self.readiness_var.set("Live input not ready: " + "; ".join(problems))
            self._refresh_controls()
            return False
        self._readiness_ok = True
        self.readiness_var.set("Native readiness checks passed. No input has been sent.")
        self._refresh_controls()
        return True

    def _begin_binding(self) -> None:
        if self._run_locked or self._binding_after is not None:
            return
        if self.backend is None:
            self.status_var.set("Live input unavailable. Dry run still works.")
            return
        self._cancel_binding(silent=True)
        self.target = None
        self.confirm_var.set(False)
        self.target_var.set("Binding starts now: manually focus Roblox within 3 seconds.")
        self.status_var.set("Binding countdown active. No input will be sent.")
        self._binding_after = self.root.after(int(COUNTDOWN_SECONDS * 1000), self._finish_binding)
        self._refresh_controls()

    def _finish_binding(self) -> None:
        self._binding_after = None
        assert self.backend is not None
        try:
            target = self.backend.foreground()
        except Exception as exc:
            self.target = None
            message = self._native_error_message(exc, "Could not read foreground Roblox target")
            self.target_var.set(f"{message}. No target bound.")
            self.status_var.set(f"Binding failed. {message}.")
            self._refresh_controls()
            return
        if target is None or not target.is_roblox:
            self.target = None
            self.target_var.set("Foreground app is not Roblox. No target bound.")
            self.status_var.set("Binding failed. Focus Roblox, then bind again.")
            self._refresh_controls()
            return
        self.target = target
        self.target_var.set(
            f"Bound Roblox — PID {target.pid}; executable {target.executable}; identifier {target.identifier}."
        )
        self.status_var.set("Roblox target bound. Complete the manual check before live start.")
        self._refresh_controls()

    def _cancel_binding(self, *, silent: bool = False) -> bool:
        if self._binding_after is None:
            return False
        try:
            self.root.after_cancel(self._binding_after)
        except tk.TclError:
            pass
        self._binding_after = None
        if not silent:
            self.target_var.set("Binding cancelled. No Roblox target bound.")
            self.status_var.set("Binding cancelled. No input was sent.")
        self._refresh_controls()
        return True

    @staticmethod
    def _native_error_message(exc: Exception, fallback: str) -> str:
        """Keep an actionable native error, never a traceback or multi-line dump."""
        detail = " ".join(str(exc).split())
        if not detail:
            return fallback
        return f"{fallback}: {detail[:240]}"

    def _start(self) -> None:
        if self._run_locked or self._binding_after is not None:
            if self._binding_after is not None:
                self.status_var.set("Wait for binding to finish or press Stop to cancel it.")
            return
        dry_run = self.mode_var.get() == "dry"
        armed = self.confirm_var.get()
        if not dry_run:
            # Acknowledgement applies to one deliberate start attempt, including a bad template.
            self.confirm_var.set(False)
        try:
            if not self._validate():
                self.status_var.set("Fix the template before starting.")
                return
            assert self._workflow is not None
            if not dry_run:
                if self.backend is None:
                    raise RuntimeError("Live input unavailable. Dry run still works.")
                if self.target is None or not self.target.is_roblox:
                    raise ValueError("Bind a foreground Roblox player before live execution.")
                if not armed:
                    raise ValueError("Complete the manual gameplay check before each live run.")
                if not self._refresh_readiness():
                    raise RuntimeError("Native readiness must pass before live execution.")
                if self.runner.cleanup_failed:
                    raise RuntimeError("Input cleanup failed. Restart before another live run.")
            self.runner.start(self._workflow, target=self.target, dry_run=dry_run, armed=armed)
        except (RuntimeError, ValueError) as exc:
            self.status_var.set(str(exc))
            self._append_log("error", str(exc))
            return
        self._terminal_received = False
        self._set_run_locked(True)
        self.status_var.set("Starting. Stop remains available.")
        self._append_log("starting", "Worker started.")
        self._schedule_poll()

    def _stop(self) -> None:
        cancelled_binding = self._cancel_binding()
        if self.runner.running:
            self.runner.stop()
            self.status_var.set("Stopping. Releasing held inputs before controls unlock.")
            self._append_log("stopping", "Cancellation requested.")
        elif not cancelled_binding:
            self.status_var.set("Nothing is running.")

    def _on_escape(self, _event: tk.Event[tk.Misc] | None = None) -> str | None:
        if self._binding_after is not None or self.runner.running:
            self._stop()
            return "break"
        return None

    def _on_quit_key(self, _event: tk.Event[tk.Misc] | None = None) -> str:
        self._on_close()
        return "break"

    def _set_run_locked(self, locked: bool) -> None:
        self._run_locked = locked
        self._refresh_controls()

    def _schedule_poll(self) -> None:
        if self._poll_after is None:
            self._poll_after = self.root.after(_POLL_MS, self._poll_runner)

    def _poll_runner(self) -> None:
        self._poll_after = None
        self._drain_events()
        if self._run_locked:
            if not self.runner.running and self._terminal_received:
                self._set_run_locked(False)
            else:
                self._schedule_poll()

    def _drain_events(self) -> None:
        while True:
            try:
                status = self.runner.events.get_nowait()
            except queue.Empty:
                return
            self._handle_status(status)

    def _handle_status(self, status: Status) -> None:
        self.status_var.set(f"{status.state}: {status.message}")
        self._append_log(status.state, status.message)
        if status.state in {"completed", "stopped", "error"}:
            self._terminal_received = True
            self._refresh_controls()

    def _append_log(self, state: str, message: str) -> None:
        self._log_lines.append(f"{state}: {message}")
        self._log_lines = self._log_lines[-_MAX_LOG_LINES:]
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", "\n".join(self._log_lines))
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_close(self) -> None:
        self._cancel_binding(silent=True)
        if self.runner.running:
            self._closing = True
            self.runner.stop()
            self.status_var.set("Stopping before close. Waiting for input cleanup.")
            self._schedule_close_wait()
            return
        self._drain_events()
        if self.runner.cleanup_failed and not self._close_error_acknowledged:
            self._close_error_acknowledged = True
            messagebox.showerror(
                "Input cleanup failed",
                "Held input cleanup failed. Check input state manually, then close again.",
                parent=self.root,
            )
            return
        self._destroy()

    def _schedule_close_wait(self) -> None:
        self.root.after(_POLL_MS, self._wait_for_close)

    def _wait_for_close(self) -> None:
        self._drain_events()
        if self.runner.running:
            self._schedule_close_wait()
            return
        if self.runner.cleanup_failed and not self._close_error_acknowledged:
            self._close_error_acknowledged = True
            messagebox.showerror(
                "Input cleanup failed",
                "Held input cleanup failed. Check input state manually, then close again.",
                parent=self.root,
            )
            self._closing = False
            self._refresh_controls()
            return
        self._destroy()

    def _destroy(self) -> None:
        if self._binding_after is not None:
            self._cancel_binding(silent=True)
        if self._validation_after is not None:
            try:
                self.root.after_cancel(self._validation_after)
            except tk.TclError:
                pass
            self._validation_after = None
        if self._poll_after is not None:
            try:
                self.root.after_cancel(self._poll_after)
            except tk.TclError:
                pass
            self._poll_after = None
        self.root.destroy()


def main() -> None:
    """Open the supervised local UI."""
    from .tk_runtime import configure_tk

    configure_tk()
    root = tk.Tk()
    app = App(root)
    try:
        root.mainloop()
    finally:
        app.runner.stop()
        app.runner.join()
        if app.runner.cleanup_failed:
            print("Input cleanup failed. Check held inputs manually before restarting.", file=sys.stderr)
        try:
            root.destroy()
        except tk.TclError:
            pass
