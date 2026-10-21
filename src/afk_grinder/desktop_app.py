"""Trusted local WebView shell. All input remains in the guarded Python engine."""

from __future__ import annotations

from pathlib import Path
import json
import sys
import threading
import time
import os
from typing import Any

from .build_info import build_info
from .capture import capture_error_type
from .desktop_controller import DesktopController

_mac_delegate_class: Any = None
_PUBLIC_BRIDGE_METHODS = frozenset({"get_state", "get_preview", "command"})


def allowed_document(url: Any, expected: str) -> bool:
    """Accept only the exact bundled entry point, without query or fragment."""
    return isinstance(url, str) and url == expected


def _document_failure(url: Any, expected: str) -> str:
    """Classify a rejected entry point without logging native file locations."""
    if url is None or url == "about:blank":
        return "blank_document"
    if not isinstance(url, str):
        return "unexpected_url_type"
    if url.casefold() == expected.casefold():
        return "url_case_mismatch"
    return "different_document"


def _smoke_resize(window: Any, width: int, height: int) -> float:
    """Fit the smoke window to its host display and report actual geometry."""
    screen_width = window.evaluate_js("window.screen.availWidth")
    if type(screen_width) not in (int, float) or not 620 <= screen_width <= 32768:
        raise RuntimeError("Native interface screen bounds are unavailable.")
    target_width = min(width, int(screen_width))
    window.resize(target_width, height)
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        actual_width = window.evaluate_js("window.innerWidth")
        if type(actual_width) in (int, float) and abs(actual_width - target_width) <= 40:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("Native interface resize failed.")
    if sys.stdout is not None:
        print(f"Launcher smoke viewport: requested={width} available={int(screen_width)} "
              f"target={target_width} actual={actual_width}.", flush=True)
    return actual_width


def _smoke_popup_models() -> None:
    """Exercise bundled OCR in private builds using synthetic pixels only."""
    from .recognition.ocr_models import model_directory, validate_models
    models = model_directory()
    if not models.exists():
        return
    from PIL import Image, ImageDraw, ImageFont
    from .recognition.service import RecognitionService
    service = RecognitionService(validate_models(models), {"bank": r"bank"})
    try:
        service.start()
        deadline = time.monotonic() + 10
        while not service.ready:
            if service.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Private OCR worker did not warm.")
            time.sleep(.02)
        image = Image.new("RGB", (800, 400), "white")
        ImageDraw.Draw(image).text((60, 70), "BANK", fill="black", font=ImageFont.load_default(size=64))
        service.submit(800, 400, image.tobytes("raw", "BGR"))
        deadline = time.monotonic() + 3
        result = None
        while result is None and time.monotonic() < deadline:
            result = service.poll()
            time.sleep(.02)
        if result is None or result.error or tuple(hit.label_id for hit in result.hits) != ("bank",):
            raise RuntimeError("Private synthetic OCR label check failed.")
        if sys.stdout is not None:
            print("Private popup OCR worker passed with synthetic pixels. No OS input or capture used.", flush=True)
    finally:
        service.close()


