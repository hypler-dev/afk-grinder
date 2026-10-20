<!-- intent-driven-delivery:spec:v1 -->
# Specification: AFK Grinder desktop application

Status: accepted
Intent: [intent.md](intent.md)
Owner: Jeff / hypler-dev
Last updated: 2026-10-20

## Behavior

The application is a local Python desktop application with a bundled pywebview game-library interface for Windows and macOS. Its default runtime remains the supervised input prototype. The adopted [BUILD.md](BUILD.md) defines further milestones; implementation status and evidence live in [plan.md](plan.md). No runtime LLM, cloud inference, login automation, or credential storage is used.

The default mode is dry run. A user can edit a version-1 JSON template containing `hold_key`, `click`, and `wait` actions. Keys are restricted to movement/interact controls; clicks use the current pointer position. Individual holds and waits are at most five seconds, a template has at most 100 steps, and total execution including a three-second start countdown is at most 30 seconds. No repeat loop is supported.

The launcher automatically discovers verified running Roblox players without moving focus. macOS enumerates the exact Roblox bundle identity and re-resolves each process; Windows enumerates eligible visible top-level windows and resolves each PID's exact player executable. One candidate binds automatically. Multiple candidates require an explicit choice, which remains selected while that identity survives. Opaque candidate IDs are not recycled for replacement targets. Missing, failed or stalled discovery invalidates acknowledgment and setup. Discovery never arms, starts or resumes input.

During execution, macOS checks the actual foreground process through ApplicationServices GetFrontProcess/GetProcessPID and resolves its fixed identity through NSRunningApplication; it must not rely on cached NSWorkspace focus. These deprecated Process Manager APIs remain a prototype compatibility dependency. Windows pins both process and HWND. Missing native functions or query errors fail closed. The legacy Tk troubleshooting interface retains its manual foreground-binding countdown.

Before every live run the user must explicitly arm input and confirm manual login is complete, gameplay is visible, and chat/menus are closed. Start permits a three-second manual switch to the bound target. At countdown completion and throughout playback, missing target focus, an unavailable permission, or any adapter error stops the run. Dry run follows the same bounded timing but does not require a live target or native permissions.

An Escape key state check runs during live countdown and playback, including waits. A GUI Stop button and window close request cancellation. All acquired keys/buttons are released on completion, cancellation, focus loss, or error. Release failure is displayed and never reported as successful cleanup. A new run requires a fresh live acknowledgment; a failed cleanup blocks further live execution until the application is restarted and the user checks input state.

## Interfaces and contracts

`Backend` exposes `foreground() -> Target | None`, `readiness() -> list[str]`, `escape_pressed() -> bool`, `key_down(key)`, `key_up(key)`, `mouse_down(button)`, and `mouse_up(button)`.

`Target` contains process ID, native focus token, executable name, and application identifier. Equality pins the captured identity. Display only target information needed by the user; do not log titles or key activity from unrelated applications.

The engine runs on a worker thread, posts status through a thread-safe queue, and uses a cancellation event. The launcher passes a separate start ticket that Stop/Close invalidates before a pending readiness check can complete; cancellation cannot be erased by a late start. Native calls must be short and synchronous. It checks guards at most every 20 milliseconds during waits, subject to OS scheduling; this is not a real-time guarantee.

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

The capture-to-layout bridge derives physical/native conversion from measured frame and native rectangle extents. Display-DPI metadata remains a separate layout field: Windows physical client pixels can map 1:1 to native input while the display reports 150% scaling; Retina capture can map 2:1. DPI-only changes invalidate layout equality. Raw Mac window captures retain their unverified-content flag through geometry checks.

Recognition Setup supports a 1280×720 (16:9) geometry-reference demo. A user can drag an image-bounded area, or focus the preview and press Enter/Space to create an area, then move it with arrows, resize with Shift+arrows, or reset with R. Historical previews remain editable references after current observation/calibration expires at 0.5 seconds. Refresh and check area retains only the selected rectangle and source layout while clearing old pixels/results, then requests a fresh capture. Only a fresh returned frame with the same target/window/bounds/monitor/physical conversion/display scale/region metadata can establish snapshot geometry. New captures, target changes, failures, cancellation and close clear pending geometry. This does not configure anchors/targets, verify game content bounds, establish a supported minimum resolution or enable input.

