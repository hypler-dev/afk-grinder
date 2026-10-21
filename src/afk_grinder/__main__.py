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
    mode.add_argument("--legacy-ui", action="store_true", help="Open the earlier Tk prototype for troubleshooting")
    mode.add_argument("--ui-smoke", action="store_true", help="Open and close a dry-run UI without native input")
    mode.add_argument("--sdk-check", action="store_true", help="Check optional local recognition with synthetic pixels only")
    mode.add_argument("--sdk-worker", action="store_true", help=argparse.SUPPRESS)
    mode.add_argument("--evaluate-pack", type=Path, metavar="PACK", help="Evaluate explicitly consented local image fixtures; no input or capture")
    mode.add_argument("--fixture-worker", type=Path, help=argparse.SUPPRESS)
    mode.add_argument("--author-local", type=Path, metavar="PACK", help="Create a local model-authored training draft; no input or capture")
    mode.add_argument("--author-worker", type=Path, metavar="PACK", help=argparse.SUPPRESS)
    parser.add_argument("--sdk-report", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--sdk-replacement-probe", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--training-packet", type=Path, help="Validated draft JSON describing selected image fixtures")
    parser.add_argument("--fixture-directory", type=Path, help="Explicitly selected fixture directory")
    parser.add_argument("--fixture-report", type=Path, help="New local metadata-only evaluation report")
    parser.add_argument("--fixture-consent", action="store_true", help="Consent to local reading of the selected fixtures; no training or export")
    parser.add_argument("--fixture-split", choices=("train", "validation", "held_out"), help="Evaluate one split (default: held_out)")
    parser.add_argument("--author-model", help="Exact installed local model tag")
    parser.add_argument("--author-digest", help="Exact SHA-256 digest for the local model")
    parser.add_argument("--author-example", action="append", default=[], metavar="ID", help="Selected train example ID (repeat for each example)")
    parser.add_argument("--author-output", type=Path, metavar="NEWPATH", help="New local metadata-only authoring report")
    parser.add_argument("--author-consent", action="store_true", help="Consent to local selected-fixture authoring; no input or capture")
    parser.add_argument("--author-port", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.sdk_report and not args.sdk_worker:
        parser.error("--sdk-report is reserved for the SDK diagnostic worker.")
    if args.sdk_replacement_probe and not args.sdk_worker:
        parser.error("--sdk-replacement-probe is reserved for the SDK diagnostic worker.")
    authoring = args.author_local is not None or args.author_worker is not None
    author_options = (args.author_model, args.author_digest, args.author_example, args.author_output,
                      args.author_consent, args.author_port)
    if not authoring and any(value is not None and value is not False and value != [] for value in author_options):
        parser.error("Authoring options require --author-local.")
    if authoring:
        fixture_author_conflicts = (args.training_packet, args.fixture_report, args.fixture_consent, args.fixture_split)
        if any(value is not None and value is not False for value in fixture_author_conflicts):
            parser.error("Authoring modes cannot use training-packet or fixture evaluation options.")
        required_text = (args.author_model, args.author_digest)
        if (not all(isinstance(value, str) and value.strip() for value in required_text)
                or not args.author_example or any(not isinstance(value, str) or not value.strip() for value in args.author_example)
                or not args.author_consent or args.author_output is None or args.fixture_directory is None):
            parser.error("Local authoring requires --fixture-directory, --author-model, --author-digest, at least one --author-example, --author-output and --author-consent.")
        from .local_authoring import AuthoringError, run_authoring, validate_output, worker, write_output

        port = 11434 if args.author_port is None else args.author_port
        try:
            validate_output(args.author_output)
        except AuthoringError as error:
            parser.error(f"Local authoring output is invalid: {error.code}.")
        if args.author_worker is not None:
            worker(args.author_worker, args.fixture_directory, args.author_model, args.author_digest,
                   tuple(args.author_example), args.author_output, consent=args.author_consent, port=port)
            return
        try:
            report = run_authoring(args.author_local, args.fixture_directory, args.author_model, args.author_digest,
                                   tuple(args.author_example), consent=args.author_consent, port=port)
            payload = {"ok": True, "report": report}
        except AuthoringError as error:
            payload = {"ok": False, "error": error.code}
        write_output(args.author_output, payload)
        if sys.stdout is not None:
            if payload["ok"] is True:
                print("Local authoring completed; report saved. No input, capture or model changes.")
            else:
                print(f"Local authoring failed: {payload['error']}. See the metadata report. No input was sent.")
        if payload["ok"] is not True:
            sys.exit(1)
        return
    evaluating = args.evaluate_pack is not None or args.fixture_worker is not None
    fixture_options = (args.training_packet, args.fixture_directory, args.fixture_report, args.fixture_consent, args.fixture_split)
    if not evaluating and any(value is not None and value is not False for value in fixture_options):
        parser.error("Fixture options require --evaluate-pack.")
    if evaluating:
        if not all((args.training_packet, args.fixture_directory, args.fixture_report, args.fixture_consent)):
            parser.error("Fixture evaluation requires --training-packet, --fixture-directory, --fixture-report and --fixture-consent.")
        if args.fixture_report.exists() or args.fixture_report.is_symlink() or not args.fixture_report.parent.is_dir():
            parser.error("--fixture-report must be a new file with an existing parent directory.")
        from .fixture_evaluation import EvaluationError, run_evaluation, worker

        split = args.fixture_split or "held_out"
        if args.fixture_worker is not None:
            worker(args.fixture_worker, args.training_packet, args.fixture_directory, args.fixture_report,
                   consent=args.fixture_consent, split=split)
            return
        try:
            report = run_evaluation(args.evaluate_pack, args.training_packet, args.fixture_directory,
                                    consent=args.fixture_consent, split=split)
            payload = {"ok": True, "report": report}
        except EvaluationError as error:
            payload = {"ok": False, "error": error.code}
        with args.fixture_report.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
        if sys.stdout is not None:
            if payload["ok"] is True:
                print("Local static fixture evaluation completed; report saved. No input, capture or model training.")
            else:
                print(f"Local fixture evaluation failed: {payload['error']}. See the metadata report. No input was sent.")
        if payload["ok"] is not True:
            sys.exit(1)
        return
    if args.sdk_check or args.sdk_worker:
        from .recognition.maa_adapter import SDKError, diagnostic, probe_sdk

        try:
            if args.sdk_worker:
                report = probe_sdk(require_replacement=True) if args.sdk_replacement_probe else probe_sdk()
            else:
                report = diagnostic()
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
    if args.legacy_ui:
        from .tk_runtime import configure_tk
        from .ui import main as open_ui

        configure_tk()
        open_ui()
        return
    from .desktop_app import open_desktop

    try:
        open_desktop(smoke=args.ui_smoke)
    except Exception:
        if sys.stderr is not None:
            print("The native launcher could not start. Windows requires the Microsoft WebView2 runtime. "
                  "Use --legacy-ui for the earlier troubleshooting interface.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
