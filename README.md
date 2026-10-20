# AFK Grinder

**Helping kids touch grass by automating their games.**

A local, supervised Windows/macOS input prototype for Roblox, starting with an editable Adopt Me input-check template.

**Current state:** prototype with deterministic keyboard/mouse playback, foreground process binding, cancellation, and emergency-stop checks. Automated builds provide Windows x64 and macOS Apple Silicon/Intel test bundles. The bundled template tests movement controls; it does not complete Adopt Me tasks. Live Roblox compatibility, representative player hardware, and production installers are not yet validated.

**No runtime LLM, cloud service, API key, login automation, credential storage, screenshots, or action recording.** Roblox sign-in stays manual.

## Why this exists

I built this for my kids because I wanted them to go outside. This is a fun family project aimed at spending less time on repetitive game chores and more time outdoors.

This is an experimental family project. The current prototype is for short, supervised input tests; unattended gameplay is not ready yet.

## Run from source

Use Python 3.11+ with Tk installed. Confirm Tk is available with `python -m tkinter` before installation. On macOS, use a Python distribution with working Tk; on Windows, include Tcl/Tk when installing Python.

From the project directory on either target OS:

```sh
python -m venv .venv
```

Activate on macOS:

```sh
source .venv/bin/activate
```

Activate on Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Then install and launch:

```sh
python -m pip install -e .
python -m afk_grinder
```

Alternatively, with uv and a Python installation containing Tk, use `uv sync --locked` and `uv run --locked python -m afk_grinder`. The committed `uv.lock` pins dependencies; plain pip installs use the declared compatible version ranges.

Two command-line checks send no native input:

```sh
python -m afk_grinder --dry-run
python -m afk_grinder --check
```

`--check` returns a nonzero exit code when native permissions/dependencies are missing. It does not grant permissions or establish game compatibility.

## First supervised test

1. Launch the app in its default **Dry run** mode. Validate the workflow and run it; no OS input is sent.
2. Sign into Roblox manually, enter the game, close chat/menus, and position the character away from sensitive interactions. Keep the game visible.
3. Select **Live input**. Refresh readiness and resolve any reported permissions. On macOS, Accessibility and Input Monitoring permission must be enabled for the relevant Python/application identity in System Settings; restart the app after permission changes if needed. The app does not request or grant permissions silently.
4. Click **Bind foreground Roblox** and switch manually to Roblox during the three-second countdown. The binding pins the process, and its window handle on Windows. Return to the prototype to inspect the binding.
5. Review the short JSON sequence. Confirm manual login/gameplay readiness, click Start, and switch to the bound Roblox window during the three-second countdown.
6. Press **Escape** to stop live execution. Clicking Stop or closing the prototype also cancels. Switching away from the bound target during playback stops the run; it never resumes automatically.

The default template holds W for 250 ms, waits 500 ms, and holds S for 250 ms. It is an input test, not a route or AFK grind routine. It has not been proven to work inside Roblox. Each live run consumes its acknowledgment; review the scene again before another run.

## Edit actions

Edit workflow JSON in the app. Copy the JSON to a local file to save it; the prototype has no recorder or import/export controls yet. Templates are data, not executable code:

```json
{
  "version": 1,
  "name": "Short input test",
  "steps": [
    {"action": "hold_key", "key": "w", "duration_ms": 250},
    {"action": "wait", "duration_ms": 500},
    {"action": "click", "button": "left"}
  ]
}
```

Allowed keys: `w`, `a`, `s`, `d`, `e`, `space`, `up`, `down`, `left`, `right`. Mouse clicks use the current pointer position and release after 80 ms. There is no pointer positioning, text entry, login action, looping, or script execution. Holds/waits are 1-5000 ms; at most 100 steps and 27 seconds of actions plus the three-second countdown. A wall-clock guard stops late runs, subject to native-call and OS scheduling latency.

## Safety limits

- Focus and Escape checks run before acquisitions and at intervals up to 20 ms during waits, subject to OS scheduling. This is not a real-time guarantee and short Escape taps can be missed; hold Escape until the run stops.
- The runner tracks each acquired key/button before posting it and attempts release on completion, focus loss, cancellation, and errors. Release failures are displayed and block later live runs until restart and manual input-state verification.
- Killing/crashing the process, OS failure, or revoked posting permissions can prevent cleanup. The application cannot guarantee release in those cases.
- Input goes through global OS APIs. Focus checking and event posting cannot be atomic; a small check-to-send race remains. The app never forces focus or injects into background windows.
- Process identity is a prototype allowlist, not a code-signature trust check. Focus cannot distinguish gameplay, login, chat, purchases, or menus inside Roblox. The user must remain present and stop if the screen changes. Authentication-screen recognition is not implemented.
- Do not use this supervised prototype for unattended AFK sessions. Screenshots, credentials, session tokens, and arbitrary key activity are neither collected nor stored.