## Compatibility and migration

### Native preview and restricted pack foundations

Tools → Recognition setup opens a separate no-input modal. It reuses explicit Roblox binding, can request one window-only preview, and can check the optional SDK using synthetic pixels. Opening it blocks input Start; it cannot open during an input run. Cancel, Escape, target change, and Close clear the displayed snapshot and reject late results. No screenshot is written to disk. The modal never establishes calibrated anchors, gameplay readiness, or permission to act.

Capture and SDK operations run in disposable spawned processes with a 15-second operation deadline. Process startup, pipe reads, native teardown, and termination run away from Tk's event thread. A closed child start gate permits no native imports or capture until the parent has a signalable process handle; a child with an expired deadline exits without starting native work. Cancellation and the gate grant share a lock. An operating-system stall during process creation can delay cleanup of bootstrap resources; it cannot grant capture or SDK work. This is not a real-time OS termination guarantee. Frame IPC is bounded JSON metadata plus raw BGR bytes; status and images remain in memory. Publication and cancellation share a lock so cancellation discards queued and late frames. Frozen entry points call multiprocessing freeze support before application argument parsing.

The macOS capture worker must initialize on its main thread before ScreenCaptureKit discovery and content-filter APIs run. When no AppKit application exists, it creates a shared `NSApplication`, sets `NSApplicationActivationPolicyProhibited`, and does not activate or run it; an existing application is preserved. Initialization failure is reported as an allowlisted diagnostic. A deadline check after adapter construction rejects a snapshot if native initialization consumed the remaining budget. Worker IPC uses fixed safe messages and never forwards native exception text, paths, window titles, or other sensitive details. The generic preview/SDK failure message is `Preview or SDK check failed. No input was sent.` The only optional exception is the fixed allowlisted SDK-absence message used by the SDK-free smoke, matched exactly as an `SDKError`; all other exception text is generic. Elevated no-capture child and frozen launcher checks pass; they do not establish native capture acceptance.

Windows uses a pinned HWND/PID and client-only PrintWindow with physical screen coordinates and display-DPI metadata; it has no desktop fallback. macOS capture requires macOS 14+ ScreenCaptureKit and an existing Screen Recording grant, never prompts automatically, and selects the bound Roblox window. Its raw window region is labelled unverified content bounds. Both adapters validate identity and geometry before and after capture and reject invalid, minimized, missing, or oversized results. macOS uses one predicate for selection and bound-ID revalidation: verified target PID and Roblox bundle, on-screen layer 0, finite frame metadata, and a minimum 320×240 logical-point frame. Zero qualified windows reports `window_missing`; multiple qualified windows reports `window_count`, with no title or largest-window heuristic. A binding becomes invalid when the predicate no longer holds. The staged `e594508` candidate predates this predicate and failed at window selection; native acceptance of the corrected source remains open. Fake-adapter checks do not establish hardware capture acceptance.

The separate version-1 resource-pack loader accepts only a restricted local declarative schema, bounded PNG assets and metadata, explicit provenance/license/hash fields, anchors, positive/excluded states, and stability requirements. Routine lists must remain empty. No Maa pipeline, executable plugin, arbitrary action, network update, archive extraction, or engine integration is enabled. The reader rejects oversized/deep structures, malformed numbers/images, path escapes, symlinks and hardlinks. POSIX uses pinned directory descriptors; Windows path-identity checks do not provide the same descriptor-relative guarantees. A successful load is schema validation, not game-state recognition or pack distribution acceptance.