def _smoke_pack_worker(*, missing_sdk: bool) -> None:
    """Check the real spawned pack worker with original in-memory pixels."""
    if missing_sdk:
        return
    from hashlib import sha256
    from io import BytesIO
    from PIL import Image
    from .recognition.pack_service import PackRecognitionService
    from .recognition.packs import Anchor, Asset, Provenance, ResourcePack, Setup, State
    texture = Image.frombytes("RGB", (16, 16), bytes((index * 37 + index // 17 * 13) % 256
                                                   for index in range(16 * 16 * 3)))
    encoded = BytesIO()
    texture.save(encoded, format="PNG")
    data = encoded.getvalue()
    pack = ResourcePack(
        "example.worker-smoke", "0.1.0", "0.2.0",
        Provenance("https://github.com/hypler-dev/afk-grinder", "0" * 40, "MIT", "Original synthetic texture."),
        (96, 64), Setup("en", "Synthetic worker check only.", (96, 64)),
        (Asset("texture", "assets/texture.png", sha256(data).hexdigest(), data),),
        (Anchor("texture", "texture", (0, 0, 96, 64), .97, (1., 1.)),),
        (State("synthetic", ("texture",), (), 2, "gameplay"),),
    )
    image = Image.new("RGB", (96, 64), (3, 7, 11))
    image.paste(texture, (11, 9))
    service = PackRecognitionService(pack, (96, 64))
    try:
        service.start()
        deadline = time.monotonic() + 15
        while not service.ready:
            if service.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("Synthetic pack worker did not warm.")
            time.sleep(.02)
        service.submit(96, 64, image.tobytes("raw", "BGR"), timeout=2)
        deadline = time.monotonic() + 3
        result = None
        while result is None and time.monotonic() < deadline:
            result = service.poll()
            time.sleep(.01)
        if (result is None or result.error or result.variant_count != 1 or len(result.hits) != 1
                or result.hits[0].id != "texture" or result.hits[0].box != (11, 9, 16, 16)
                or result.hits[0].score is None or result.hits[0].score < .97):
            raise RuntimeError("Synthetic pack worker result failed.")
        if sys.stdout is not None:
            print("Pack template worker passed with synthetic pixels. No OS input or capture used.", flush=True)
    finally:
        service.close()


def restricted_dispatch(original: Any) -> Any:
    """Prevent pinned pywebview's dotted getattr resolver exposing internals.

    Its API-generation filter alone is not an access-control boundary. The
    internal callback is required only for Python's evaluate_js completion.
    No DOM/file/state handlers are registered by this application.
    """
    def dispatch(window: Any, name: Any, params: Any, value_id: Any) -> None:
        if isinstance(name, str) and (name in _PUBLIC_BRIDGE_METHODS or name == "pywebviewAsyncCallback"):
            original(window, name, params, value_id)
    return dispatch


def _webview_thread(*args: Any, **kwargs: Any) -> threading.Thread:
    """Keep WebView response delivery from retaining a closed application."""
    kwargs["daemon"] = True
    return threading.Thread(*args, **kwargs)


def _restrict_bridge() -> None:
    from webview import util
    # Pinned pywebview 6.2.1 uses non-daemon utility threads for API replies
    # and bridge injection. Cocoa reply delivery can wait indefinitely once
    # its UI loop closes. Only these WebView utilities become daemon threads;
    # the input runner stays non-daemon and controller.close still awaits it.
    util.Thread = _webview_thread
    guarded = restricted_dispatch(util.js_bridge_call)
    util.js_bridge_call = guarded
    # Platform modules normally import after this hook. Rebind cached adapters
    # too, so an earlier import cannot retain the unrestricted function.
    for name in ("cocoa", "winforms", "edgechromium"):
        module = sys.modules.get(f"webview.platforms.{name}")
        if module is not None and hasattr(module, "js_bridge_call"):
            module.js_bridge_call = guarded


class DesktopAPI:
    """Expose exactly three methods to pywebview's recursive API discovery."""

    def __init__(self, controller: DesktopController) -> None:
        self._controller = controller
        self._allowed = threading.Event()
        self._observed = threading.Event()

    def get_state(self) -> dict[str, Any]:
        if not self._allowed.is_set():
            raise RuntimeError("The trusted local interface is not ready.")
        self._observed.set()
        return self._controller.get_state()

    def get_preview(self, preview_id: int) -> Any:
        if not self._allowed.is_set():
            raise RuntimeError("The trusted local interface is not ready.")
        return self._controller.get_preview(preview_id)

    def command(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        if name != "stop" and not self._allowed.is_set():
            raise RuntimeError("The trusted local interface is not ready.")
        return self._controller.command(name, payload)


def _install_navigation_guard(window: Any, expected: str, rejected: Any) -> Any:
    """Install native navigation cancellation before the entry point loads.

    The adapters target pinned pywebview 6.2.1. CSP separately restricts page
    subresources. A guard failure closes the shell before exposing its API.
    """
    global _mac_delegate_class
    if sys.platform == "darwin":
        from webview.platforms.cocoa import BrowserView
        native = BrowserView.instances[window.uid].webview
        original = native.navigationDelegate()
        if _mac_delegate_class is None:
            # Subclassing preserves WebKit callback metadata and pywebview's
            # load-completion bridge injection, without forwarding selectors.
            class AFKLocalNavigationDelegate(type(original)):
                def webView_decidePolicyForNavigationAction_decisionHandler_(self, view, action, handler):
                    url = str(action.request().URL().absoluteString())
                    if allowed_document(url, self._afk_expected):
                        handler(1)  # WKNavigationActionPolicyAllow
                    else:
                        handler(0)  # WKNavigationActionPolicyCancel
                        self._afk_rejected(url)

            _mac_delegate_class = AFKLocalNavigationDelegate
        delegate = _mac_delegate_class.alloc().init()
        delegate._afk_expected = expected
        delegate._afk_rejected = rejected
        native.setNavigationDelegate_(delegate)
        return delegate
    if sys.platform == "win32":
        native = window.native.webview
        def on_navigation(_sender: Any, event: Any) -> None:
            if not allowed_document(str(event.Uri), expected):
                event.Cancel = True
                rejected(str(event.Uri))

        native.NavigationStarting += on_navigation
        return on_navigation
    raise RuntimeError("The native launcher supports Windows and macOS only.")


def _schedule_interface_scale(window: Any, percent: int, closing: threading.Event) -> None:
    """Change native page zoom on its UI thread, without changing game state."""
    if type(percent) is not int or percent not in {100, 125, 150, 175, 200}:
        raise ValueError("Unsupported interface size.")

    def apply() -> None:
        if closing.is_set():
            return
        try:
            if sys.platform == "darwin":
                from webview.platforms.cocoa import BrowserView
                BrowserView.instances[window.uid].webview.setPageZoom_(percent / 100)
            elif sys.platform == "win32":
                window.native.webview.ZoomFactor = percent / 100
            else:
                raise RuntimeError("Unsupported native interface.")
        except Exception:
            if sys.stderr is not None:
                print("Interface size could not be changed.", file=sys.stderr)

    if closing.is_set():
        return
    try:
        if sys.platform == "darwin":
            from PyObjCTools import AppHelper
            AppHelper.callAfter(apply)
        elif sys.platform == "win32":
            from System import Action
            window.native.webview.BeginInvoke(Action(apply))
        else:
            raise RuntimeError("Unsupported native interface.")
    except Exception:
        if not closing.is_set() and sys.stderr is not None:
            print("Interface size could not be changed.", file=sys.stderr)


def _choose_pack_directory(window: Any) -> Path | None:
    """Read one human selection from the native picker; never accept a JS path."""
    from webview import FileDialog
    selected = None
    failed = False

    def choose() -> None:
        nonlocal selected, failed
        try:
            selected = window.create_file_dialog(FileDialog.FOLDER, allow_multiple=False)
        except Exception:
            failed = True

    # Bridge calls run on Python worker threads. The pinned WinForms folder
    # dialog does not marshal itself to the form's STA thread; Cocoa does.
    if sys.platform == "win32" and window.native.InvokeRequired:
        from System import Action
        window.native.Invoke(Action(choose))
    else:
        choose()
    if failed:
        raise ValueError("The native pack picker could not open.")
    if selected is None:
        return None
    if (type(selected) not in (tuple, list) or len(selected) != 1
            or type(selected[0]) is not str or not selected[0] or len(selected[0]) > 4096):
        raise ValueError("A single local pack folder is required.")
    directory = Path(selected[0])
    if not directory.is_absolute():
        raise ValueError("A local absolute folder is required.")
    return directory


def _smoke_picker_thread(window: Any) -> None:
    """Check real Windows STA dispatch without displaying a folder dialog."""
    if sys.platform != "win32":
        return
    from types import SimpleNamespace
    from System.Threading import ApartmentState, Thread
    observed = []

    def inspect_thread(*_args: Any, **_kwargs: Any) -> None:
        if window.native.InvokeRequired or Thread.CurrentThread.GetApartmentState() != ApartmentState.STA:
            raise RuntimeError("Pack picker did not reach its native UI thread.")
        observed.append(True)

    _choose_pack_directory(SimpleNamespace(native=window.native, create_file_dialog=inspect_thread))
    if observed != [True]:
        raise RuntimeError("Pack picker UI-thread check did not run.")


def open_desktop(*, smoke: bool = False) -> None:
    """Run the native launcher, or a no-input bridge/navigation smoke check."""
    if sys.platform not in {"darwin", "win32"}:
        raise RuntimeError("The native launcher supports Windows and macOS only.")
    import webview
    _restrict_bridge()

    if smoke:
        backend = None
    else:
        from .backends import create_backend
        try:
            backend = create_backend()
        except Exception:
            backend = None
    metadata = build_info()
    replay_service = None
    if not smoke:
        from .replay_service import ReplayService
        if sys.platform == "darwin":
            replay_root = Path.home() / "Library" / "Application Support" / "AFKGrinder" / "replay"
        else:
            local = os.environ.get("LOCALAPPDATA")
            if not local or not Path(local).is_absolute():
                raise RuntimeError("Windows local application storage is unavailable.")
            replay_root = Path(local) / "AFKGrinder" / "replay"
        replay_service = ReplayService(replay_root)
    controller = DesktopController(backend=backend, buildmetadata=metadata,
                                   replay_service=replay_service)
    api = DesktopAPI(controller)
    entry = Path(__file__).with_name("web") / "index.html"
    if not entry.is_file():
        controller.close()
        raise RuntimeError("Bundled launcher files are missing.")
    url = entry.resolve().as_uri()
    webview.settings.update({"ALLOW_FILE_URLS": False, "ALLOW_DOWNLOADS": False,
                             "OPEN_EXTERNAL_LINKS_IN_BROWSER": False,
                             "REMOTE_DEBUGGING_PORT": None, "IGNORE_SSL_ERRORS": False})
    identity = metadata["commit"][:7]
    if metadata["commit"].endswith("-dirty"):
        identity += "-dirty"
    window = webview.create_window(f"AFK Grinder {metadata['version']} · {identity}", url=url,
                                   js_api=api, width=1180, height=800, min_size=(620, 450),
                                   background_color="#090d19", text_select=True, zoomable=True)
    if not smoke:
        controller._pack_picker = lambda: _choose_pack_directory(window)
    guard: list[Any] = []
    failed = threading.Event()
    rejected = threading.Event()
    closed = threading.Event()
    closing_requested = threading.Event()
    lifecycle_lock = threading.Lock()
    close_worker_started = threading.Event()

    def request_close() -> None:
        with lifecycle_lock:
            closing_requested.set()
            api._allowed.clear()
        window.destroy()

    def fail(stage: str, error: Exception | None = None) -> None:
        first = not failed.is_set()
        failed.set()
        if first and smoke and sys.stderr is not None:
            kind = capture_error_type(error) if error is not None else "none"
            print(f"Launcher smoke failure: {stage} ({kind}).", file=sys.stderr, flush=True)

    def reject_navigation(rejected_url: str) -> None:
        api._allowed.clear()
        controller.command("stop", {})
        rejected.set()
        if smoke and sys.stderr is not None:
            print(f"Launcher smoke navigation rejected: {_document_failure(rejected_url, url)}.",
                  file=sys.stderr, flush=True)

    def before_show() -> None:
        try:
            guard.append(_install_navigation_guard(window, url, reject_navigation))
        except Exception as error:
            fail("navigation_guard", error)
            controller.close()
            # Public destroy waits for the shown event, which has not fired
            # during before_show. Close on a worker once startup can proceed.
            threading.Thread(target=request_close, daemon=True).start()

    def before_load() -> None:
        api._allowed.clear()

    def loaded() -> None:
        if closing_requested.is_set():
            return
        try:
            # Edge's cached Source can describe an initialization or canceled
            # navigation. Verify the document that is actually executing.
            current_url = window.evaluate_js("window.location.href")
            with lifecycle_lock:
                if closing_requested.is_set():
                    return
                trusted = guard and allowed_document(current_url, url) and not failed.is_set()
                if trusted:
                    api._allowed.set()
            if not trusted:
                reason = _document_failure(current_url, url) if guard else "missing_guard"
                fail(reason + ("_after_bridge" if api._observed.is_set() else "_startup"))
                request_close()
        except Exception as error:
            if not closing_requested.is_set():
                fail("loaded_callback", error)
                request_close()

    def finish_close() -> None:
        while not closed.is_set():
            if controller.close():
                request_close()
                return
            time.sleep(0.02)

    def closing() -> bool:
        with lifecycle_lock:
            closing_requested.set()
            api._allowed.clear()
        if controller.close():
            return True
        if not close_worker_started.is_set():
            close_worker_started.set()
            threading.Thread(target=finish_close, daemon=True, name="launcher-close").start()
        return False

    window.events.before_show += before_show
    window.events.before_load += before_load
    window.events.loaded += loaded
    window.events.closing += closing
    window.events.closed += closed.set

    from webview.menu import Menu, MenuAction
    menus = [Menu("Interface", [
        MenuAction(f"{percent}%" + (" (Actual size)" if percent == 100 else ""),
                   lambda percent=percent: _schedule_interface_scale(window, percent, closing_requested))
        for percent in (100, 125, 150, 175, 200)
    ])]

    def smoke_check() -> None:
        from .capture.service import BackgroundJob
        job = None
        deadline = time.monotonic() + 18
        result = None
        stage = "bridge_startup"
        try:
            while time.monotonic() < deadline and not closed.is_set() and not failed.is_set():
                if api._observed.is_set():
                    if window.evaluate_js("document.documentElement.dataset.bridgeReady === 'true'"):
                        break
                time.sleep(0.05)
            else:
                raise RuntimeError("Launcher bridge startup timed out.")
            stage = "picker_thread"
            _smoke_picker_thread(window)
            stage = "sdk_service"
            # Keep native WebView startup separate from the SDK's own hard
            # 15-second process deadline, especially on cold Intel runners.
            job = BackgroundJob("sdk", timeout=min(15.0, max(0.1, deadline - time.monotonic())))
            while result is None and not closed.is_set() and not failed.is_set():
                result = job.poll()
                time.sleep(0.05)
            if result is None:
                raise RuntimeError("Launcher closed during the SDK service check.")
            missing_sdk = result.error == "Recognition is optional. Install the locked recognition extra first."
            if not missing_sdk and (result.error or result.report is None):
                raise RuntimeError("Spawned recognition service failed.")
            stage = "pack_worker"
            _smoke_pack_worker(missing_sdk=missing_sdk)
            stage = "private_popup_models"
            _smoke_popup_models()
            stage = "popup_diagnostic"
            from .capture import CaptureDiagnostic
            from .recognition.popup_diagnostic import PopupDiagnostic
            with controller._lock:
                controller._popup_phase, controller._popup_state = "result", "error"
                controller._popup_message = "Popup check stopped. Check capture, content area and local recognition setup."
                controller._popup_diagnostic = PopupDiagnostic(
                    "capture_freshness", "stale",
                    CaptureDiagnostic("stale", "worker_exit_freshness", "capture_error"))
            diagnostic_deadline = time.monotonic() + 2
            while time.monotonic() < diagnostic_deadline:
                if window.evaluate_js("document.getElementById('popup-diagnostic').textContent === "
                                      "'Diagnostic: capture_freshness / stale. Capture: stale at worker_exit_freshness (capture_error).'"):
                    break
                time.sleep(.05)
            else:
                raise RuntimeError("Synthetic popup diagnostic did not cross the desktop bridge.")
            stage = "ui_state"
            if not window.evaluate_js("getComputedStyle(document.getElementById('cleanup-banner')).display === 'none'"):
                raise RuntimeError("Inactive cleanup warning is visible.")
            for width, height, levels in ((640, 450, (200, 100)), (960, 700, (100,)), (1180, 800, (100,))):
                stage = f"interface_resize_{width}"
                original_width = _smoke_resize(window, width, height)
                for percent in levels:
                    stage = f"interface_scale_{width}_{percent}"
                    _schedule_interface_scale(window, percent, closing_requested)
                    scale_deadline = time.monotonic() + 2
                    while time.monotonic() < scale_deadline:
                        layout = window.evaluate_js("""(() => {
                            const stop = document.querySelector('.topbar [data-command="stop"]');
                            const rect = stop.getBoundingClientRect();
                            return {width: innerWidth, fit: document.documentElement.scrollWidth <= innerWidth + 1,
                                stop: rect.width > 0 && rect.left >= 0 && rect.right <= innerWidth + 1 &&
                                      rect.top >= 0 && rect.bottom <= innerHeight + 1};
                        })()""")
                        if (isinstance(layout, dict) and layout.get("fit") and layout.get("stop")
                                and abs(layout.get("width", 0) * percent / 100 - original_width) <= 3):
                            break
                        time.sleep(0.05)
                    else:
                        raise RuntimeError("Native interface scaling or Stop layout failed.")
                    for route in ("library", "session", "replay", "setup", "routines", "packs", "settings"):
                        stage = f"interface_scale_{width}_{percent}_{route}"
                        selector = json.dumps(f'[data-route="{route}"]')
                        fits = window.evaluate_js("""(() => {
                            document.querySelector(""" + selector + """).click();
                            const stop = document.querySelector('.topbar [data-command="stop"]').getBoundingClientRect();
                            return document.documentElement.scrollWidth <= innerWidth + 1 &&
                                stop.width > 0 && stop.left >= 0 && stop.right <= innerWidth + 1 &&
                                stop.top >= 0 && stop.bottom <= innerHeight + 1;
                        })()""")
                        if fits is not True:
                            raise RuntimeError("Native launcher section overflowed at interface scale.")
                        if route == "session" and window.evaluate_js("""(() => {
                            const row = document.getElementById('popup-diagnostic');
                            const rect = row.getBoundingClientRect();
                            return !row.hidden && rect.width > 0 && rect.left >= 0 &&
                                rect.right <= innerWidth + 1 && row.scrollWidth <= row.clientWidth + 1 &&
                                !row.hasAttribute('aria-live') && !row.hasAttribute('role') &&
                                !row.hasAttribute('tabindex');
                        })()""") is not True:
                            raise RuntimeError("Native popup diagnostic overflowed or became an active status surface.")
                        if route == "setup" and window.evaluate_js("""(() => {
                            const panel = document.getElementById('pack-panel').getBoundingClientRect();
                            return panel.width > 0 && panel.left >= 0 && panel.right <= innerWidth + 1 &&
                                ['pack-choose', 'pack-check', 'pack-clear'].every(id => {
                                    const rect = document.getElementById(id).getBoundingClientRect();
                                    return rect.height >= 40 && rect.width >= 40 && rect.left >= 0 &&
                                        rect.right <= innerWidth + 1;
                                });
                        })()""") is not True:
                            raise RuntimeError("Native pack inspector controls overflowed at interface scale.")
                        if sys.stdout is not None:
                            print(f"Launcher smoke route: {route} viewport={width} zoom={percent}% "
                                  "fit=true stop=true.", flush=True)
            stage = "blocked_navigation"
            rejected.clear()
            blocked_url = entry.with_name("styles.css").resolve().as_uri()
            window.run_js("window.location.href = " + json.dumps(blocked_url) + ";")
            if not rejected.wait(2) or not allowed_document(window.evaluate_js("window.location.href"), url):
                raise RuntimeError("Native navigation guard failed.")
        except Exception as error:
            fail(stage, error)
        finally:
            if job is not None:
                job.cancel()
            controller.close()
            request_close()

    try:
        webview.start(smoke_check if smoke else None,
                      gui="cocoa" if sys.platform == "darwin" else "edgechromium",
                      debug=False, http_server=False, private_mode=True, menu=menus)
    finally:
        controller.close()
    if failed.is_set() or (smoke and not rejected.is_set()):
        raise RuntimeError("Native launcher startup or bridge check failed. WebView2 is required on Windows.")
    if smoke and sys.stdout is not None:
        print("Local launcher, bridge, navigation guard and spawned SDK service passed. No OS input or capture used.")
