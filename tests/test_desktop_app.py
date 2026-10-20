"""Trusted-shell API boundaries with no WebView or native backend."""

import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from afk_grinder.desktop_app import (DesktopAPI, _document_failure, _schedule_interface_scale,
                                    allowed_document, open_desktop, restricted_dispatch)


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
