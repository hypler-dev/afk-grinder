"""Trusted local WebView shell. All input remains in the guarded Python engine."""

from __future__ import annotations

from pathlib import Path
import json
import sys
import threading
import time
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


def _restrict_bridge() -> None:
    from webview import util
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
    controller = DesktopController(backend=backend, buildmetadata=metadata)
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
            stage = "ui_state"
            if not window.evaluate_js("getComputedStyle(document.getElementById('cleanup-banner')).display === 'none'"):
                raise RuntimeError("Inactive cleanup warning is visible.")
            for width, height, levels in ((640, 450, (200, 100)), (960, 700, (100,)), (1180, 800, (100,))):
                stage = f"interface_resize_{width}"
                window.resize(width, height)
                resize_deadline = time.monotonic() + 2
                while time.monotonic() < resize_deadline:
                    original_width = window.evaluate_js("window.innerWidth")
                    if isinstance(original_width, (int, float)) and abs(original_width - width) <= 40:
                        break
                    time.sleep(0.05)
                else:
                    raise RuntimeError("Native interface resize failed.")
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
                    for route in ("library", "session", "setup", "routines", "packs", "settings"):
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
