<!-- intent-driven-delivery:spec:v1 -->
# Specification: Desktop input safety prototype

Status: accepted
Intent: [intent.md](intent.md)
Owner: Jeff / hypler-dev
Last updated: 2026-10-19

## Behavior

The application is a local Python/Tk desktop prototype for Windows and macOS. No runtime LLM, network service, screenshot capture, recording, login automation, or credential storage is used.

The default mode is dry run. A user can edit a version-1 JSON template containing `hold_key`, `click`, and `wait` actions. Keys are restricted to movement/interact controls; clicks use the current pointer position. Individual holds and waits are at most five seconds, a template has at most 100 steps, and total execution including a three-second start countdown is at most 30 seconds. No repeat loop is supported.

To bind a live target, the user starts a three-second capture countdown and manually focuses Roblox. The native adapter checks the foreground process, using the Roblox bundle identifier on macOS or player executable name on Windows. The binding pins that process and, on Windows, its window handle. It never brings Roblox to the foreground automatically.

Before every live run the user must explicitly arm input and confirm manual login is complete, gameplay is visible, and chat/menus are closed. Start permits a three-second manual switch to the bound target. At countdown completion and throughout playback, missing target focus, an unavailable permission, or any adapter error stops the run. Dry run follows the same bounded timing but does not require a live target or native permissions.

An Escape key state check runs during live countdown and playback, including waits. A GUI Stop button and window close request cancellation. All acquired keys/buttons are released on completion, cancellation, focus loss, or error. Release failure is displayed and never reported as successful cleanup. A new run requires a fresh live acknowledgment; a failed cleanup blocks further live execution until the application is restarted and the user checks input state.

## Interfaces and contracts

`Backend` exposes `foreground() -> Target | None`, `readiness() -> list[str]`, `escape_pressed() -> bool`, `key_down(key)`, `key_up(key)`, `mouse_down(button)`, and `mouse_up(button)`.

`Target` contains process ID, native focus token, executable name, and application identifier. Equality pins the captured identity. Display only target information needed by the user; do not log titles or key activity from unrelated applications.

The engine runs on a worker thread, posts status through a thread-safe queue, and uses a cancellation event. Native calls must be short and synchronous. It checks guards at most every 20 milliseconds during waits, subject to OS scheduling; this is not a real-time guarantee.

## States and failure handling

- Unsupported platform or missing native dependencies: live controls unavailable; dry run works.
- Missing macOS permissions: explain required permissions without silently requesting or granting them.
- Target not Roblox, target exits, or focus changes: stop; no automatic resume.
- Escape or explicit Stop: cancel countdown/wait and release tracked inputs.
- Permission loss or native injection failure: stop and report the failing operation.
- Invalid or oversized template: reject before starting the worker.
- Cleanup failure: attempt remaining releases, report failure, and block subsequent live runs.

Focus checks and global input injection cannot be atomic; a small check-to-send race remains. Application focus also cannot distinguish gameplay from an authentication screen within Roblox. The prototype is for short supervised input tests, not unattended AFK use.

## Data, privacy, and permissions

Do not request or collect login credentials, session tokens, arbitrary keystrokes, window titles, or screenshots. macOS live execution requires permission to post events and observe the Escape key state. Permission checks must not silently request access. Status messages contain operation/result information only.

## Compatibility and migration

Windows uses documented Win32 APIs through `ctypes`; macOS uses AppKit/Quartz through PyObjC. Python 3.11+ with Tk is required for source execution. Installer binaries remain future delivery targets. A PyInstaller packaging recipe and private automated test-artifact builds cover Windows x64 and macOS Apple Silicon/Intel. No Linux backend is provided.

Templates are plain declarative JSON with no executable code, credentials, session tokens, screen images, or arbitrary text entry. The bundled Adopt Me input-check template tests controls only and does not claim to complete gameplay tasks.

## Acceptance mapping

Use fake backends to test deterministic safety behavior without sending OS input. Native hardware checks remain required on both target platforms. Test focus loss during holds/waits/countdown, Escape, cancellation, close, native errors, cleanup failures, and dry run. Validate packaging separately from game compatibility.

CI builds use hosted target-OS runners, pinned action revisions, and locked Python dependencies. Successful targets upload revision-labeled application archives, build metadata, and SHA-256 checksums with 14-day retention. Windows archives include all adjacent runtime files; Mac tar archives preserve app-bundle modes and symlinks. Unit/UI tests and packaged smoke checks must pass before upload. Native readiness checks may accept documented missing macOS permissions but must reject missing adapter modules or other startup errors. No signing secrets, public release, or live Roblox session is part of CI.

## Non-goals and open questions

See [intent.md](intent.md). Mobile, recording, full Adopt Me automation, login, purchases, trading, anti-cheat workarounds, automatic recovery, and release publication are excluded.
