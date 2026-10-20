"""Native Tk state smoke with fake input only; requires a desktop session."""

from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afk_grinder.tk_runtime import configure_tk

configure_tk()

import tkinter as tk

from afk_grinder.models import Target
from afk_grinder.ui import App


class FakeBackend:
    def __init__(self):
        self.calls = []

    def foreground(self):
        return Target(100, "100", "RobloxPlayerBeta.exe", "win32")

    def readiness(self):
        return []

    def escape_pressed(self):
        return False

    def key_down(self, key):
        self.calls.append(("down", key))

    def key_up(self, key):
        self.calls.append(("up", key))

    def mouse_down(self, button):
        self.calls.append(("mouse_down", button))

    def mouse_up(self, button):
        self.calls.append(("mouse_up", button))


class UISmoke(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.backend = FakeBackend()
        self.app = App(self.root, backend=self.backend)
        self.root.update()

    def tearDown(self):
        self.app.runner.stop()
        self.app.runner.join(1)
        try:
            self.app._destroy()
        except tk.TclError:
            pass

    def settle(self):
        deadline = time.monotonic() + 1
        while self.app._run_locked and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.root.update()
        self.assertFalse(self.app.runner.running)
        self.assertFalse(self.app._run_locked)

    def enable_live(self):
        self.app.mode_var.set("live")
        self.app.target = self.backend.foreground()
        self.app._refresh_readiness()
        self.app.confirm_var.set(True)
        self.root.update()

    def test_default_dry_and_invalid_template_gates(self):
        self.assertEqual(self.app.mode_var.get(), "dry")
        self.assertFalse(self.app.start_button.instate(["disabled"]))
        self.app.editor.delete("1.0", "end")
        self.app.editor.insert("1.0", "{")
        self.assertFalse(self.app._validate())
        self.assertTrue(self.app.start_button.instate(["disabled"]))

    def test_live_requires_binding_readiness_and_per_run_confirmation(self):
        self.app.mode_var.set("live")
        self.assertTrue(self.app.start_button.instate(["disabled"]))
        self.enable_live()
        self.assertFalse(self.app.start_button.instate(["disabled"]))
        self.app.confirm_var.set(False)
        self.assertTrue(self.app.start_button.instate(["disabled"]))

    def test_invalid_live_start_consumes_confirmation(self):
        self.enable_live()
        self.app.editor.delete("1.0", "end")
        self.app.editor.insert("1.0", "{")
        self.app._start()
        self.assertFalse(self.app.confirm_var.get())
        self.assertFalse(self.app.runner.running)

    def test_binding_locks_and_stop_cancels_without_input(self):
        self.app.mode_var.set("live")
        self.app._begin_binding()
        self.assertTrue(self.app.start_button.instate(["disabled"]))
        self.assertFalse(self.app.stop_button.instate(["disabled"]))
        self.assertTrue(self.app.dry_radio.instate(["disabled"]))
        self.app._stop()
        self.assertIsNone(self.app._binding_after)
        self.assertEqual(self.backend.calls, [])

    def test_preview_setup_blocks_input_start_without_changing_mode(self):
        self.app._open_recognition_setup()
        self.root.update()
        self.assertTrue(self.app._preview_open())
        self.app._start()
        self.assertFalse(self.app.runner.running)
        self.assertEqual(self.app.mode_var.get(), "dry")
        self.assertEqual(self.backend.calls, [])
        self.app._recognition_setup.close()
        self.assertFalse(self.app._preview_open())

    def test_preview_cannot_open_during_input_and_closes_with_app(self):
        self.app._run_locked = True
        self.app._open_recognition_setup()
        self.assertFalse(self.app._preview_open())
        self.app._run_locked = False
        self.app._open_recognition_setup()
        preview = self.app._recognition_setup
        self.app._on_close()
        self.assertTrue(preview._closed)
        self.assertEqual(self.backend.calls, [])

    def test_countdown_stop_keeps_terminal_status(self):
        self.app._start()
        self.assertTrue(self.app.start_button.instate(["disabled"]))
        self.app._stop()
        self.settle()
        self.assertIn("stopped:", self.app.status_var.get())
        self.assertEqual(self.backend.calls, [])

    def test_close_during_fake_live_hold_releases_input(self):
        self.enable_live()
        with patch("afk_grinder.engine.COUNTDOWN_SECONDS", 0):
            self.app._start()
            deadline = time.monotonic() + 1
            while not self.backend.calls and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertEqual(self.backend.calls[0], ("down", "w"))
            self.app._on_close()
            self.app.runner.join(1)
        self.assertEqual(self.backend.calls[-1], ("up", "w"))

    def test_live_controls_fit_minimum_window(self):
        self.app.mode_var.set("live")
        self.root.deiconify()
        self.root.geometry("640x620")
        self.root.update()
        bottom = self.app.stop_button.winfo_rooty() + self.app.stop_button.winfo_height()
        self.assertLessEqual(bottom, self.root.winfo_rooty() + self.root.winfo_height(),
                             "Stop button is outside the minimum live window")

    @unittest.skipUnless(sys.platform == "darwin", "macOS native Quit callback")
    def test_native_quit_routes_through_cleanup(self):
        self.enable_live()
        with patch("afk_grinder.engine.COUNTDOWN_SECONDS", 0):
            self.app._start()
            deadline = time.monotonic() + 1
            while not self.backend.calls and time.monotonic() < deadline:
                self.root.update()
                time.sleep(0.01)
            self.assertEqual(self.backend.calls[0], ("down", "w"))
            self.root.tk.call("::tk::mac::Quit")
            self.app.runner.join(1)
        self.assertEqual(self.backend.calls[-1], ("up", "w"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
