<!-- intent-driven-delivery:plan:v1 -->
# Plan: AFK Grinder desktop application

Status: accepted
Authority: [intent.md](intent.md)
Owner: Jeff / hypler-dev
Last updated: 2026-10-20

## Scope and protected lanes

Preserve the bounded local input prototype and develop the adopted BUILD.md roadmap incrementally. Public repository visibility/topics, the original README banner, commit/push and automated test artifacts remain authorized. Native gameplay tests remain short and supervised after manual login. Credential access, transactions, injection, signed/public GitHub release publication and mobile implementation are excluded. Longer sessions require the blueprint's endurance evidence; network pack updates require its curated signature/provenance gates.

## Files and ownership

- Controller: `intent.md`, `spec.md`, `plan.md`, `README.md`, `pyproject.toml`, `.gitignore`, `src/afk_grinder/models.py`, `engine.py`, `templates.py`, package entry points, `tests/`, `templates/`, and packaging recipe.
- Native implementation worker: `src/afk_grinder/backends/` only.
- UI implementation worker: `src/afk_grinder/ui.py` only, following the separate UI design handoff.
- Read-only designer and reviewers: exact scoped source and documentation only.
- Automated build follow-up: controller owns `.github/workflows/build.yml`, documentation, validation, GitHub Actions execution, and commit/push. A bounded native GPT implementation worker owns `tools/package_build.py`, `tools/check_build.py`, and `tests/test_package_build.py`. Fresh independent review covers the exact CI/helper/documentation delta before push.
- Public/demo follow-up: controller owns README, intent/spec/plan, `docs/MAC_LIVE_TEST.md`, `assets/afk-grinder-banner.png`, `assets/banner-prompt.txt`, workflow artifact-step wording, GitHub visibility/topics, and supervised testing. No worker receives live game screenshots or account data.

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
.github/workflows/build.yml
tools/check_build.py
tools/package_build.py
tests/test_package_build.py
docs/MAC_LIVE_TEST.md
assets/afk-grinder-banner.png
assets/banner-prompt.txt
```

## Sequence

1. Establish accepted scope, behavior, and shared interfaces.
2. Obtain a bounded UI design; implement native adapters and controller-owned safety engine independently.
3. Integrate the Tk interface and bundled input-check template.
4. Run safety unit tests, static compilation, artifact validators, and a dry-run/source startup check.
5. Obtain fresh independent code and UI review; fix findings and rerun affected checks.
6. Record exact evidence and remaining native hardware tests. Do not publish a release.
7. Follow-up authorized October 19: commit/push the reviewed prototype, add Windows x64/macOS arm64/macOS x64 hosted builds, test/package/checksum archives, upload private artifacts, and verify actual workflow completion and download records. Signed/public releases remain closed.

## Validators

- `python3 -m unittest discover -s tests -v`
- `python3 -m compileall -q src tests`
- Run `python3 /Users/jeff/.agents/skills/intent-driven-delivery/scripts/validate_artifact.py FILE` separately for `intent.md`, `spec.md`, and `plan.md`.
- `git diff --check`
- Source GUI and native readiness smoke on the current macOS host, without sending game input.
- A local package build when dependencies are available; no signing or distribution claim.
- Automated build follow-up: actionlint validates the workflow; helper tests verify archives/checksums/metadata; each hosted target runs unit tests, fake-input GUI smoke, a native build, and packaged startup checks before upload. Verify workflow status and actual artifact records through GitHub, then download and inspect the archives.

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
- Remaining gates: real Roblox input acceptance, focus loss, Escape, Stop, and quit on each platform; representative player hardware and minimum OS coverage; clean-machine packaged permissions and install/uninstall; accessibility with assistive technology; installer creation, signing/notarization, and separately authorized public release. The automated build follow-up below closes native build/startup coverage for Windows x64 and Mac arm64/x64.
- Original prototype handoff: no live game input, login, account access, screenshot capture by the application, deployment, or release publication occurred. At that snapshot no prototype commit or push had been requested or performed. The subsequent October 19 instruction authorizes commit/push and private CI test artifacts. At that handoff the repository was private `hypler-dev/afk-grinder`; bootstrap HEAD was `25ff352`.
- Original prototype working-tree snapshot: 3 modified tracked files and 20 new source/documentation files, all owned by this slice. No unrelated dirt observed. `.venv/`, `build/`, and the 29 MB local `dist/AFKGrinder.app` are ignored generated state. The local executable is macOS arm64; its SHA-256 is `ead700c6323e98018648ff4a66375a53449c45813b0480916bdce95106e65fa5`.

### Automated build follow-up

- Prototype committed and pushed as `38b07e9` (`feat: add supervised desktop input prototype`). The private repository's main branch was verified before push; the 32-test safety suite, whitespace checks, and intent/plan validators passed.
- User selected direct wording: "Helping kids touch grass by automating their games." README explains that this began as a fun project for Jeff's kids because he wanted them to go outside.
- Workflow targets Windows x64 (`windows-2025`), macOS arm64 (`macos-15`), and macOS x64 (`macos-15-intel`). Current standard/private runner labels were verified in official GitHub documentation.
- Official GitHub actions are pinned to verified commit SHAs: checkout v7.0.1, setup-python v7.0.0, upload-artifact v7.0.2. Read-only repository permission and disabled persisted checkout credentials are explicit. No signing secrets or public releases are introduced.
- Workflow YAML parsing and actionlint v1.7.12: PASS. The validator was downloaded from its official GitHub release and checked against its published SHA-256 file.
- Native GPT `gpt_worker` (OpenAI Terra) implemented `tools/package_build.py`, `tools/check_build.py`, and `tests/test_package_build.py`. Controller added no-input packaged `--ui-smoke` startup and integrated the workflow. GLM was unused; no GLM contact or fallback occurred.
- Local pre-push validation: 38 unit tests PASS; compile, tracked/new-file whitespace, artifact validators, and actionlint PASS. Rebuilt Mac arm64 package PASS; packaged dry run, no-input GUI startup, and native readiness all returned 0 outside the sandbox. No native input or permissions changes occurred. Archive metadata, SHA-256 sums, and executable mode checks PASS.
- Fresh independent CI/helper/CLI/documentation review by native GPT `gpt_reviewer` (OpenAI Terra): PASS, no actionable P1/P2/P3 findings. Private CI artifacts are authorized for testing; this does not authorize a public/signed release or live gameplay.
- CI implementation committed and pushed as `6cde71ea8f3cd32935956682b0124f9ae9312103` (`ci: build downloadable Windows and macOS apps`). [Run 39359240665](https://github.com/hypler-dev/afk-grinder/actions/runs/39359240665) completed successfully for all three targets.
- Hosted Windows: 38 unit tests reported, with 2 Mac-symlink fixtures skipped; 8 GUI tests reported, with 1 Mac-Quit test skipped. Both Mac jobs: all 38 unit and 8 GUI tests passed. Every target's packaged dry run, no-input GUI startup, and native readiness check returned 0. No Roblox game session or input was used.
- All three private artifact records were unexpired and tied to source `6cde71e`; retention is 14 days. Downloaded all three archives and independently verified outer SHA-256 sums, embedded/external metadata, exact source revision, runtime layout, binary architecture, and Mac executable mode plus 23 internal symlinks per Mac archive.

| Target | Verified binary | Archive bytes | GitHub artifact |
| --- | --- | --- | --- |
| Windows x64 | PE x64 | 11,567,292 | [12236632318](https://github.com/hypler-dev/afk-grinder/actions/runs/39359240665/artifacts/12236632318) |
| Mac Apple Silicon | Mach-O arm64 | 11,586,198 | [12236447572](https://github.com/hypler-dev/afk-grinder/actions/runs/39359240665/artifacts/12236447572) |
| Mac Intel | Mach-O x86_64 | 12,281,019 | [12235998511](https://github.com/hypler-dev/afk-grinder/actions/runs/39359240665/artifacts/12235998511) |

Archive SHA-256 values:

```text
1905d47e3ea5cb523f9104a8e752c3acf85096c768d99ea5a00de06ebad140e6  AFKGrinder-windows-x64.zip
f413cb849148a3ddf1fbf9b30a61ec9b74abbed53ca1fb0c5f56fc89907d96f3  AFKGrinder-macos-arm64.tar.gz
52771d2dfb4553e27e8b7454a1cd55016e12fffd740c12d5bc60016004ae8ff8  AFKGrinder-macos-x64.tar.gz
```

- The final receipt is documentation-only; source/build artifacts remain tied to `6cde71e`. Documentation-only pushes do not retrigger the path-filtered workflow. No unrelated dirt was observed. `.venv/`, `build/`, `dist/`, and `artifact-output/` remain ignored generated state.
- GitHub description and README use the user's exact tagline: "Helping kids touch grass by automating their games." At the automated-build handoff, repository visibility was private. No signing credentials, public releases, app-store submissions, deployment, account/login access, or live game input were used.


### Public repository and supervised Mac follow-up

- Authority: the owner explicitly requested public visibility, appropriate topics, original README artwork, and short supervised Mac tests after manual login. Public repository publication is separate from a signed binary release.
- Original artwork was generated with built-in image generation and inspected visually. `assets/afk-grinder-banner.png` is 1983 × 793 pixels; `assets/banner-prompt.txt` preserves the exact final prompt. The README embeds the image using a relative path. Subjects are fictional; no game screenshots or photos of the user's children were included.
- Publication check: Gitleaks v8.30.1 scanned all five existing commits and the downloaded CI logs with no leaks found. The final candidate and committed history are checked again before visibility changes.
- Mac test build: the verified CI arm64 artifact from source `6cde71ea8f3cd32935956682b0124f9ae9312103`, extracted outside the repository. Deep strict code-signature verification passed. Roblox sign-in was performed manually by the owner; gameplay was visible.
- At the initial live-test attempt, tests were BLOCKED: the application reports missing Accessibility and Input Monitoring permissions and keeps Start disabled. No live game input has been sent. Movement, focus-loss cancellation, physical Escape, and live held-key cleanup remained PENDING; this was not a live-game compatibility pass. The owner was asked to grant permissions manually and reopen the application.
- Verified GitHub topics: `roblox`, `adopt-me`, `automation`, `afk`, `python`, `tkinter`, `windows`, `macos`, `desktop-app`, `cross-platform`, `touch-grass`, `prototype`. GitHub CLI readback confirmed PUBLIC visibility and all 12 topics after the owner-authorized change.
- Controller: native GPT/Sol, OpenAI. Fresh independent publication/documentation review by native GPT `gpt_reviewer` (OpenAI Terra) found two P2 documentation issues: ambiguous bind-countdown wording and a public-visibility claim before readback. The wording was corrected and GitHub PUBLIC/topic readback now supports the claim; fresh follow-up review PASS, with no remaining P1/P2/P3 findings. No GLM invocation or external game/account-data transfer occurred. No signing credentials, public binary release, installer publication, deployment, login automation, purchases, or trades were performed.

- Follow-up validation: intent/spec/plan artifact checks, actionlint v1.7.12, README local links, and staged whitespace PASS. Candidate-directory Gitleaks scan (11.85 MB) and repeated all-history scan (five commits, 176.35 KB) found no leaks. At that validation snapshot, macOS administrator authentication was awaiting the owner; input permissions and live tests were not yet confirmed.

- Publication committed/pushed as `980772a1da379e202b7d36471d10db7dfa87bfaa`. An interrupted HTTP push was verified not to have reached the remote, then a command-scoped buffered HTTP/1.1 retry succeeded. Local and remote main matched; no unrelated dirt. Final all-history Gitleaks scan: six commits, 189.61 KB, no leaks.
- Public readback: unauthenticated HTTPS fetched the README and banner successfully; the README references the asset and remote image bytes match local SHA-256 `3963aa321950d2ff29ab91dbb3beb5001f58389327443f55659bb34549964f0b`. Generated with built-in image generation; exact prompt remains in `assets/banner-prompt.txt`.
- [Build run 39361632122](https://github.com/hypler-dev/afk-grinder/actions/runs/39361632122) succeeded for Windows x64, Mac arm64, and Mac x64 at `980772a`. GitHub reports all three artifacts unexpired: Windows `12237527433`, Mac arm64 `12237647191`, Mac x64 `12237667323`. These are test binaries, not signed installers or a published GitHub release.
- Permission follow-up: the owner explicitly confirmed granting Accessibility and Input Monitoring at action time and completed administrator authentication manually. System Settings visibly shows AFKGrinder enabled in both panels. Input Monitoring's Quit & Reopen action restarted the verified CI app.
- At the publication handoff, the live-test blocker was that the Tk form exposes no accessible controls to the UI tool, and tool coordinate clicks/keyboard navigation did not change mode. The owner was asked to select Live input and refresh readiness. Native readiness in the restarted app was unverified at that point; the later supervised attempt below passed readiness. No live game input has been sent; movement, focus-loss cancellation, physical Escape, and live held-key cleanup remain PENDING.

- Fresh independent read-only review of the final publication/build/permission receipt by native GPT `gpt_reviewer` (OpenAI Terra): PASS, no P1/P2/P3 findings. Artifact and whitespace validation passed. This receipt update is documentation-only and does not replace the pending live tests.


### Mac foreground-cache correction

- Authority: accepted `intent.md` requires accurate live target binding and cancellation on focus loss. The supervised test exposed a native correctness defect; repair is within that accepted safety scope. Keep the old Mac binary out of live input tests until correction is validated.
- Observed: packaged native readiness passed, but two manual Roblox binding attempts failed. A read-only host probe first recognized Roblox in all 12 stable samples. After switching away, a persistent backend remained `is_roblox=True` in 15 samples while fresh-process queries returned false. No game input was sent. Stale UI handles were also observed after the permissions restart; reopening restored a running application, while Tk form controls still lack accessibility elements.
- Diagnosis: `NSWorkspace.frontmostApplication` can remain cached without a serviced Cocoa main run loop; Tk and the engine worker cannot rely on that property updating. Apple documents main-run-loop caching of changing application properties: [NSRunningApplication](https://developer.apple.com/documentation/appkit/nsrunningapplication?language=objc).
- Correction: query the current native process with ApplicationServices `GetFrontProcess` and `GetProcessPID`, then resolve only fixed identity fields using `NSRunningApplication.runningApplicationWithProcessIdentifier_`. Do not fall back to cached focus. Native errors or missing APIs fail closed. These Process Manager functions are deprecated Apple APIs; their availability is a bounded prototype compatibility dependency and must be checked on both Mac build targets.
- Ownership: native GPT `gpt_worker` (OpenAI Terra) owns only `src/afk_grinder/backends/macos.py` and `tests/test_backends.py`; controller owns documentation, integration, validation, GitHub state, and supervised tests. Fresh read-only reviewer gets only the exact secret-free correction and evidence. No account information or game screenshots are delegated; GLM unused.
- Acceptance: changing foreground PID is recognized by the same backend across repeated calls and worker-thread reads; stale workspace state is never consulted; native failures/missing identity fail closed; permission/Escape/release tests remain green. Validate headless tests, GUI fake-input smoke, compilation, packaged diagnostics, native focus transitions without input, and Windows/both Mac CI builds before resuming supervised movement tests. Movement, actual focus-loss cancellation with held input, Escape, and held-key cleanup remain PENDING.

- Replacement native probe: the owner confirmed two manual switches. Across one persistent process, direct foreground lookup changed false → true → false for Roblox while cached NSWorkspace remained false. Native statuses were zero in all 24 samples. Fresh-process comparisons agreed in stable samples; one boundary sample differed because the sequential queries straddled a switch. This validates read-only focus transitions, not movement or live cancellation.

- Correction validation: 43 unit tests PASS, 8 fake-input GUI tests PASS, compilation and intent/spec/plan validators PASS, whitespace PASS, candidate Gitleaks scan (11.90 MB) no leaks. Rebuilt local Mac arm64 bundle PASS; packaged dry run, no-input GUI startup, and native readiness each returned 0; deep strict code-signature verification PASS. Actual corrected backend read native focus successfully 10/10 times from a background thread without input.
- Fresh independent read-only correction review by native GPT `gpt_reviewer` (OpenAI Terra): PASS, no actionable P1/P2/P3. Native GPT `gpt_worker` (OpenAI Terra) produced the adapter/test change; controller GPT/Sol integrated and validated. GLM unused, no contact/fallback. Old Mac GUI was closed before replacement. Windows/both-Mac CI, verified replacement artifact, and supervised live movement/focus-loss/Escape/cleanup remain open.

- Fix committed/pushed as `76c3efbfcb7e846762602577769f2760d4d4991d`. [Run 39363752157](https://github.com/hypler-dev/afk-grinder/actions/runs/39363752157) passed Windows x64 and both Mac jobs. All three corrected artifact records are unexpired: Windows `12238546451`, Mac Intel `12238845530`, Mac Apple Silicon `12239015107`. All-history Gitleaks scan: eight commits, 209.46 KB, no leaks.
- Downloaded the corrected arm64 CI artifact. Outer checksums and exact source/architecture metadata PASS; archive SHA-256 `ff6318eb4f4f3d26e87a6fce3d58b876c187bcb8b0a6847ca49e12875c194515`. Extracted metadata matches, Mach-O arm64 and executable mode verified, 23 internal symlinks preserved, deep strict signature verification PASS. The old temporary app was preserved outside the repository for rollback.
- Multiple local bundles shared `com.hypler.afkgrinder`, causing a launch to choose the local `dist` copy. Closed it and opened the exact CI app directly in Finder; the running executable path was verified as `/private/tmp/afk-grinder-live-test/AFKGrinder.app/Contents/MacOS/AFKGrinder`. The CI app visibly bound the Roblox player successfully. This is binding proof, not movement or live-cancellation proof.
- The corrected unsigned build required renewed OS trust. The owner explicitly authorized granting both permissions and replacing both old trust entries, and performed administrator authentication manually. Accessibility and Input Monitoring entries were refreshed through System Settings; no credentials were entered into the application or chat. The reopened CI app awaits its first movement test; no live-game PASS is claimed here.

- Final receipt/procedure review found one P2: Finder launch alone does not prove the tested app is the verified artifact when bundle identifiers collide. The Mac procedure now requires exactly one running executable, exact artifact-path comparison, and source metadata matched to the selected successful run before live input. Fresh independent follow-up review by native GPT `gpt_reviewer` (OpenAI Terra): PASS, no remaining P1/P2/P3 findings.

- Latest supervised-test snapshot: the exact corrected CI app is running, Roblox is bound, and no completed live run appears in the UI log. The owner has been asked to refresh readiness and run the default short movement sequence. Movement, live focus-loss cancellation, physical Escape cancellation, and live held-key cleanup are still PENDING; read-only native focus transitions and binding have been verified separately. No unrelated working-tree changes, signing credentials, login automation, purchases, trades, deployment, or public binary release were involved.


## BUILD.md application development — October 20, 2026

Authority: accepted intent.md and the owner-supplied BUILD.md. The owner explicitly requested updating the application from this document, free/open-source with an appropriate license and liability disclaimer. The earlier prototype evidence above remains historical; it does not prove the new roadmap complete.

### Outcome and milestones

| Milestone | Required outcome | Current acceptance |
| --- | --- | --- |
| 0 | Preserve baseline; pin/load/package MaaFw; dependency/license inventory | In progress |
| 1 | Window-only capture/calibration and tested coordinate/layout invalidation; no input | Pending |
| 2 | Restricted packs, local recognition, held-out labeled fixture/state evaluation | Pending |
| 3 | One verified indoor care task with guarded action/outcome/cancellation evidence | Pending |
| 4 | Additional independently verified indoor tasks and bounded recovery | Pending |
| 5 | Curated signed pack update provenance, validation, rollback | Pending |
| 6 | Opt-in longer sessions after native soak/performance evidence | Pending |
| Later | Verified location navigation, other games, optional companion | Game-library design opened by owner; other-game automation and companion remain deferred |

The full goal remains active until the accepted roadmap is implemented and proved at its stated scope. Native Roblox movement/Escape/held-key proof from the earlier supervised attempt remains pending; never infer it from CI or read-only focus probes. No new live game input is authorized by a timer or recognition result alone. No purchases, trades, credentials, injection, shell routines, or arbitrary plugins.

### Current execution and ownership

- Controller GPT/Sol (OpenAI) owns architecture, licensing/privacy judgment, intent/spec/plan, project/dependency metadata, build integration, validation, commits and GitHub state.
- Read-only native GPT `gpt_reader` (OpenAI Luna) extracts exact blueprint requirements and dependency metadata from secret-free named snapshots.
- Bounded SDK worker ownership: recognition adapter package and its tests only. Native GPT `gpt_worker` returned `Selected model is at capacity. Please try a different model.` on initial contact and one bounded retry; controller takes implementation. No GLM/Spark fallback or external secret transfer.
- Current files: BUILD.md, LICENSE, THIRD_PARTY_NOTICES.md, legal/dependency notices, pyproject.toml/uv.lock, lazy recognition adapter/tests, CLI/build/package helpers and exact tests/workflow, plus intent/spec/plan/README. Capture, coordinates, pack and session paths will be declared before their implementation milestones.
- Initial SDK: official MaaFw 5.14.3, upstream tag v5.14.3 at `8963191215ca49d6b037802acd07d20a4213160a`, official Windows x64 and both macOS 13+ architecture wheels observed. This is package availability evidence, not supported minimum OS/hardware proof. Native package contents and license obligations are being audited before distribution.
- License decision: unchanged standard MIT text for AFK Grinder's original code/documentation. It allows commercial redistribution as well as free use. MaaFramework remains LGPL-3.0; third-party assets and libraries are not relicensed. No claim that any disclaimer overrides mandatory law.
- Validation: preserve all 43 baseline safety/package tests and eight fake-input GUI checks; add meaningful SDK lifecycle/privacy/cancellation/version tests; verify source/wheel/frozen legal contents, pinned SDK native smoke, CI on Windows x64/Mac arm64/x64, and fresh independent review. No source-only test may close native game or calibration/recognition gates.

### SDK and coordinate foundation evidence

- The owner-supplied BUILD.md is preserved byte-for-byte. Original project code/documentation now use standard MIT; README explains the disclaimer's limits. A wheel/source build succeeds; wheel metadata reports `License-Expression: MIT` and retains 99 legal files. Ninety-five upstream notice-file hashes match `licenses/provenance.json`, including 89 MaaDeps archive notices. These notices are an inventory, not proof of SDK-bearing distribution readiness.
- MaaFw 5.14.3 source and frozen SDK diagnostics pass on the current Apple Silicon host: installed/native version match, CPU resource accepted, two-frame cache, persistent log/image/debug options disabled, synthetic 2×2 custom controller bound, input/shell/app callbacks disabled, cancellation passed. Whole native lifecycle runs in a disposable child with a 15-second deadline. No screen capture or OS input occurred.
- The first stdout-based diagnostic design was replaced with private temporary status-file IPC for Windows windowed executables. Tests cover absent standard streams, malformed/oversized status, missing optional modules despite retained distribution metadata, version mismatch, rejected privacy settings and native-job timeout. No pixels are stored in status files.
- Downloadable builds still exclude recognition implementation/native libraries. CI is configured to build/check the SDK privately, then rebuild the original input prototype before packaging. The artifact gate checks frozen CArchive/PYZ indexes, adjacent ZIP contents and filesystem/native-library paths. Harmless version/license metadata may remain. Actual SDK-free Mac archive packaging passes with its frozen module inventory checked. SDK corresponding-source/replacement and all-platform notice gates remain open.
- The coordinate layer separates reference, physical capture and native input units; tests cover Retina/fractional scale, negative origins, aspect mismatch, invalid buffers, stale/future/out-of-order frames, late callbacks, and target/window/bounds/monitor/scale invalidation. Calibration is cleared after a failed frame. This has no input path and is not gameplay/anchor calibration acceptance.
- Current full source suite: 78 tests pass, including eight separately implemented native-capture fake tests still awaiting independent review. Existing eight fake-input GUI tests pass. Compilation, actionlint, project artifact validation and whitespace checks pass for the foundation files; unchanged upstream notice whitespace is preserved. Mac SDK diagnostic and SDK-free packaged dry run/UI/native readiness pass. New all-target CI is pending push.
- SDK boundary fresh independent read-only review by native GPT/Sol (OpenAI): PASS. Terra implementation returned capacity errors twice and Terra review once; a separate native GPT/Sol reviewer handles integration. No GLM contact, Spark fallback, account data or screenshots were transferred. A review finding expanded the publication guard from filesystem-only checks to embedded Python module indexes.
- Related work in progress: separate native GPT/Sol fallback worker owns `src/afk_grinder/capture/{__init__,macos,windows}.py` and `tests/test_capture_backends.py`; fresh read-only capture review is pending. Mac raw-window previews are explicitly unverified content bounds; Windows uses client-only PrintWindow. Neither has native hardware/capture acceptance yet. No capture UI, task packs, care actions, signed updates or longer sessions are enabled by this foundation.
- Foundation integration review: fresh native GPT/Sol read-only reviewer reports PASS, no P1/P2/P3 after the embedded-module guard fix; independently inspected the real Mac bundle's 230-module frozen index with no Maa implementation. The separate capture review identified explicit SCK output sizing and per-pixel conversion memory issues; those uncommitted capture files remain with their worker for repair and follow-up review, outside the foundation commit.
- Foundation committed/pushed as `dd767bbe993ba361d17f5428dab329333e8c080c`. GitHub confirms public visibility and MIT detection. [Run 39393844904](https://github.com/hypler-dev/afk-grinder/actions/runs/39393844904) passed both Mac targets, including source/frozen SDK diagnostics, SDK-free rebuild and artifact upload. Windows stopped at a test fixture comparing CRLF bytes against an LF literal; no Windows SDK check or artifact upload ran. The correction compares archived bytes with original source bytes and adds `.gitattributes` plus a 95-notice hash test to prevent checkout normalization of upstream texts. A fresh all-target run is required; no Windows success is claimed from the first run.

### All-platform SDK foundation receipt

- The newline/notice correction was committed and pushed as `8d3641cd2ef7631fe0d89b8c115b826f8532b761`. [Run 39394583486](https://github.com/hypler-dev/afk-grinder/actions/runs/39394583486) passed Windows x64, macOS arm64, and macOS x64, including source/frozen SDK diagnostics, SDK-free rebuild, packaged checks, and test-artifact uploads.
- All three artifacts were downloaded and inspected. Outer checksums, exact embedded/external source metadata, architecture, root MIT license, all 95 notice hashes, Mac executable modes, and frozen module inventories passed. No Maa/MaaAgentBinary implementation was present. Artifact IDs: Windows `12251670754`, Mac arm64 `12251630966`, Mac x64 `12250868681`; these are retained test bundles, not installers or signed releases.
- Archive SHA-256: Windows `f04630d02388da3600a7aefd890bfe0c74fadd1d01a53f43911923e88f4c19ba`; Mac arm64 `53fbb74de60294fd494ad9aba6d0eb9a5c22f16fce1d6709818680f4ccd919cf`; Mac x64 `a0f54c7e6deaa36b063bc548dea3e6c2de618aa76ab4bcd23942155c5432d96e`. Local receipt: `/private/tmp/afk-grinder-foundation-ci-39394583486/VERIFICATION.json` (temporary, not source-controlled).

### Capture, pack, and launcher work in progress

- Scope: no-input native preview/capture service and strict local resource-pack validation. The owner additionally accepted a dark violet/cyan launcher with bold game previews/cards and multiple game workspaces; [docs/UI_DESIGN.md](docs/UI_DESIGN.md) records that design. It is a separate offline HTML deliverable, not an implemented native shell. Adopt Me remains the first input-check profile; other cards remain explicitly unsupported.
- Capture adapter producer: native GPT/Sol fallback; fresh native GPT `gpt_reviewer` (OpenAI Terra xhigh) review passed after explicit SCK output-size and conversion-memory repairs. Thirteen fake native-adapter tests pass. No actual window capture or calibration acceptance is claimed.
- Native preview producer: `gpt_worker` (OpenAI Terra high), controller service/integration: GPT/Sol. Review found synchronous process startup and non-atomic queued-frame discard; fixes move startup off Tk and serialize result publication/cancellation. Twelve service checks include blocked startup, late child cleanup, queued/late result disposal, malformed IPC, and deadline behavior. A closed child gate prevents native work until the parent has a signalable handle; expired/ungranted workers exit before importing native APIs. OS process-creation stalls may delay bootstrap cleanup, not authorize native work. A real spawned SDK service check passes with synthetic pixels only. Fresh `gpt_reviewer` (OpenAI Terra xhigh) follow-up PASS, no P1/P2/P3 findings.
- Restricted pack producer: `gpt_worker` (OpenAI Terra high); fresh `gpt_reviewer` (OpenAI Terra xhigh) final review PASS after bounded-file, pinned-root, numeric-overflow and PNG-validation fixes. Fourteen pack checks pass. Loader has no recognition/input/update path; held-out fixtures and signed pack distribution remain open.
- Native GUI evidence: ten fake-input integration checks and eight fake-frame Recognition Setup checks pass. CI now runs both GUI suites. Local Mac arm64 SDK-free and private SDK-bearing builds pass; their frozen checks include actual spawned SDK-service/gate/pipe startup in the no-input UI smoke. The SDK-free smoke accepts only the exact optional-SDK-absent result; unexpected errors and early close fail. No capture or game input occurs. The default SDK-free bundle was restored after private verification. New all-target CI remains pending; the successful `8d3641c` artifacts above predate this native preview integration.
- Final source validation at this snapshot: 110 unit checks pass, compilation passes, and tracked plus explicitly checked untracked text has no whitespace errors. Native capture, calibration anchors, held-out game fixtures, actual Roblox movement/focus-loss/Escape cleanup, signed pack updates, and longer-session gates remain open.
- Privacy gate: host read-only preflight found one Roblox player and no Screen Recording grant. No permission prompt, game screenshot, diagnostic file, native input, or account-data transfer occurred. Existing Accessibility/Input Monitoring grants do not establish the new capture permission.
- Launcher producer: `gpt_worker` (OpenAI Terra high). Three original 1672×941 covers were generated using built-in image generation, inspected, and copied byte-for-byte; exact prompts and paths are in `docs/design/asset-prompts.txt`. No official game artwork, game captures, or children's photos were used. Fresh independent `gpt_ui_review` (OpenAI Terra xhigh) final PASS after dry/live readiness, focus-recovery, per-run acknowledgment, AA contrast, shortcut, reflow and ARIA repairs; no P1/P2/P3 findings. The owner accepted the direction; the reviewed design artifact is implemented, while native launcher integration remains pending.
- Root launcher browser QA passes: initial dry run without setup; supported live arming; consumed acknowledgment blocks immediate restart; focus loss clears setup and fresh binding/preview/access/ack recovers; cleanup latch survives changing games; unsupported profile Start remains disabled; Cmd+. stops and Cmd+, opens Settings. Logical 620×450 and 320×450 layouts have no horizontal content overflow and both global Stop controls fit. A 1240×900 screenshot is retained at `docs/design/library-dark.jpg`; temporary browser viewport overrides were reset. HTML/JavaScript syntax and untracked text whitespace checks pass. This is design QA, not native assistive-technology or gameplay proof.
- Other-provider UI review routing was checked against official Z.AI documentation, but the pinned resolver stopped with `glm-secure: registry timestamp stale/future`. No GLM payload or provider contact occurred; no model/registry was changed. Native independent review is the fallback. No Spark lane was used.
- New Mac ScreenCaptureKit/CoreMedia 12.2.2 bindings identify MIT. Their pinned upstream notices were fetched independently and byte-match the retained common PyObjC notice; [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) records the hash. The actual restored default Mac bundle passes the SDK publication guard. SDK-bearing output remains private and was overwritten after diagnosis.

### Changed paths for this slice

```text
.github/workflows/build.yml
README.md
intent.md
plan.md
spec.md
pyproject.toml
uv.lock
docs/DEPENDENCIES.md
docs/UI_DESIGN.md
docs/design/index.html
docs/design/library-dark.jpg
docs/design/asset-prompts.txt
docs/design/assets/pet-world.png
docs/design/assets/bee-fields.png
docs/design/assets/ocean-adventure.png
src/afk_grinder/__main__.py
src/afk_grinder/ui.py
src/afk_grinder/ui_recognition.py
src/afk_grinder/capture/__init__.py
src/afk_grinder/capture/macos.py
src/afk_grinder/capture/windows.py
src/afk_grinder/capture/service.py
src/afk_grinder/recognition/packs.py
tests/test_capture_backends.py
tests/test_capture_service.py
tests/test_packs.py
tools/build.py
tools/smoke_ui.py
tools/smoke_recognition_ui.py
```

No unrelated working-tree changes observed. Generated `.venv/`, `build/`, `dist/`, and prior downloaded test artifacts remain outside the source slice. No login automation, account-data transfer, native game input, Screen Recording permission grant, diagnostic screenshot file, signing credential, deploy, or public binary release occurred.

### Windows compatibility correction after the preview slice

- The reviewed preview/pack/launcher slice was committed and pushed as `8a2da0dbf356ad11a014f34c78023a9e0ca706d5`. [Run 39401623984](https://github.com/hypler-dev/afk-grinder/actions/runs/39401623984) passed both Mac targets, including the new spawned SDK-service and fake-preview checks. Mac artifact IDs: arm64 `12253719903`, x64 `12255600111`. Windows stopped in unit tests and produced no artifact; the full run failed.
- Sol diagnosed two Windows pack-reader defects against the failed job and Python's documented Windows behavior: cached [DirEntry.stat()](https://docs.python.org/3.12/library/os.html#os.DirEntry.stat) returns zero link metadata, and CRT text-mode [os.open](https://docs.python.org/3.12/library/os.html#os.open) changes PNG CRLF/`0x1A` bytes. Fresh no-follow `os.stat()` and `O_BINARY` preserve strict link checks and exact binary bytes. Forced-fallback regressions cover valid packs, genuine hardlink rejection and binary payload preservation.
- A separate test assumed an Event timeout and the monotonic parent deadline expired on the same clock tick. The child still received no native-work grant; the test now expires the parent deadline explicitly before asserting its result, removing that timing assumption without changing runtime gates.
- Producer: `gpt_worker` (OpenAI Terra high) for pack code/tests, GPT/Sol for diagnosis and the timer assertion. Fresh independent `gpt_reviewer` (OpenAI Terra xhigh) PASS, no P1/P2/P3. Pack tests: 16 PASS; capture-service tests: 12 PASS; full source suite before the separate M1 bridge: 112 PASS. A new Windows/Mac run is required before this correction is accepted across platforms.
- The separate M1 capture-to-geometry bridge and M0 SDK-inventory work remain outside this corrective commit. No native game input, capture permission change, production release, or deploy occurred.
