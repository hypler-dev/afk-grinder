"""Cancelable, bounded input execution. No OS calls occur in dry-run mode."""

from dataclasses import dataclass
import queue
import threading
import time
import math
from typing import Callable

from .models import Backend, Step, Target, Workflow
from .templates import COUNTDOWN_SECONDS, validate_workflow

POLL_SECONDS = 0.02


@dataclass(frozen=True)
class Status:
    state: str
    message: str


class _Stopped(Exception):
    pass


class GuardedInput:
    """Internal routine capability; the web bridge never receives this object."""

    def __init__(self, runner: "Runner", target: Target):
        self._runner, self._target = runner, target

    def guard(self) -> None:
        if threading.current_thread() is not self._runner._thread:
            raise RuntimeError("Routine capability is no longer active.")
        self._runner._guard(self._target, False, focus=True)

    def wait(self, seconds: float) -> None:
        self.guard()
        self._runner._wait(seconds, self._target, False)

    def click(self, point: tuple[float, float], authorize: Callable[[], None]) -> None:
        if (type(point) is not tuple or len(point) != 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in point)):
            raise ValueError("Positioned click requires finite native coordinates.")
        with self._runner._lock:
            self.guard()
            authorize()
            self.guard()
            self._runner._held_buttons.add("left")
            self._runner.backend.mouse_down_at("left", *point)
            self._runner.backend.mouse_up("left")
            self._runner._held_buttons.remove("left")


class Runner:
    """One non-daemon worker; UI reads events and never touches native input."""

    def __init__(self, backend: Backend | None):
        self.backend = backend
        self.events: queue.Queue[Status] = queue.Queue()
        self._cancel = threading.Event()
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._held_keys: set[str] = set()
        self._held_buttons: set[str] = set()
        self.cleanup_failed = False
        self._deadline = 0.0
        self._start_cancel: threading.Event | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, workflow: Workflow, *, target: Target | None = None,
              dry_run: bool = True, armed: bool = False,
              cancel_event: threading.Event | None = None,
              _routine: Callable[[GuardedInput], None] | None = None) -> None:
        validate_workflow(workflow)
        with self._lock:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Start was canceled.")
            if self.running:
                raise RuntimeError("A run is already active.")
            if not dry_run:
                if self.cleanup_failed:
                    raise RuntimeError("Input cleanup failed. Check held inputs and restart before live use.")
                if not armed:
                    raise ValueError("Confirm manual login and visible gameplay before each live run.")
                if self.backend is None or target is None or not target.is_roblox:
                    raise ValueError("Bind a foreground Roblox player before live execution.")
                problems = self.backend.readiness()
                if problems:
                    raise RuntimeError("; ".join(problems))
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("Start was canceled.")
            self._start_cancel = cancel_event
            self._cancel.clear()
            self._thread = threading.Thread(target=self._run,
                                            args=(workflow, target, dry_run, _routine),
                                            name="input-runner", daemon=False)
            self._thread.start()

    def start_routine(self, routine: Callable[[GuardedInput], None], *, target: Target,
                      armed: bool, cancel_event: threading.Event) -> None:
        if not callable(routine):
            raise ValueError("A trusted application routine is required.")
        self.start(Workflow("Approved popup recovery", (Step("wait", 1),)), target=target,
                   dry_run=False, armed=armed, cancel_event=cancel_event, _routine=routine)

    def stop(self) -> None:
        # Serialize cancellation with acquisition so no new press starts after stop returns.
        with self._lock:
            self._cancel.set()

    def join(self, timeout: float | None = None) -> None:
        thread = self._thread
        if thread:
            thread.join(timeout)

    def _guard(self, target: Target | None, dry_run: bool, *, focus: bool) -> None:
        if self._cancel.is_set() or (self._start_cancel is not None and self._start_cancel.is_set()):
            raise _Stopped("Stopped by user.")
        if time.monotonic() >= self._deadline:
            raise _Stopped("Run time limit reached.")
        if not dry_run:
            assert self.backend is not None
            if self.backend.escape_pressed():
                raise _Stopped("Emergency stop: Escape pressed.")
            problems = self.backend.readiness()
            if problems:
                raise RuntimeError("; ".join(problems))
            if focus and self.backend.foreground() != target:
                raise _Stopped("Focus lost. Run stopped; focus will not be restored automatically.")

    def _wait(self, seconds: float, target: Target | None, dry_run: bool,
              *, focus: bool = True) -> None:
        deadline = time.monotonic() + seconds
        while True:
            self._guard(target, dry_run, focus=focus)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            self._cancel.wait(min(POLL_SECONDS, remaining))

    def _release_all(self) -> list[str]:
        failures = []
        assert self.backend is not None or not (self._held_keys or self._held_buttons)
        for key in sorted(self._held_keys):
            try:
                self.backend.key_up(key)
                self._held_keys.remove(key)
            except Exception:
                failures.append(f"Could not release key {key}.")
        for button in sorted(self._held_buttons):
            try:
                self.backend.mouse_up(button)
                self._held_buttons.remove(button)
            except Exception:
                failures.append(f"Could not release {button} mouse button.")
        return failures

    def _run(self, workflow: Workflow, target: Target | None, dry_run: bool,
             routine: Callable[[GuardedInput], None] | None = None) -> None:
        self._deadline = time.monotonic() + 30.0
        outcome = Status("completed", "Dry run complete; no OS input sent." if dry_run
                         else "Run complete. Held inputs released.")
        try:
            for second in (3, 2, 1):
                self.events.put(Status("countdown", f"Starting in {second}s. " + (
                    "Dry run: no input will be sent." if dry_run else "Focus the bound Roblox window. Escape stops.")))
                self._wait(COUNTDOWN_SECONDS / 3, target, dry_run, focus=False)
            self._guard(target, dry_run, focus=True)
            if routine is not None:
                assert target is not None and not dry_run
                self.events.put(Status("running", "Checking approved popup response."))
                routine(GuardedInput(self, target))
                return
            for index, step in enumerate(workflow.steps, 1):
                self._guard(target, dry_run, focus=True)
                self.events.put(Status("running", f"Step {index}/{len(workflow.steps)}: {step.action}"))
                if dry_run or step.action == "wait":
                    self._wait(step.duration_ms / 1000, target, dry_run)
                    continue
                assert self.backend is not None
                with self._lock:
                    self._guard(target, dry_run, focus=True)
                    if step.action == "hold_key":
                        # Track before the call: an adapter can fail after posting input.
                        self._held_keys.add(step.key)
                        self.backend.key_down(step.key)
                    else:
                        self._held_buttons.add(step.button)
                        self.backend.mouse_down(step.button)
                self._wait(step.duration_ms / 1000, target, dry_run)
                if step.action == "hold_key":
                    self.backend.key_up(step.key)
                    self._held_keys.remove(step.key)
                else:
                    self.backend.mouse_up(step.button)
                    self._held_buttons.remove(step.button)
        except _Stopped as exc:
            outcome = Status("stopped", str(exc))
        except Exception as exc:
            outcome = Status("error", f"Run failed: {exc}")
        finally:
            # A prior failed cleanup can leave tracked inputs. Dry run must never
            # retry those native releases; live execution is already blocked.
            failures = [] if dry_run else self._release_all()
            if failures:
                self.cleanup_failed = True
                outcome = Status("error", " ".join(failures) +
                                 " Check held inputs manually; restart before another live run.")
            self.events.put(outcome)