Windows uses Win32 foreground/process identity APIs and `SendInput`; input can be blocked by privilege differences or rejected by the game. Do not run as administrator to work around failures. macOS uses AppKit, ApplicationServices, and Quartz. Native API success does not prove that Roblox consumed an event. See [Microsoft SendInput](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-sendinput) and [PyObjC framework notes](https://pyobjc.readthedocs.io/en/latest/notes/framework-wrappers.html).

## Local packaging

Build on the operating system and CPU architecture you intend to test. This creates an unsigned local application, not a production installer or published release:

```sh
python -m pip install -e ".[build]"
python tools/build.py
```

With uv, use `uv sync --locked --extra build` followed by `uv run --locked --extra build python tools/build.py`.

- macOS: `dist/AFKGrinder.app`
- Windows: `dist/AFKGrinder/AFKGrinder.exe` and its adjacent runtime files; keep the whole directory together.

Build output is ignored by Git. Windows installer creation and macOS distribution packaging, signing/notarization, clean-machine installation, upgrade/uninstall, and release publication remain future work. Do not treat an ad hoc signed or unsigned local build as a trusted production release.

## Download automated test builds

Open [Build desktop prototypes](https://github.com/hypler-dev/afk-grinder/actions/workflows/build.yml), select a successful run, and scroll to **Artifacts**. You must be signed into a GitHub account with access to this private repository.

| Download | Target | Contents |
| --- | --- | --- |
| `AFKGrinder-windows-x64-<commit>` | Windows x64 | Portable application ZIP; extract the entire directory and open `AFKGrinder.exe` |
| `AFKGrinder-macos-arm64-<commit>` | Apple Silicon Mac | `.tar.gz` containing `AFKGrinder.app` |
| `AFKGrinder-macos-x64-<commit>` | Intel Mac | `.tar.gz` containing `AFKGrinder.app` |

GitHub wraps each artifact in a download ZIP. Extract it, then extract the application archive inside. Keep the Windows executable beside its runtime files. The Mac archive preserves app-bundle symlinks and executable permissions. Each artifact includes `SHA256SUMS.txt` and `BUILD_INFO.json` identifying the exact source revision and architecture. Artifacts expire after 14 days; use **Run workflow** to rebuild when needed.

The workflow runs for app/build changes pushed to `main` and pull requests targeting `main`, plus manual dispatch. Each target runs safety/packaging tests, fake-input UI smoke, a native build, and packaged dry-run/readiness checks before uploading. macOS permission denial is expected on fresh runners; missing native modules or other startup errors fail the build. No Roblox session or game input runs in CI.

These are unsigned prototype bundles, not production installers or gameplay certification. OS signing/trust warnings may appear. This project does not disable OS protections or change permissions automatically. Live testing still requires your own manual Roblox sign-in and explicit input permissions.

## Validation

```sh
python -m unittest discover -s tests -v
python -m compileall -q src tests tools
```

On a desktop session, `python tools/smoke_ui.py` also exercises UI gates, binding cancellation, close/Quit cleanup, and minimum-window control visibility using a fake backend. It opens test windows but sends no OS keyboard/mouse input. Assistive-technology support remains unverified; the current Tk macOS accessibility tree does not expose the form controls reliably.

Unit tests use fake adapters and send no OS input. Before claiming support, test both target systems with a user-controlled game session: denied/granted permissions, wrong target, target closing, focus loss while holding a key/button, Escape during countdown/hold/wait, GUI Stop, window close, cleanup failure, and actual Roblox response. Run the same checks on packaged builds. Intel/Apple Silicon macOS builds and Windows architectures need separate evidence.

## Platforms and next steps

| Platform | Scope |
| --- | --- |
| Windows | x64 CI build/startup checks pass; supervised Roblox testing and installer pending |
| macOS | Apple Silicon/Intel CI build/startup checks pass; supervised Roblox testing and signed distribution pending |
| Linux | Excluded; [Roblox does not officially support it](https://en.help.roblox.com/hc/en-us/articles/203312800-Computer-Hardware-Operating-System-Requirements) |
| iOS / Android | Feasibility research only; no implementation commitment |

After desktop input proof: recorder and visual editor, guided Adopt Me calibration, visual checkpoints, tested task routines, then installers and signed releases. Research mobile input/capture restrictions, permissions, distribution rules, privacy, and stop controls separately. A shared framework alone does not establish mobile automation feasibility.

Roblox prohibits cheating/exploits and disruptive automation; permission for this particular use in Adopt Me has not been established. See [Roblox Community Standards](https://en.help.roblox.com/hc/en-us/articles/203313410-Roblox-Community-Standards) and [Adopt Me support](https://www.playadopt.me/support). Client injection, memory access, anti-cheat bypass, automated purchases, and trades remain excluded.

[intent.md](intent.md) is the canonical scope and acceptance record. [spec.md](spec.md) defines behavior; [plan.md](plan.md) records execution and validation evidence.
