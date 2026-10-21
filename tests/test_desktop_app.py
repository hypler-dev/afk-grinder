"""Trusted-shell API boundaries with no WebView or native backend."""

import io
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from afk_grinder.desktop_app import (DesktopAPI, _document_failure, _schedule_interface_scale, _smoke_resize,
                                    _choose_pack_directory, allowed_document, open_desktop, restricted_dispatch)


class FakeController:
    def __init__(self):
        self.commands = []

    def get_state(self):
        return {"schema_version": 1}

    def get_preview(self, preview_id):
        return {"id": preview_id}

    def command(self, name, payload):
        self.commands.append((name, payload))
        return {"ok": True}


class ShellBoundaryTests(unittest.TestCase):
    def test_native_pack_picker_accepts_one_absolute_folder_and_cancel(self):
        window = Mock()
        folder = object()
        with patch.dict('sys.modules', {'webview': SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=folder))}), \
             patch('afk_grinder.desktop_app.sys.platform', 'darwin'):
            window.create_file_dialog.return_value = None
            self.assertIsNone(_choose_pack_directory(window))
            window.create_file_dialog.return_value = [str(Path.cwd())]
            self.assertEqual(_choose_pack_directory(window), Path.cwd())
            window.create_file_dialog.assert_called_with(folder, allow_multiple=False)
            for value in ([], ['relative'], ['one', 'two'], str(Path.cwd()), [True], ['x' * 4097]):
                window.create_file_dialog.return_value = value
                with self.subTest(value=value), self.assertRaises(ValueError):
                    _choose_pack_directory(window)

    def test_windows_picker_marshals_to_native_ui_thread(self):
        active = False
        calls = []
        def invoke(callback):
            nonlocal active
            active = True
            try:
                callback()
            finally:
                active = False
        def choose(*_args, **_kwargs):
            self.assertTrue(active)
            calls.append(True)
            return [str(Path.cwd())]
        window = SimpleNamespace(native=SimpleNamespace(InvokeRequired=True, Invoke=invoke),
                                 create_file_dialog=choose)
        with patch.dict('sys.modules', {
            'webview': SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=object())),
            'System': SimpleNamespace(Action=lambda callback: callback),
        }), patch('afk_grinder.desktop_app.sys.platform', 'win32'):
            self.assertEqual(_choose_pack_directory(window), Path.cwd())
        self.assertEqual(calls, [True])

    def test_windows_picker_contains_callback_errors_and_supports_ui_thread_call(self):
        window = Mock()
        window.native.InvokeRequired = False
        window.create_file_dialog.side_effect = RuntimeError('/private/sensitive-folder')
        with patch.dict('sys.modules', {
            'webview': SimpleNamespace(FileDialog=SimpleNamespace(FOLDER=object())),
        }), patch('afk_grinder.desktop_app.sys.platform', 'win32'):
            with self.assertRaisesRegex(ValueError, '^The native pack picker could not open.$'):
                _choose_pack_directory(window)
            window.native.Invoke.assert_not_called()
            window.create_file_dialog.side_effect = None
            window.create_file_dialog.return_value = None
            self.assertIsNone(_choose_pack_directory(window))

    def test_pending_real_webview_reply_cannot_hold_process_after_ui_close(self):
        script = '''
import threading
from types import SimpleNamespace
from afk_grinder.desktop_app import _restrict_bridge
from webview import util
waiting = threading.Event()
def disposed_ui_reply(_script):
    waiting.set()
    threading.Event().wait()
window = SimpleNamespace(_functions={}, _js_api=SimpleNamespace(get_state=lambda: {}),
                         evaluate_js=disposed_ui_reply)
_restrict_bridge()
util.js_bridge_call(window, 'get_state', [], 'reply')
assert waiting.wait(2), 'The real pinned dispatcher did not reach reply delivery.'
print('Pending WebView reply does not retain the process.', flush=True)
'''
        result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                                text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), 'Pending WebView reply does not retain the process.')

    def test_smoke_resize_caps_to_host_and_reports_actual_client_width(self):
        window = Mock()
        window.evaluate_js.side_effect = [1024, 1008]
        output = io.StringIO()
        with patch('afk_grinder.desktop_app.sys.stdout', output):
            self.assertEqual(_smoke_resize(window, 1180, 800), 1008)
        window.resize.assert_called_once_with(1024, 800)
        self.assertEqual(output.getvalue(),
                         'Launcher smoke viewport: requested=1180 available=1024 target=1024 actual=1008.\n')

    def test_smoke_resize_preserves_request_on_larger_display(self):
        window = Mock()
        window.evaluate_js.side_effect = [3840, 1180]
        with patch('afk_grinder.desktop_app.sys.stdout', None):
            self.assertEqual(_smoke_resize(window, 1180, 800), 1180)
        window.resize.assert_called_once_with(1180, 800)

    def test_smoke_resize_rejects_unknown_or_unsupported_display_before_resize(self):
        for value in (None, True, '1024', 619, 32769, float('nan'), float('inf')):
            with self.subTest(value=value):
                window = Mock()
                window.evaluate_js.return_value = value
                with self.assertRaisesRegex(RuntimeError, 'screen bounds are unavailable'):
                    _smoke_resize(window, 1180, 800)
                window.resize.assert_not_called()

    def test_smoke_resize_still_fails_when_window_does_not_reach_capped_width(self):
        window = Mock()
        window.evaluate_js.side_effect = [1024, 900]
        with patch('afk_grinder.desktop_app.time.monotonic', side_effect=[0, 0.1, 2.1]), \
             patch('afk_grinder.desktop_app.time.sleep'):
            with self.assertRaisesRegex(RuntimeError, 'resize failed'):
                _smoke_resize(window, 1180, 800)
        window.resize.assert_called_once_with(1024, 800)

    def test_interface_scale_validates_and_uses_native_ui_thread(self):
        window = SimpleNamespace(uid='test')
        native = Mock()
        callbacks = []
        closed = threading.Event()
        cocoa = SimpleNamespace(BrowserView=SimpleNamespace(instances={'test': SimpleNamespace(webview=native)}))
        app_helper = SimpleNamespace(callAfter=callbacks.append)
        with patch.dict('sys.modules', {'webview.platforms.cocoa': cocoa,
                                       'PyObjCTools': SimpleNamespace(AppHelper=app_helper)}), \
             patch('afk_grinder.desktop_app.sys.platform', 'darwin'):
            for value in (True, 0, 99, 201, 150.0, '150'):
                with self.assertRaises(ValueError):
                    _schedule_interface_scale(window, value, closed)
            _schedule_interface_scale(window, 200, closed)
            native.setPageZoom_.assert_not_called()
            callbacks.pop()()
            native.setPageZoom_.assert_called_once_with(2.0)
            _schedule_interface_scale(window, 125, closed)
            closed.set()
            callbacks.pop()()
            _schedule_interface_scale(window, 150, closed)
        native.setPageZoom_.assert_called_once()
        self.assertEqual(callbacks, [])

    def test_windows_interface_scale_is_deferred_and_cancelled_on_close(self):
        native = Mock()
        callbacks = []
        native.BeginInvoke.side_effect = callbacks.append
        window = SimpleNamespace(native=SimpleNamespace(webview=native))
        closed = threading.Event()
        with patch.dict('sys.modules', {'System': SimpleNamespace(Action=lambda action: action)}), \
             patch('afk_grinder.desktop_app.sys.platform', 'win32'):
            _schedule_interface_scale(window, 150, closed)
            self.assertNotIn('ZoomFactor', native.__dict__)
            callbacks.pop()()
            self.assertEqual(native.ZoomFactor, 1.5)
            _schedule_interface_scale(window, 200, closed)
            closed.set()
            callbacks.pop()()
            _schedule_interface_scale(window, 125, closed)
        self.assertEqual(native.ZoomFactor, 1.5)
        self.assertEqual(callbacks, [])

    def test_close_during_loaded_callback_does_not_fail_or_reopen_bridge(self):
        class Event:
            def __init__(self):
                self.handlers = []

            def __iadd__(self, handler):
                self.handlers.append(handler)
                return self

        events = SimpleNamespace(**{name: Event() for name in
                                    ("before_show", "before_load", "loaded", "closing", "closed")})
        evaluating, release = threading.Event(), threading.Event()
        window = Mock(events=events)
        controller = Mock()
        controller.close.return_value = True
        api_holder = []

        def create_window(*args, **kwargs):
            api_holder.append(kwargs['js_api'])
            return window

        def evaluate(*args):
            evaluating.set()
            self.assertTrue(release.wait(1))
            return None  # WebView disposal can finish an outstanding query.

        window.evaluate_js.side_effect = evaluate

        def start(*args, **kwargs):
            events.before_show.handlers[0]()
            loaded = threading.Thread(target=events.loaded.handlers[0])
            loaded.start()
            try:
                self.assertTrue(evaluating.wait(1))
                self.assertTrue(events.closing.handlers[0]())
            finally:
                release.set()
                loaded.join(timeout=1)
            self.assertFalse(loaded.is_alive())
            events.loaded.handlers[0]()  # Late duplicate callbacks are ignored.

        webview = SimpleNamespace(settings={}, create_window=create_window, start=start)
        menu = SimpleNamespace(Menu=lambda *args: args, MenuAction=lambda *args: args)
        with patch.dict('sys.modules', {'webview': webview, 'webview.menu': menu}), \
             patch('afk_grinder.desktop_app.sys.platform', 'darwin'), \
             patch('afk_grinder.desktop_app._restrict_bridge'), \
             patch('afk_grinder.desktop_app._install_navigation_guard', return_value=object()), \
             patch('afk_grinder.desktop_app.DesktopController', return_value=controller), \
             patch('afk_grinder.backends.create_backend', return_value=None):
            open_desktop()
        self.assertFalse(api_holder[0]._allowed.is_set())
        window.evaluate_js.assert_called_once()
        window.destroy.assert_not_called()

    def test_entry_failure_diagnostics_expose_no_native_url(self):
        expected = "file:///trusted/web/index.html"
        self.assertEqual(_document_failure(None, expected), "blank_document")
        self.assertEqual(_document_failure("about:blank", expected), "blank_document")
        self.assertEqual(_document_failure(expected.upper(), expected), "url_case_mismatch")
        self.assertEqual(_document_failure(object(), expected), "unexpected_url_type")
        self.assertEqual(_document_failure("file:///private/person/secret", expected), "different_document")

    def test_dispatch_rejects_private_dotted_and_unregistered_native_methods(self):
        calls = []
        dispatch = restricted_dispatch(lambda *args: calls.append(args))
        for name in ("_controller.command", "command.__globals__.clear", "pywebviewMoveWindow",
                     "pywebviewEventHandler", "pywebviewStateUpdate", "create_file_dialog", None, 1):
            dispatch(None, name, [], "id")
        self.assertEqual(calls, [])
        for name in ("get_state", "get_preview", "command", "pywebviewAsyncCallback"):
            dispatch(None, name, [], "id")
        self.assertEqual([call[1] for call in calls],
                         ["get_state", "get_preview", "command", "pywebviewAsyncCallback"])

    def test_facade_only_exposes_three_methods_and_gates_native_actions(self):
        controller = FakeController()
        api = DesktopAPI(controller)
        self.assertEqual({name for name in dir(api) if not name.startswith("_")},
                         {"get_state", "get_preview", "command"})
        for operation in (api.get_state, lambda: api.get_preview(1), lambda: api.command("start", {})):
            with self.assertRaises(RuntimeError):
                operation()
        self.assertTrue(api.command("stop", {})["ok"])
        api._allowed.set()
        self.assertEqual(api.get_state(), {"schema_version": 1})
        self.assertTrue(api._observed.is_set())
        api._allowed.clear()
        with self.assertRaises(RuntimeError):
            api.command("capture", {})
        self.assertEqual(controller.commands, [("stop", {})])

    def test_navigation_requires_exact_bundled_document(self):
        expected = "file:///trusted/web/index.html"
        self.assertTrue(allowed_document(expected, expected))
        for value in (None, 1, "https://example.invalid", "about:blank", expected + "#x",
                      expected + "?x=1", "file:///trusted/web/styles.css", "file:///other/index.html"):
            self.assertFalse(allowed_document(value, expected))