The separate offline recognition foundation is a pure, read-only state inspector over a validated resource pack, an observation and caller-supplied anchor scores. Each call supplies finite monotonic `now`; a capture must be no later than `now` and at most 0.5 seconds old. The caller remains responsible for supplying the current observation and binding recognition results to that frame. A score is an exact integer or float in `[0,1]`; booleans, non-finite/out-of-range values and unknown anchor IDs are invalid rather than coerced. Missing or `None` evidence is unavailable, distinct from an evaluated score below its anchor threshold. The inspector and its history retain only identity, layout and outcome metadata, never observation objects or pixel buffers. It performs no image matching, SDK loading, capture, input or bridge operation. Positive evidence plus a matching exclusion blocks the result. Missing evidence, multiple possible states, invalid scores, stale or replayed observations and unverified content bounds produce an explicit unknown result. A unique supported candidate needs its declared consecutive stable-frame count and reports `unknown/unstable` while that count accumulates. Incomplete, conflicting, invalid, stale or ambiguous evidence resets stability. Layout/generation changes and skipped frame sequences restart stability, and duplicate or older observations cannot count again. This offline component does not close native capture, real fixture-corpus or recognition acceptance and cannot authorize input.

### Game library design

The separate offline HTML design follows [docs/UI_DESIGN.md](docs/UI_DESIGN.md): a dark violet/cyan library, original game-cover previews, per-game workspaces, explicit support status, and persistent Stop. Adopt Me is the first input-check profile; Bee Swarm Simulator and Blox Fruits are viewable proposed profiles with no input path. Game changes invalidate setup and arming; cleanup failure remains global. That HTML remains a simulated reference. The native launcher now ports its visual direction with authoritative Python state through the restricted [desktop bridge](docs/DESKTOP_BRIDGE.md). It loads only bundled files with native navigation cancellation, CSP, an explicit three-method dispatch allowlist and no HTTP server or remote resources. Settings displays version/source/platform. The earlier Tk interface remains an explicit `--legacy-ui` troubleshooting option. No game compatibility claim follows from either UI.

The native Interface menu offers 100%, 125%, 150%, 175% and 200% page zoom on the WebView UI thread. Closing drops pending zoom callbacks. Zoom changes launcher visuals only; it does not change stored source-pixel reference areas or arm/start input. Normal focus-loss and Stop guards remain active. Responsive grid tracks shrink without hiding page overflow; narrow navigation scrolls within its own bounds, with header Stop visible. Preview canvases use CSS dimensions and a device-pixel-ratio backing store, converting pointer coordinates through the live displayed rectangle into source pixels. Window/viewport resize redraws the image without modifying reference metadata.

Windows uses documented Win32 APIs through `ctypes`; macOS uses AppKit/Quartz through PyObjC. Python 3.11+ and the target OS WebView are required for source execution; Tk is required for legacy troubleshooting and its GUI tests. Installer binaries remain future delivery targets. The PyInstaller recipe and test-artifact workflow target Windows x64 and macOS Apple Silicon/Intel. Earlier successful artifacts use Tk; exact-revision new-launcher CI acceptance is recorded separately in plan.md. No Linux backend is provided.

Templates are plain declarative JSON with no executable code, credentials, session tokens, screen images, or arbitrary text entry. The bundled Adopt Me input-check template tests controls only and does not claim to complete gameplay tasks.

## Acceptance mapping

Use fake backends to test deterministic safety behavior without sending OS input. Native hardware checks remain required on both target platforms. Test focus loss during holds/waits/countdown, Escape, cancellation, close, native errors, cleanup failures, and dry run. Validate packaging separately from game compatibility.

CI builds use hosted target-OS runners, pinned action revisions, and locked Python dependencies. Successful targets upload revision-labeled application archives, build metadata, and SHA-256 checksums with 14-day retention. Windows archives include all adjacent runtime files; Mac tar archives preserve app-bundle modes and symlinks. Unit/UI tests and packaged smoke checks must pass before upload. Native readiness checks may accept documented missing macOS permissions but must reject missing adapter modules or other startup errors. Repository visibility is public as authorized by the owner. No signing secrets, GitHub release publication, or live Roblox session is part of CI.

## Non-goals and open questions

See [intent.md](intent.md). Mobile, login, purchases, trading, injection and anti-cheat workarounds remain excluded. Verified indoor care routines and bounded recovery are future BUILD.md milestones; they are not enabled by the SDK diagnostic or geometry layer. Signed production release publication and longer-session enablement require their separate gates.
