"""Desktop entry point. Importing the package never sends native input."""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="AFK Grinder supervised desktop prototype")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Print native readiness without sending input")
    mode.add_argument("--dry-run", action="store_true", help="Run the default template without OS input or GUI")
    mode.add_argument("--ui-smoke", action="store_true", help="Open and close a dry-run UI without native input")
    args = parser.parse_args()
    if args.dry_run:
        from .engine import Runner
        from .templates import DEFAULT_TEMPLATE, parse_template

        runner = Runner(None)
        runner.start(parse_template(DEFAULT_TEMPLATE))
        try:
            runner.join()
        except KeyboardInterrupt:
            runner.stop()
            runner.join()
        success = False
        while not runner.events.empty():
            status = runner.events.get_nowait()
            print(f"{status.state}: {status.message}")
            success = status.state == "completed"
        if not success:
            sys.exit(1)
        return
    if args.check:
        try:
            from .backends import create_backend

            backend = create_backend()
            problems = backend.readiness()
            target = backend.foreground()
            print("Foreground Roblox player:", "yes" if target and target.is_roblox else "no")
            if problems:
                for problem in problems:
                    print(problem)
                sys.exit(1)
            print("Native readiness checks passed. No input sent; game compatibility is untested.")
        except Exception as exc:
            print(f"Native backend unavailable: {exc}", file=sys.stderr)
            sys.exit(1)
        return
    from .tk_runtime import configure_tk

    configure_tk()
    if args.ui_smoke:
        import tkinter as tk
        from .ui import App

        root = tk.Tk()
        app = App(root, backend=None)
        try:
            root.after(200, app._on_close)
            root.mainloop()
        finally:
            app.runner.stop()
            app.runner.join()
            try:
                root.destroy()
            except tk.TclError:
                pass
        print("Dry-run UI startup passed. No native backend or OS input used.")
        return
    from .ui import main as open_ui

    open_ui()


if __name__ == "__main__":
    main()
