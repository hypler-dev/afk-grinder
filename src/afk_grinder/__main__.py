"""Desktop entry point. Importing the package never sends native input."""

import argparse
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="AFK Grinder supervised desktop prototype")
    parser.add_argument("--check", action="store_true", help="Print native readiness without sending input")
    parser.add_argument("--dry-run", action="store_true", help="Run the default template without OS input or GUI")
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
    from .ui import main as open_ui

    open_ui()


if __name__ == "__main__":
    main()
