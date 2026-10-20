<!-- intent-driven-delivery:spec:v1 -->
# Specification: AFK Grinder desktop application

Status: accepted
Intent: [intent.md](intent.md)
Owner: Jeff / hypler-dev
Last updated: 2026-10-20

## Behavior

The application is a local Python/Tk desktop application for Windows and macOS. Its default runtime remains the supervised input prototype. The adopted [BUILD.md](BUILD.md) defines further milestones; implementation status and evidence live in [plan.md](plan.md). No runtime LLM, cloud inference, login automation, or credential storage is used.

The default mode is dry run. A user can edit a version-1 JSON template containing `hold_key`, `click`, and `wait` actions. Keys are restricted to movement/interact controls; clicks use the current pointer position. Individual holds and waits are at most five seconds, a template has at most 100 steps, and total execution including a three-second start countdown is at most 30 seconds. No repeat loop is supported.

To bind a live target, the user starts a three-second capture countdown and manually focuses Roblox. The native adapter checks the foreground process, using the Roblox bundle identifier on macOS or player executable name on Windows. macOS reads the current foreground process through ApplicationServices GetFrontProcess/GetProcessPID and resolves its fixed identity through NSRunningApplication; it must not rely on cached NSWorkspace focus or require a Cocoa run loop. Missing native functions or query errors fail closed. These deprecated Process Manager APIs are a prototype compatibility dependency. The binding pins that process and, on Windows, its window handle. It never brings Roblox to the foreground automatically.

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

Do not request or collect login credentials, session tokens, arbitrary keystrokes, or unrelated window titles. The input prototype does not capture screenshots. The blueprint permits window-only in-memory capture for local recognition after its capture/calibration gates; persistent diagnostic images require explicit consent. macOS live execution requires permission to post events and observe the Escape key state. Permission checks must not silently request access. Status messages contain operation/result information only.

## Optional recognition SDK foundation

The `recognition` extra pins MaaFw 5.14.3 and its resolved transitive dependencies in uv.lock. Importing the application or recognition boundary does not import the SDK. `--sdk-check` launches a disposable child process with a 15-second whole-process deadline, including native loading and destruction. Status travels through a private temporary JSON file, because frozen Windows windowed apps have no standard output. The file contains no pixels and is removed after the check.

The probe rejects `MAAFW_BINARY_PATH`, requires matching installed/native versions, disables persistent SDK logs, saved draws, saved error images and debug mode, caps the recognition cache at two frames, selects a CPU resource, and binds a custom controller containing a synthetic 2×2 frame. Every input, shell, start-app and stop-app callback rejects requests. It checks SDK cancellation with bounded status polling and never uses `Job.wait()`. A polling deadline alone cannot bound a stuck native call; the outer process deadline provides that boundary. This is SDK initialization evidence, not game recognition or care-task proof.

SDK-bearing bundles can be built locally with `tools/build.py --with-recognition` for diagnosis. CI builds and checks these without uploading them, then rebuilds the downloadable input prototype with MaaFw/MaaAgentBinary/NumPy/StrEnum excluded. Packaging rejects an SDK-bearing bundle until the corresponding-source and notice distribution gate is closed. Project and upstream license notices accompany source and test artifacts.

## Observation and coordinate foundation

Observation metadata separates physical BGR capture dimensions, reference coordinates and native input coordinates. It includes the pinned Roblox process/window, native content bounds, monitor, measured scale, monotonic capture timestamp, generation and sequence. Geometry validation rejects oversized or inconsistent buffers and unsupported aspect ratios rather than stretching the scene. Reference-to-pixel and pixel-to-native conversions use the measured content rectangle, including negative monitor origins and fractional/Retina scale.

The tracker clears calibration after capture failure, stale/future/out-of-order frames, target/window replacement, or any bounds, monitor, size or scale change. Old callbacks and observations cannot remain current after a newer frame. Calibration requires a fresh frame. This pure geometry layer sends no input and does not establish anchors, gameplay readiness or care-task completion. Native capture and calibration UI acceptance remain separate gates.

## Compatibility and migration

Windows uses documented Win32 APIs through `ctypes`; macOS uses AppKit/Quartz through PyObjC. Python 3.11+ with Tk is required for source execution. Installer binaries remain future delivery targets. A PyInstaller packaging recipe and automated test-artifact builds cover Windows x64 and macOS Apple Silicon/Intel. No Linux backend is provided.

Templates are plain declarative JSON with no executable code, credentials, session tokens, screen images, or arbitrary text entry. The bundled Adopt Me input-check template tests controls only and does not claim to complete gameplay tasks.

## Acceptance mapping

Use fake backends to test deterministic safety behavior without sending OS input. Native hardware checks remain required on both target platforms. Test focus loss during holds/waits/countdown, Escape, cancellation, close, native errors, cleanup failures, and dry run. Validate packaging separately from game compatibility.

CI builds use hosted target-OS runners, pinned action revisions, and locked Python dependencies. Successful targets upload revision-labeled application archives, build metadata, and SHA-256 checksums with 14-day retention. Windows archives include all adjacent runtime files; Mac tar archives preserve app-bundle modes and symlinks. Unit/UI tests and packaged smoke checks must pass before upload. Native readiness checks may accept documented missing macOS permissions but must reject missing adapter modules or other startup errors. Repository visibility is public as authorized by the owner. No signing secrets, GitHub release publication, or live Roblox session is part of CI.

## Non-goals and open questions

See [intent.md](intent.md). Mobile, login, purchases, trading, injection and anti-cheat workarounds remain excluded. Verified indoor care routines and bounded recovery are future BUILD.md milestones; they are not enabled by the SDK diagnostic or geometry layer. Signed production release publication and longer-session enablement require their separate gates.
