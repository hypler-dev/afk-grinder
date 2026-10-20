<!-- intent-driven-delivery:plan:v1 -->
# Plan: Desktop input safety prototype

Status: accepted
Authority: [intent.md](intent.md)
Owner: Jeff / hypler-dev
Last updated: 2026-10-19

## Scope and protected lanes

Implement a bounded local input prototype with native Windows/macOS focus and Escape checks, then commit/push it and run automated private test-binary builds as explicitly requested. Authentication remains manual. No credential access, network runtime, live Roblox testing, public release publication, or mobile implementation.

## Files and ownership

- Controller: `intent.md`, `spec.md`, `plan.md`, `README.md`, `pyproject.toml`, `.gitignore`, `src/afk_grinder/models.py`, `engine.py`, `templates.py`, package entry points, `tests/`, `templates/`, and packaging recipe.
- Native implementation worker: `src/afk_grinder/backends/` only.
- UI implementation worker: `src/afk_grinder/ui.py` only, following the separate UI design handoff.
- Read-only designer and reviewers: exact scoped source and documentation only.

Final changed paths (all relative to the repository root):

```text
.gitignore
README.md
intent.md
plan.md
pyproject.toml
spec.md
uv.lock
src/afk_grinder/__init__.py
src/afk_grinder/__main__.py
src/afk_grinder/backends/__init__.py
src/afk_grinder/backends/macos.py
src/afk_grinder/backends/windows.py
src/afk_grinder/engine.py
src/afk_grinder/models.py
src/afk_grinder/templates.py
src/afk_grinder/tk_runtime.py
src/afk_grinder/ui.py
tests/test_backends.py
tests/test_engine.py
tests/test_templates.py
tools/build.py
tools/launch.py
tools/smoke_ui.py
```

## Sequence

1. Establish accepted scope, behavior, and shared interfaces.
2. Obtain a bounded UI design; implement native adapters and controller-owned safety engine independently.
3. Integrate the Tk interface and bundled input-check template.
4. Run safety unit tests, static compilation, artifact validators, and a dry-run/source startup check.
5. Obtain fresh independent code and UI review; fix findings and rerun affected checks.
6. Record exact evidence and remaining native hardware tests. Do not publish a release.

## Validators

- `python3 -m unittest discover -s tests -v`
- `python3 -m compileall -q src tests`
- Run `python3 /Users/jeff/.agents/skills/intent-driven-delivery/scripts/validate_artifact.py FILE` separately for `intent.md`, `spec.md`, and `plan.md`.
- `git diff --check`
- Source GUI and native readiness smoke on the current macOS host, without sending game input.
- A local package build when dependencies are available; no signing or distribution claim.

## Independent review

Use native GPT design/implementation/review roles from the user routing instructions. Send only exact secret-free files and contracts. Fresh reviewers receive accepted intent, exact diff, and evidence; review does not authorize release. GLM is optional by fit; authentication boundaries and safety integration remain controller-owned.

## Rollback and recovery

Stop all workers before removing source or generated build artifacts. No production state is changed. Cancellation always attempts to release tracked inputs. A cleanup error blocks further live execution and instructs the user to check held input before restarting.

## Deviations

None at plan creation. Python/Tk is the bounded proof-of-input prototype; Tauri remains a possible later production shell.

## Evidence ledger

- Host: macOS 26.0, Apple Silicon; `.venv` uses CPython 3.12.11 arm64. System CPython 3.11.6 also runs the headless safety suite. Windows hardware is unavailable in this session.
- `uv sync --extra build`: PASS after network access was permitted; `uv.lock` records resolved dependencies. Initial sandbox DNS failures did not change dependency scope.
- `.venv/bin/python -m unittest discover -s tests -v`: PASS, 32 tests, including direct stop/acquisition contention and native Escape fake-adapter coverage.
- `.venv/bin/python -m compileall -q src tests tools`: PASS.
- Intent, spec, and plan artifact validators: PASS, one invocation per file. `git diff --check`: PASS; whitespace checks for all 20 new files: PASS.
- `.venv/bin/python -m afk_grinder --dry-run`: PASS; default three-step sequence completed without OS input.
- `.venv/bin/python -m afk_grinder --check`: expected exit 1, reporting missing Accessibility/Input Monitoring/post permissions. No permission was requested or granted and no input was sent. An initial Quartz-only AX lookup was corrected to ApplicationServices.
- GUI source startup initially failed because the uv-managed Python did not locate its shipped Tcl/Tk data; `tk_runtime.configure_tk()` now locates that source runtime. Desktop tests also require WindowServer access outside the filesystem sandbox. A withdrawn-window test stall was isolated to test setup; visible test windows work.
- `.venv/bin/python tools/smoke_ui.py`: 8 tests PASS outside the sandbox with fake input only, including native macOS Quit callback cleanup. A diagnostic 12-second timeout wrapper also completed normally.
- `.venv/bin/python tools/build.py`: PASS for the final local macOS arm64 application. Packaged command-line dry run PASS; default packaged dark GUI rendered and was inspected. The first packaged native readiness check exposed missing lazy-imported PyObjC modules; explicit hidden imports fixed this. Final packaged `--check` loads native modules correctly and returns expected exit 1 for missing Accessibility/Input Monitoring/post permissions. Output is not developer-signed/notarized and is not an installer or published release.
- Controller: native GPT/Sol (OpenAI). Design: `gpt_ui_design`; adapters/UI: `gpt_worker`; independent safety review: `gpt_reviewer`; UI/accessibility/QA/performance review: `gpt_ui_review` (OpenAI Terra roles). GLM unused; no GLM contact attempted, no provider errors or fallback.
- Initial independent code review found no engine/adapter defects; requested completed evidence ledger and two meaningful regression tests. Both tests now pass. Final independent safety follow-up: PASS, no actionable P1/P2/P3 findings. UI/accessibility/QA/performance review: PASS with assistive-technology and platform hardware gates explicitly open; native Quit callback and main-loop cleanup were added before that final review.
- Remaining gates: real Windows validation/build; real Roblox input acceptance, focus loss, Escape, Stop, and quit on each platform; clean-machine packaged permissions and install/uninstall; CPU architecture coverage; accessibility with assistive technology; installer creation, signing/notarization, and separately authorized publication.
- Original prototype handoff: no live game input, login, account access, screenshot capture by the application, deployment, or release publication occurred. At that snapshot no prototype commit or push had been requested or performed. The subsequent October 19 instruction authorizes commit/push and private CI test artifacts. Repository remains private `hypler-dev/afk-grinder`; bootstrap HEAD was `25ff352`.
- Original prototype working-tree snapshot: 3 modified tracked files and 20 new source/documentation files, all owned by this slice. No unrelated dirt observed. `.venv/`, `build/`, and the 29 MB local `dist/AFKGrinder.app` are ignored generated state. The local executable is macOS arm64; its SHA-256 is `ead700c6323e98018648ff4a66375a53449c45813b0480916bdce95106e65fa5`.
