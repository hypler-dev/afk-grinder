"""Desktop entry point. Importing the package never sends native input."""

import argparse
import json
from pathlib import Path
import sys


def main() -> None:
    from multiprocessing import freeze_support

    freeze_support()
    parser = argparse.ArgumentParser(description="AFK Grinder supervised desktop prototype")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Print native readiness without sending input")
    mode.add_argument("--dry-run", action="store_true", help="Run the default template without OS input or GUI")
    mode.add_argument("--ui-smoke", action="store_true", help="Open and close a dry-run UI without native input")
    mode.add_argument("--sdk-check", action="store_true", help="Check optional local recognition with synthetic pixels only")
    mode.add_argument("--sdk-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--sdk-report", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.sdk_report and not args.sdk_worker:
        parser.error("--sdk-report is reserved for the SDK diagnostic worker.")
    if args.sdk_check or args.sdk_worker:
        from .recognition.maa_adapter import SDKError, diagnostic, probe_sdk

        try:
            report = probe_sdk() if args.sdk_worker else diagnostic()
            if args.sdk_report:
                with args.sdk_report.open("x", encoding="utf-8") as report_file:
                    json.dump({"ok": True, "report": report}, report_file)
            elif sys.stdout is not None:
                print(json.dumps(report, sort_keys=True))
        except SDKError as exc:
            if args.sdk_report:
                with args.sdk_report.open("x", encoding="utf-8") as report_file:
                    json.dump({"ok": False, "error": str(exc)}, report_file)
            elif sys.stderr is not None:
                print(f"Recognition unavailable: {exc}", file=sys.stderr)
            sys.exit(1)
        return
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
        from .capture.service import BackgroundJob
        from .ui import App

        root = tk.Tk()
        app = App(root, backend=None)
        job = BackgroundJob("sdk")
        failure = []
        probe_complete = False

        def finish_probe() -> None:
            nonlocal probe_complete
            result = job.poll()
            if result is None:
                root.after(20, finish_probe)
                return
            missing_optional_sdk = result.error == "Recognition is optional. Install the locked recognition extra first."
            if not missing_optional_sdk and (result.error or result.report is None):
                failure.append("Spawned recognition service failed its no-input smoke check.")
            probe_complete = True
            app._on_close()

        try:
            root.after(20, finish_probe)
            root.mainloop()
        finally:
            job.cancel()
            app.runner.stop()
            app.runner.join()
            try:
                root.destroy()
            except tk.TclError:
                pass
        if not probe_complete or failure:
            if sys.stderr is not None:
                print(failure[0] if failure else "UI closed before observation smoke completed.", file=sys.stderr)
            sys.exit(1)
        print("Dry-run UI and spawned SDK-service startup passed. No OS input or capture used.")
        return
    from .ui import main as open_ui

    open_ui()


if __name__ == "__main__":
    main()
