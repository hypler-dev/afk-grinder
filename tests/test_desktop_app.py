"""Trusted-shell API boundaries with no WebView or native backend."""

import unittest

from afk_grinder.desktop_app import DesktopAPI, _document_failure, allowed_document, restricted_dispatch


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
