<!-- intent-driven-delivery:plan:v1 -->
# Plan: AFK Grinder desktop application

Status: accepted
Authority: [intent.md](intent.md)
Owner: Jeff / hypler-dev
Last updated: 2026-10-20

## Current checkpoint

Source `e59450857fceec52ce7317a370dca8c3b95dac50` is the current verified CI candidate. GitHub Actions [run 39472952279](https://github.com/hypler-dev/afk-grinder/actions/runs/39472952279) passed all three Windows x64/macOS Apple Silicon/Intel jobs on the first attempt; all six artifact records were downloaded and statically verified. The old `13fa083` app was closed and preserved for rollback. The owner authorized all three exact-build permission updates; only AFK Grinder entries were removed/re-added, all three switches were observed enabled, and the exact app was reopened without an administrator prompt. Its UI reported native checks ready and automatic unique-window binding. Explicit Capture then failed at `window_count`; a foreground retry failed at the same selection stage. Roblox was manually reconnected to clear Adopt Me gameplay; the controller observed clear gameplay, but no input workflow was started. Native capture remains unaccepted; gameplay movement/cancellation, installer, and assistive-technology acceptance remain open.

Earlier source `fa3bc7aa9ecd200795861f1f1a079e7c83440fd0`, included in `e594508`, adds an offline state-inspector foundation using supplied scores only. [Run 39428783690](https://github.com/hypler-dev/afk-grinder/actions/runs/39428783690) passed all three platforms after one Windows-only retry of an unchanged Node formatter test timeout. It has no launcher or input integration. Native and game-fixture acceptance remain open.

## Scope and protected lanes

Preserve the bounded local input prototype and develop the adopted BUILD.md roadmap incrementally. Public repository visibility/topics, the original README banner, commit/push and automated test artifacts remain authorized. Native gameplay tests remain short and supervised after manual login. Credential access, transactions, injection, signed/public GitHub release publication and mobile implementation are excluded. Longer sessions require the blueprint's endurance evidence; network pack updates require its curated signature/provenance gates.

The current pre-capture packet adds the BUILD.md state-inspector foundation only: pure interpretation of supplied anchor scores against validated pack states, explicit missing/conflicting evidence, caller-supplied monotonic time with a 0.5-second freshness bound, observation identity and bounded stability. Inspector/history must retain only metadata, never observations or pixels. It adds no matcher, game fixtures, SDK pipeline, UI/bridge command, care action or live enablement. Terra owns the new inspector module and its tests; Sol owns contract, integration, diagnostics and review resolution. Meaningful acceptance is synthetic coverage of missing versus evaluated-negative evidence, strict score validation, exclusion precedence, ambiguity, stability reset, stale/replayed frames, layout changes and no pixel retention, followed by independent read-only review and existing regression checks. The staged native test candidate remains `13fa083`; source-only recognition work must not replace it or invalidate its pending permission request.

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
| 1 | Window-only capture/calibration and tested coordinate/layout invalidation; no input | In progress; geometry UI implemented, native capture/anchor acceptance pending |
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

### Windows correction verification and Mac preview diagnosis

- Correction `0fd7d29d08f6098e8f3d85ec3e29625f74b23d66` passed all three jobs in [run 39402685675](https://github.com/hypler-dev/afk-grinder/actions/runs/39402685675), including private SDK/source checks, frozen startup, fake GUI checks and SDK-free packaging. Downloaded Windows x64 (`12256591102`), Mac arm64 (`12256231280`) and Mac x64 (`12255686646`) artifacts. Outer hashes, exact embedded/external source metadata, architecture, Mac executable modes, all 95 retained notice hashes and the SDK-exclusion guard pass. Mac arm64 deep strict ad-hoc signature verification passes. These are CI test binaries; native gameplay remains unverified.

```text
a1a3aac5956878db402058e238a6c7df22e94689176f47da78d45090be4f142f  AFKGrinder-windows-x64.zip
e5aa3bc15c360df9b95483688af8195459ed89f36d3288ab326b61fc166c8869  AFKGrinder-macos-arm64.tar.gz
c192416a7f65034a65d93a1dbdad94b5cc174f7b5c9c862c4142edf8bf21a613  AFKGrinder-macos-x64.tar.gz
```

- The owner authorized Screen Recording for the verified `8a2da0d` Mac arm64 test app and completed administrator authentication manually. System Settings showed the grant enabled. Its restart selected a different local bundle with the same identifier; that copy was closed, and the exact CI executable path was verified before testing. The owner manually bound Roblox successfully. Capture then failed with the generic error and no visible preview. This is not a capture pass, and no game input was sent.
- Sol reproduced two native conversion defects using synthetic 2×2 images without ScreenCaptureKit or screen access: `CGBitmapContextGetData` returns an `objc.varlist`, which rejects the ctypes/buffer fallback; explicitly releasing its PyObjC-owned context causes a later garbage-collection crash (exit 139). The repair copies its bounded [`as_buffer`](https://pyobjc.readthedocs.io/en/latest/api/module-objc.html#objc.varlist.as_buffer) view while the context is alive and leaves [reference management](https://pyobjc.readthedocs.io/en/latest/core/intro.html#reference-counting) to PyObjC. A subprocess regression requires exact red/blue BGR output and clean exit after 40 conversions and forced garbage collection. This repair passes locally; its real window-capture acceptance remains open.
- A discarded mixed source/frozen multiprocessing diagnostic failed in interpreter bootstrap before capture. It is not evidence about the ScreenCaptureKit backend. No game pixels were saved or included in diagnostics, reviews or repository contents.

### M0 static SDK bundle inventory

- Added `tools/inventory_build.py` and six fake-bundle tests. `sdk-inventory.v2` records embedded modules, unique native contents and their internal aliases, executable and legal-file hashes, with bundle-relative paths. It recognizes Windows DLL/PYD/PE and Mac dylib/extensionless Mach-O payloads. Escaping, broken, self-referential and directory-cycle links fail closed; MaaAgentBinary remains forbidden. The tool neither imports nor executes bundle code.
- A private local Mac arm64 build passed frozen SDK, spawned SDK-service, dry-run UI and native-readiness smoke checks. Its diagnostic inventory reported 495 embedded modules, 54 unique native contents and 226 logical legal-file paths including aliases. This was a dirty development checkout, not an exact-revision distribution receipt. The default SDK-free bundle was then rebuilt and passed the SDK publication guard.
- CI now records the inventory after private SDK verification and uploads JSON separately from the SDK-free test archive. `actionlint` passes. New exact-revision Windows/both-Mac inventory artifacts remain pending until the next run; existing `0fd7d29` test artifacts predate this tool.
- Producer: native `gpt_worker` (OpenAI Terra high), with Sol owning CI integration and validation. Fresh independent `gpt_reviewer` (OpenAI Terra xhigh) final PASS after a P3 self-link traceback was converted to a clean rejection; six targeted tests, compilation and whitespace checks pass. No GLM contact occurred; the previously recorded stale/future registry gate remains unchanged. No SDK-bearing binaries, game images, credentials or public release were uploaded. Corresponding-source, replacement, attribution and final distribution-review gates remain open in [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md).

### Corrected capture and SDK inventory CI receipt

- Reviewed fixes were pushed as `b3bd472` (Mac bridge ownership) and `71c2809e6851d4c8ad8332756072ec63f7c40111` (SDK inventory). [Run 39406697042](https://github.com/hypler-dev/afk-grinder/actions/runs/39406697042) passed all three targets. Both Macs passed the real-Quartz synthetic conversion/cleanup regression; Windows skips that Mac-only test. No real screen capture or game input runs in CI.
- Downloaded and verified all three SDK-free application artifacts and the three separate `sdk-inventory.v2` JSON artifacts against exact source/labels. Application metadata/hashes, architecture, all 95 notice hashes, SDK-exclusion guard and Mac executable modes pass; arm64 deep strict ad-hoc signature verification passes. Local verification receipt: `/private/tmp/afk-grinder-ci-39406697042/VERIFICATION.json` (temporary).

| Target | Application artifact | SDK JSON artifact | Modules / unique native contents / logical legal paths |
| --- | --- | --- | --- |
| Windows x64 | `12257612285` | `12257247386` | 412 / 109 / 111 |
| Mac arm64 | `12257182593` | `12257052568` | 493 / 106 / 226 |
| Mac x64 | `12257092578` | `12257132654` | 493 / 106 / 226 |

```text
dacccaddd43aad57ced6984d0a813cf07cb8cfac601cbfd0b08c5abd5b8e8688  AFKGrinder-windows-x64.zip
ba500607fd69a4fc74fe27754a0ce525e554da71c88572eaff40f787b460476e  AFKGrinder-macos-arm64.tar.gz
95b2bbac74e6b0af97fc3b65547a20334fb6de7dc42869856f7752c402b6b625  AFKGrinder-macos-x64.tar.gz
```

- These static SDK inventories identify actual frozen contents; they do not map every native component to complete corresponding source or prove library replacement. SDK-bearing application publication remains blocked. The corrected application artifacts precede the separate M1 ROI changes below.

### M1 reference geometry and editable preview

- Added a no-input capture-to-layout bridge that keeps display DPI separate from measured physical/native conversion. Four new bridge checks and eight observation checks cover Windows 150% DPI with 1:1 native pixels, Mac Retina 2:1/negative origins, raw-window uncertainty and DPI-only/layout invalidation. Fresh independent `gpt_reviewer` (OpenAI Terra xhigh) final PASS; an existing invalid-scale regression was retained after a review finding.
- Native Recognition Setup adds image-bounded 16:9 area selection, keyboard initialization/movement/resize/reset and fresh matching-layout recapture before snapshot geometry is accepted. A historical image remains editable, while expired observation/calibration cannot remain current. Mac raw-window uncertainty survives the check; anchors and targets remain explicitly unconfigured. This is geometry-reference evidence, not gameplay calibration or input authorization.
- Producer: `gpt_worker` (OpenAI Terra high), separate bounded `gpt_ui_design` direction, and Sol integration. Fresh `gpt_ui_review` (OpenAI Terra xhigh) found human selection incorrectly constrained to 0.5 seconds, missing keyboard initialization, contradictory historical-state copy and an unusably small minimum-size preview. All were repaired; final independent review PASS, no P1/P2/P3. Root validation: 123 unit tests, 10 input-GUI and 12 recognition-GUI checks pass; compilation, actionlint and whitespace pass. The minimum-window check now covers all controls/status labels and at least 96 pixels of preview height at 440×560 with a historical raw-Mac snapshot and long safe error. The rebuilt SDK-free local app passes frozen dry run, spawned-service UI, native readiness and deep strict ad-hoc signature verification. Exact-revision M1 CI and native capture/anchor acceptance remain pending.
- This M1 slice owns exactly `plan.md`, `spec.md`, `src/afk_grinder/recognition/observation.py`, `src/afk_grinder/recognition/frame_geometry.py`, `src/afk_grinder/ui_recognition.py`, `tests/test_observation.py`, `tests/test_frame_geometry.py` and `tools/smoke_recognition_ui.py`. No unrelated dirt observed. Input remains stopped; no credentials, native game input, saved game pixels, transactions, SDK-bearing binary upload, signing credentials, deploy or public binary release occurred. The earlier owner-approved Screen Recording grant is recorded separately above.
- M2 research only: an isolated local MaaFw `JTemplateMatch` probe matched an original synthetic 32×24 pattern at expected box `(400, 180, 32, 24)`, score `0.999999`, using an in-memory 1280×720 BGR frame, CPU resource and a controller whose input/shell/app callbacks all reject. The first empty-pipeline-directory bundle failed; pinned upstream `PipelineResMgr` requires at least one JSON file, and an engine-owned empty JSON object resolved loading. The outer child deadline was 15 seconds; persistent SDK logs/images were disabled and the private synthetic template directory was deleted. This is not production recognition integration, held-out fixture evaluation, game-state or care-task proof.

### M1 exact-revision CI and supervised retest receipt

- The reviewed geometry/UI slice was committed and pushed as `53cab75b2bb4f9c9a452bff8ad8de06a22da317a`. [Run 39407605583](https://github.com/hypler-dev/afk-grinder/actions/runs/39407605583) passed Windows x64 and both Macs, including the expanded minimum-size/keyboard/historical-preview GUI checks, private SDK smoke/inventory, SDK-free rebuild and frozen checks. All six application/JSON artifacts were downloaded. Exact metadata, outer hashes, architecture, 95 notice hashes, SDK exclusion and Mac executable modes pass; both Mac bundles pass deep strict ad-hoc signature verification. Temporary receipt: `/private/tmp/afk-grinder-ci-39407605583/VERIFICATION.json`.

| Target | Application artifact | SDK JSON artifact | Modules / unique native contents / logical legal paths |
| --- | --- | --- | --- |
| Windows x64 | `12257842749` | `12258187283` | 414 / 109 / 111 |
| Mac arm64 | `12256884293` | `12257333825` | 495 / 106 / 226 |
| Mac x64 | `12257319420` | `12257199420` | 495 / 106 / 226 |

```text
ea06af2dd2fcc172e0cba7d4d9ab4749ece5c4416c3a4c1bd3d9dcbc73aedcfa  AFKGrinder-windows-x64.zip
ab68f0290363c753e3b11840a4fd761f7497fe7f42775f5fe8a9a8c282add8fd  AFKGrinder-macos-arm64.tar.gz
ff0cc8dc9df3304ed14b3d98cbfb2dab833ab9fd3da06609719781a181e7fa3a  AFKGrinder-macos-x64.tar.gz
```

- The old `8a2da0d` app was closed. Exactly one GUI process was verified at `/private/tmp/afk-grinder-ci-39407605583/AFKGrinder-macos-arm64-53cab75b2bb4f9c9a452bff8ad8de06a22da317a/extracted/AFKGrinder.app/Contents/MacOS/AFKGrinder`. The owner bound Roblox; the first corrected-build preview failed Screen Recording preflight because macOS did not carry the earlier unsigned build's trust forward. No capture pass is claimed from that attempt.
- The owner explicitly approved refreshing all three permissions for `53cab75`: Accessibility, Input Monitoring and Screen Recording. Old AFKGrinder entries were removed and the corrected app added; all three switches were observed enabled. Other applications' grants were untouched. The app was quit and relaunched from the exact verified Finder path rather than macOS's ambiguous bundle-identifier restart. A read-only `--check` on that executable returned 0 with native readiness passed. No credentials were entered by the agent. Restart cleared the binding; fresh binding and actual preview acceptance remain pending at this receipt snapshot. Input remains stopped; movement, live focus-loss/Escape cancellation and held-key cleanup remain unverified.
- Final source directory and 16-commit history Gitleaks scans found no leaks before this documentation receipt. No unrelated source dirt was present. SDK-bearing binaries, game images, credentials, transactions, signing credentials, deployment and public binary release remain excluded; the free/open-source roadmap goal remains active.


### Native game-library launcher and automatic binding

Authority remains `intent.md`; the owner requested automatic binding and adoption of the accepted dark launcher preview as the actual application interface. `docs/DESKTOP_BRIDGE.md` records the local contract. This slice does not establish native capture or gameplay acceptance.

- Ported the original violet/cyan game-card design and three byte-identical original covers into bundled HTML/CSS/JavaScript. Adopt Me exposes the short input check; Bee Swarm Simulator and Blox Fruits remain unsupported previews. Added Library, Session, Setup, Routines, Packs and Settings with actual Python state, persistent Stop, visible version/source/platform, keyboard controls, accessible statuses and optional historical physical-pixel reference editing. No simulation harness ships in the application.
- Added native target discovery without focus changes or a bind countdown. Unique verified targets select automatically; zero waits and multiple targets require explicit selection. Candidate IDs are opaque and not reused for replacements. Discovery never acknowledges, arms, starts or resumes input. Native permission checks and discovery run away from the UI thread; failed/stalled discovery invalidates live setup.
- The local pywebview 6.2.1 shell forces Cocoa/WebKit or Edge Chromium, loads bundled `file://` assets without an HTTP server, rejects navigation away from the entry point and restricts subresources through CSP. An explicit dispatch allowlist blocks dotted/private/native methods before the upstream attribute resolver. Only state, typed commands and a bounded in-memory preview are exposed. No credentials, remote content, fonts or telemetry were added.
- Stop/Close now invalidate a start ticket before pending engine readiness can finish, preventing a late start from clearing cancellation. The engine checks that ticket before/after readiness and throughout execution. Live attempts consume acknowledgment even when rejected; acknowledgment can be unchecked. Cleanup failure remains global. Unsupported profiles and active-input reference mutations are blocked in Python. Capture errors carry allowlisted reason/stage/type values without exception text, titles or paths.
- Final source validation passes 156 unit tests, including dispatch, pending-start cancellation, candidate identity, stale PNG and declared-notice regressions. Legacy fake-input GUI checks pass 10/10 and recognition GUI checks pass 12/12. The actual Mac WKWebView source and SDK-free frozen smoke both pass the real bridge roundtrip, canceled `about:blank` navigation and spawned synthetic SDK check, with the native input backend disabled and no screen capture. Frozen dry run and native readiness also return zero. The final terminal-phase ROI, hidden-state CSS, dispatch and announcement changes also passed a rebuilt Mac source/frozen smoke and deep strict ad-hoc signature check. Later static permission guidance and idle-Stop wording passed source tests; exact-revision CI remains pending. An initial adapter lookup error (`WindowHost` has no `webview`) was fixed by targeting the pinned Cocoa adapter instance; it is not capture evidence.
- Producer lanes: OpenAI Terra-high `gpt_worker` for discovery/controller/frontend/build, OpenAI Terra-high UI design, and Sol for shell, safety integration, license judgment and diagnosis. Fresh OpenAI Terra-xhigh read-only code/UI review found and prompted fixes for a Windows last-error ambiguity, Mac display-stage diagnostics, small-window Stop visibility, saved ROI edits, active-input ROI gating, hidden polling and stale PNG queue publication. Fresh independent UI and code/docs rereviews passed with no remaining P1/P2/P3. Exact-revision three-target CI remains pending. GLM was skipped before provider contact because `glm-secure: registry timestamp stale/future`; no requested/returned model or provider payload exists.
- Existing native capture still fails in the verified old `53cab75` app. The new diagnostic build has not yet received capture acceptance. Login remains manual, input stopped, and no native game input, saved game pixels, SDK-bearing upload, signing credentials, deploy or public release occurred in this slice.

- Native dirty-development UI observation: the launcher bound one verified Roblox player while the launcher itself remained foreground; no manual bind countdown or focus change occurred. The real 620×450 window retained a visible Stop. Dry run followed by Escape reached `stopped`; this verifies launcher cancellation only, not global Escape while Roblox is foreground or release of a real held game key. An explicit capture attempt returned `permission/preflight/capture_error` for the new unsigned app identity. No image was published or stored. No new permission grant was attempted; final capture testing will use an exact verified CI app to avoid another disposable trust refresh. Input permissions were visibly blocked in this launched app even though command-line `--check` had passed under its parent process; command-line readiness does not establish the independently launched app's trust.
- Root retained seven new dependency notice files (102 manifest entries total), including official WebView2 SDK LICENSE/NOTICE and CFFI's bundled Windows libffi source-header copyrights omitted by its wheel. New collector coverage retains metadata-declared pythonnet AUTHORS.md. The original MIT project license and SDK-bearing publication block remain unchanged. Source Gitleaks found no leaks. No unrelated dirt was observed; current changes belong to this launcher/binding/diagnostic slice.


### Launcher CI and preview freshness follow-up

- Committed/pushed launcher baseline `45a5286b18e80e7588f24cc5fc7871b06c57c08e`. [Run 39414439431](https://github.com/hypler-dev/afk-grinder/actions/runs/39414439431) passed both Mac targets, including real WebView source/frozen smoke, private SDK inventory, SDK-free packaging and uploads. Windows passed unit/compile checks but failed the new source launcher smoke: WebView2 was already disposed during evaluation. This is not three-platform acceptance; no corrected Windows launcher download is claimed. The initial HTTPS push failed with HTTP 400 and succeeded with per-command HTTP/1.1/post-buffer settings; no persistent Git settings, credentials or TLS verification changed.
- Fixed a separately reproduced preview bug: normal captures older than 0.5 seconds now remain editable historical references, with no current observation/calibration. Explicit reference checking still requires a fresh frame and exact layout. Polling expires matched geometry after 0.5 seconds while retaining reference pixels/area. New capture/check operations immediately change the preview ID and clear old pixels/layout, rejecting late PNG publication. Background discovery preserves existing candidate controls while refreshing; stalled discovery still fails closed after two seconds.
- Added smoke-only allowlisted startup failure codes to diagnose Windows without printing URLs, paths or native exception text. Navigation policy and bridge gates remain unchanged. The deliberate blocked-navigation smoke clears any earlier rejection before requiring its own cancellation, preventing a false pass.
- Follow-up validation: 161 unit tests pass; compilation and whitespace pass; real Mac source no-input WebView smoke passes. Fresh independent OpenAI Terra-xhigh code and UI reviews passed the historical-preview behavior; an additional fresh code review passed startup diagnostic privacy/strictness. Exact-revision CI for this correction and Windows diagnosis remain pending. Producer/integrator is Sol; no native game input, permission changes, saved game pixels, SDK-bearing upload or release occurred.

### Windows WebView document verification correction

- Follow-up commit `1a62fa6d3a3e0d869db21013faea680734329538` passed both Mac jobs in [run 39415755890](https://github.com/hypler-dev/afk-grinder/actions/runs/39415755890). Windows failed its source launcher smoke with the allowlisted diagnostic `blank_document (none)`. The cached WebView2 Source did not establish which document was executing; Windows acceptance remains open.
- The loaded callback now verifies the executing document through `window.location.href`, retaining the exact entry-URI check and closed bridge gate on failure. The blocked-navigation smoke attempts another bundled file rather than `about:blank`, then requires native rejection and the original executing document. No blank-document exception, URI normalization, remote access or navigation-policy relaxation was added. Smoke diagnostics classify rejected navigation without printing URLs or paths.
- The corrected real Mac source smoke passes the bridge roundtrip, native navigation rejection and spawned synthetic SDK service without OS input or screen capture. Fresh independent OpenAI Terra-xhigh read-only review passed this exact correction. Windows and exact-revision three-target CI remain pending. No permissions, credentials, game pixels, native game input, signing credentials or public release were involved.

### Launcher shutdown and observation cleanup races

- [Run 39417044502](https://github.com/hypler-dev/afk-grinder/actions/runs/39417044502), source `7d8583834773bef5fdbc2703980254fbdd5e76e6`, passed Mac arm64. Windows reached the real bridge and intentional navigation rejection, then a delayed loaded callback evaluated after WebView disposal and reported `blank_document_after_bridge`. Intel Mac reached the SDK service deadline and exposed concurrent parent pipe closure (`OSError: [Errno 9] Bad file descriptor`). Neither failure is capture or game-input evidence.
- The shell now marks closing before destruction and ignores loaded callbacks that finish during shutdown. A lifecycle lock prevents a late callback from reopening the bridge after Close. The real smoke waits for UI connectivity before starting the separately bounded 15-second SDK service, avoiding contention with cold WebView startup. Navigation remains exact-entry only; no failed document becomes trusted.
- Observation cancellation and normal read teardown now serialize closure of the shared parent reader. Deterministic regressions cover an in-flight document query completing during Close and simultaneous cancellation/read cleanup closing the reader once. Root validation passes 163 unit tests, compilation, whitespace and real Mac source bridge/navigation/spawned-service smoke without OS input or capture. The receipt below supersedes the earlier pending-review/CI status.

### Launcher CI and native autobind receipt

- Source `51eb15b4a131812e235e16add5a84acc843c08c4` passed all three jobs in [run 39417880800](https://github.com/hypler-dev/afk-grinder/actions/runs/39417880800). Windows x64 and Mac Apple Silicon/Intel application artifacts plus three separate SDK inventory JSON artifacts were downloaded and verified: exact metadata, archive hashes, architecture, 102 notice hashes, SDK exclusion, bundled frontend/art checks, Mac deep strict ad-hoc signatures and inventory labels/counts all passed. Windows source text was CRLF-normalized for source comparison only; its 102 notice hashes still passed exact-byte checks. SDK-bearing binaries were not uploaded.

| Target | Application archive SHA-256 | SDK inventory SHA-256 | Inventory counts (embedded / SDK modules / native / legal paths) |
| --- | --- | --- | --- |
| Windows x64 | `80c8f8ce1f9aee35603568d2b554e8b52878d44ed855b084bef4d114366a9096` | `a5072b739ad9cb8f3cee352cb93e84515fb02c65d59333166c070aed031f3531` | 505 / 677 / 122 / 126 |
| Mac Apple Silicon | `7c7365bd96cca3c104bbfb3d0ee402aebae9e31bf10e1730b2548ace2d4dbd6c` | `c405e44604ec3b550a8e1a422aeb2b5283e3b338b7063de5bddd5b6d27b37c66` | 391 / 558 / 109 / 248 |
| Mac Intel | `b56ac768851b7bd671c6c6a4eb6daabed9f2c756f2cb545a4807615020698d98` | `12a3d0283f05ec0294c3cea700e343b5aa36a5c23855f83891dacbf305c22844` | 391 / 558 / 109 / 248 |

- Fresh independent OpenAI Terra-xhigh read-only review passed exact cleanup-race range `7d85838..51eb15b`; no P1/P2/P3 findings. Final CI source was `51eb15b4a131812e235e16add5a84acc843c08c4`. Intel's first frozen `--ui-smoke` timed out after 30 seconds; one failed-job-only retry passed. The timeout remains a reliability observation, not a proven hosted-runner cause.
- Actual verified Mac app copied to `/private/tmp/afk-grinder-current/AFKGrinder.app`; executable hash matched. Native UI opened with title `0.2.0 · 51eb15b`, Settings showed full commit, and Setup auto-bound one unique Roblox target while launcher stayed foreground. Initial access was blocked. The owner explicitly approved refreshing all three permissions for this verified build; only old AFKGrinder entries were removed/replaced, and Accessibility, Input Monitoring and Screen Recording were observed enabled. The exact app was quit/reopened; its own UI now reports native readiness ready. A subsequent selected-window capture returned `unexpected at worker (unexpected)` with no preview published or saved. This is unresolved capture failure, not capture acceptance. A separate bounded source diagnostic stopped at denied Screen Recording preflight; it establishes no application capture result. No live game input was sent.
- Read-only scaling design is complete; bounded frontend implementation is in progress under the user's additional October 20 request. Documentation production used OpenAI Luna; Sol corrected the exact review range and retained the Intel retry limitation. No SDK-bearing upload, credentials, transactions, signing credentials, deployment or public release occurred.

### Launcher scaling and capture failure boundaries

- The owner additionally requested scaling. OpenAI Terra UI design and implementation retain the accepted violet/cyan game library, add responsive small-window controls/navigation and HiDPI preview drawing, and preserve source-pixel reference metadata through live-rectangle pointer conversion and redraws. Sol added the native Interface menu (100/125/150/175/200%) using UI-thread page zoom without extending the bridge or changing input state. Closing cancels pending zoom callbacks. Source-level Windows and Mac tests cover native scheduling and late Close.
- Fresh OpenAI Terra UI/a11y review prompted removal of global overflow masking, narrow Setup action wrapping, Interface-menu guidance and an AA primary-button text correction (4.72:1 default, 6.59:1 hover). Source review passed. Real native CUA testing then exposed a small-window 200% overflow that source review had missed: the one-column grid retained a minimum-content width. The grid now uses `minmax(0,1fr)` with shrinkable rail/navigation; the compact brand name is restored. The source native smoke now resizes to 640×450, checks actual 200% and 100% viewport widths, no horizontal overflow and header Stop visibility, then exercises navigation rejection. This exact source smoke passes; corrected frozen visual checks and exact-revision CI remain pending.
- Capture diagnosis remains open. Safe stages now distinguish parent IPC, child teardown, whole-worker deadline, launcher geometry and PNG encoding. Fresh independent code review found that real asynchronous encoding failures and outer deadlines still bypassed diagnostics; both were repaired. Encoder failure now clears pixels/layout/PNG/calibration, and late or stale callbacks remain rejected. Targeted regressions pass. No raw native exception text, paths, titles or images are added to diagnostics.
- Validation at this snapshot: 168 unit tests, compilation, JavaScript syntax and whitespace pass. The initial local SDK-free frozen scaling candidate passed dry run, real WebView/spawned service, default-window 200%/100% zoom, native readiness and deep strict signature checks before the narrow-grid correction. No permissions were granted to disposable scaling builds. The verified `51eb15b` app remains the last explicitly trusted test build; its capture failure is not resolved by these diagnostics. Roblox was observed at the Adopt Me welcome screen; two native CUA Play clicks produced no transition, so no movement workflow was started and fresh clear-gameplay confirmation is pending. No game images were saved or committed, and no transactions, account changes, signing credentials or public release occurred.
- Final local validation passes 170 unit tests, including cross-language diagnostic vocabulary and actual JavaScript formatter coverage for all five new stages plus rejection of unknown native details. Fresh code review caught that the frontend had omitted the new stages; this is corrected without exposing raw exceptions. Native source and rebuilt SDK-free frozen checks now pass all six launcher sections at 640×450 (200% and 100%), 960×700 (100%) and 1180×800 (100%), including real page-zoom ratios, horizontal-fit and Stop bounds. Frozen dry run/readiness and deep strict signature verification also pass. Real CUA observed a fully visible Stop at 640×450/200% after the grid correction; a subsequent Settings hash overflow prompted explicit long-value wrapping and the expanded six-section regression. Intermediate 761–1000 px layouts use one content column and two cards. Exact-revision CI and final review of the expanded matrix remain pending at this snapshot. All current dirt belongs to this scaling/diagnostic/CI-receipt slice.

### Scaling CI viewport correction

- Scaling source `a59a3feec3ee2b4530c28af12a31fc4da1a6e870` was committed/pushed after 170 tests and local source/frozen matrix checks passed. Fresh independent OpenAI Terra-xhigh code and UI reviews passed exact range `51eb15b..a59a3fe` with no remaining P1/P2/P3. [Run 39423028120](https://github.com/hypler-dev/afk-grinder/actions/runs/39423028120) passed both Macs. Windows passed the small/medium six-section and native-zoom checks but failed `interface_resize_1180` before upload. This is not Windows scaling acceptance.
- The smoke now reads the actual available host-screen width before requesting each window size and caps requests to that width. It retains actual resize, zoom ratio, all-section horizontal-fit and fully visible Stop assertions; unavailable bounds fail the test. Smoke-only numeric viewport evidence reports requested, available, target and actual widths so host limits can be distinguished from a layout defect. No application layout, native input, navigation/bridge policy or run limit is relaxed by this test correction. Exact-revision CI remains pending.
- Local source smoke passes with actual widths 640/960/1180 against the reported 3840 px host width; seven shell tests, compilation, whitespace and plan validation pass. Windows available-width evidence and the new exact-revision run remain pending; a display-limit cause is not yet established.
- Fresh independent read-only OpenAI Terra review found a P3 coverage gap in the display-bound correction. The smoke resize is now isolated for deterministic checks covering a 1180 px request capped to a 1024 px host with a 1008 px client, an unchanged request on a larger display, invalid/unavailable bounds, exact four-field numeric output and failure when the window does not reach its capped target. The layout, zoom and Stop gates are retained. All 174 tests, compilation, whitespace and plan validation pass; the actual no-input Mac source smoke also passes all three requested widths and the six-section scaling matrix. Follow-up independent review and final CI remain pending at this snapshot.
- Fresh review passed the display-bound correction and its four regression tests; `338d9c2` and `6f29704` were committed/pushed. In run 39424469805, Windows passed the source scaling matrix. The Apple Silicon source smoke printed all three viewport measurements and the final success message, then remained alive until the one-minute step timeout. Its 1180 px request was correctly capped to a reported 1024 px display. Pending bridge callbacks attempted replies after close. Inspection of pinned pywebview 6.2.1 identifies non-daemon utility threads and an unbounded Cocoa response semaphore as a shutdown hazard; this is distinct from layout failure. Only pywebview utility workers are now daemonized. The input runner remains non-daemon and the controller close gate continues to await cleanup. A subprocess regression uses the real pinned dispatcher with permanently blocked reply delivery and requires normal process exit; no forced exit or timeout waiver is introduced. New validation, review and exact-revision CI remain pending.
- Run 39424469805 completed with Windows and Intel successful and Apple Silicon failed on process shutdown after its source checks passed. Windows source and both frozen checks report requested/available/target/actual widths `640/1024/640/624`, `960/1024/960/944` and `1180/1024/1024/1008`; the hosted display bound and client border account for the earlier resize failure. The shutdown correction passes all 175 unit tests, compilation, whitespace and an actual Mac source smoke with normal exit. Independent review and a new exact-revision all-platform build remain required.

### Final launcher scaling and receipt

- Source `13fa0832b60021445a27b0d8c167e5a6ed7705f1` passed all 3 CI jobs in [run 39425375723](https://github.com/hypler-dev/afk-grinder/actions/runs/39425375723) on the first attempt. Local source validation passed 175 tests, compilation, Node/frontend checks, diff/whitespace checks, and the actual no-input native smoke. Its six-section matrix requests 640×450 at 200% and 100%, 960×700 at 100%, and 1180×800 at 100%, capping width to the available host display. The Interface menu also offers 125%, 150%, and 175%; these intermediate levels do not have full native matrix acceptance. CI source/frozen gates, packaged dry-run/readiness, and both Mac deep strict ad-hoc signature checks also passed. The downloaded artifacts and inventories were verified against `/private/tmp/afk-grinder-ci-39425375723/VERIFICATION.json`.
- Final artifact receipt:

| Target | Application archive SHA-256 | SDK inventory SHA-256 | Inventory counts (embedded / SDK modules / native / legal paths) |
| --- | --- | --- | --- |
| Windows x64 | `b185bfe69ae3281a8e90cbe5865b260e5544b9d89cf2fff4149af59dd97ff300` | `1fe30814028402f7ea0b421b154a710771aa89b80fe49af833273155cdbe5151` | 505 / 677 / 122 / 126 |
| Mac Apple Silicon | `8e6d21f8b09c1bd751c00e021e65af0f705652a1ec95be499d73bcad790b9db7` | `5fc5a837cb5e82b2472e1d50c8edea0d02f60a71da4afefef29eca64fb69909a` | 391 / 558 / 109 / 248 |
| Mac Intel | `50428059e0bfcc754f076e08151bc1e74b55c21c8adbbc248598fcc3f29d88e9` | `5afd6b773cb4bf05443375e83657239c42283c6308e5d41eec40d376592fc532` | 391 / 558 / 109 / 248 |

- The application bundles are SDK-free, carry 102 verified notices, retain the expected frontend/art/architecture metadata, and pass source/archive exclusion checks. SDK-bearing outputs remain private; no SDK-bearing upload occurred. Native captures, gameplay, installer, assistive-technology, release, signing/notarization, and acceptance testing remain open; ad-hoc signatures were verified but do not close production signing/notarization. No live input was sent; no game screenshots or game pixels were saved or committed. Launcher UI screenshots were saved for UI inspection. Credentials, transactions, deployment, and public binary release did not occur.
- Staged native receipt: the exact verified `13fa083` app was reopened after the owner-authorized refresh of Accessibility, Input Monitoring, and Screen Recording. Its executable path was `/private/tmp/afk-grinder-current/AFKGrinder.app/Contents/MacOS/AFKGrinder` and its SHA-256 was `89c148599f9e460de50411edb4101914119b43c60a2974b271fb0c7890326a53`. The launcher reported native checks ready and automatically bound the unique Roblox window while remaining foreground. The owner manually reconnected Adopt Me and the controller observed clear gameplay with no modal; no input workflow was started. Explicit Capture failed with an unexpected worker error and published no pixels. Native capture acceptance, movement, focus-loss cancellation, Escape cancellation, and held-key cleanup remain open.
- Producer/integrator: Sol, OpenAI primary controller, with native diagnosis by Sol; frontend/design production by OpenAI Terra; documentation production by OpenAI Luna. Independent reviewers: OpenAI Terra-xhigh `gpt_reviewer` for `51eb15b..a59a3fe`, `a59a3fe..6f29704`, and `6f29704..13fa083`; OpenAI Terra-xhigh `gpt_ui_review` for exact range `51eb15b..a59a3fe` only. All applicable reviews passed with no remaining P1/P2/P3 findings. GLM was skipped because the registry was stale/future-dated before contact; no provider call or payload transfer occurred. No Spark lane was used.
- Changed paths for the scaling slice (`git diff --name-only 51eb15b4a131812e235e16add5a84acc843c08c4..HEAD`):

```text
README.md
docs/DESKTOP_BRIDGE.md
docs/UI_DESIGN.md
intent.md
plan.md
spec.md
src/afk_grinder/capture/__init__.py
src/afk_grinder/capture/service.py
src/afk_grinder/desktop_app.py
src/afk_grinder/desktop_controller.py
src/afk_grinder/web/app.js
src/afk_grinder/web/index.html
src/afk_grinder/web/styles.css
tests/test_capture_service.py
tests/test_desktop_app.py
tests/test_desktop_controller.py
tests/test_frontend_contract.py
```

### Native capture failure diagnosis and candidate fix

- The latest exact `13fa083` native test reproduced a capture failure reported as `unexpected` at the IPC read boundary. A matching own-application worker crash was observed at 10:59:32 PDT on October 20, 2026. The native stack reached `SCContentFilter` initialization and a `SLSGetDisplaysWithRect` assertion, consistent with a missing display-environment bootstrap; the underlying cause remains a hypothesis pending native retry. This is not proof that the candidate fix resolves capture.
- The current source candidate initializes AppKit on the worker's main thread before ScreenCaptureKit use. It creates a shared `NSApplication` only when no application exists, applies the prohibited activation policy, preserves an existing application unchanged, and never activates or runs the application. The worker IPC error is now a fixed safe message; diagnostics retain only allowlisted code, stage, and error type, with no native exception text or paths.
- The no-capture child smoke passes with the required elevated WindowServer access; the same bootstrap fails closed in the sandbox rather than using an unsafe fallback. Final elevated validation passes all 199 tests, compilation, JavaScript syntax, and whitespace checks. Source launcher smoke and the rebuilt Mac dry-run/frozen launcher/readiness checks pass. Frozen validation first exposed a sanitization regression, now corrected by preserving only the fixed allowlisted optional-SDK-absence message with exact `SDKError` matching; all other exception text is generic. Independent review also requested a post-constructor deadline check: a slow native bootstrap now cannot start a snapshot after expiry, covered by a deterministic fake-clock test. Real native capture, gameplay movement, focus-loss cancellation, Escape cancellation, and held-key cleanup remain open pending fresh independent review, CI, and a final verified replacement candidate. The staged native candidate remains `13fa083` until those gates pass.
- Fresh OpenAI Terra-xhigh read-only review of the eight-file packet passed with no remaining P1/P2/P3 findings. Sol produced the macOS bootstrap and native tests; OpenAI Terra-high produced the bounded IPC/deadline changes and service tests; OpenAI Luna-medium updated the documentation, with Sol integration and validation. Changed paths are `src/afk_grinder/capture/macos.py`, `src/afk_grinder/capture/service.py`, `tests/test_capture_backends.py`, `tests/test_capture_service.py`, `tests/test_macos_pixels.py`, `plan.md`, `spec.md`, and `docs/MAC_LIVE_TEST.md`. GLM remained skipped under the previously recorded stale-registry gate; no external provider payload, Spark fallback, game capture persistence, live input, credentials, transaction, release, signing credential, or deployment occurred. CI and verified native retry remain open. Apple's [NSApplication documentation](https://developer.apple.com/documentation/appkit/nsapplication?changes=la_2_2) supports the display-environment bootstrap rationale, but does not prove this native failure resolved.

### Current native window-selection evidence

- With the exact `e594508` app and all three permissions enabled, native readiness reported ready and automatic binding selected the unique Roblox target. Explicit capture and a foreground retry both failed at `window_count/window_selection`; no native filter crash was observed, but the filter stage was not reached, so the earlier crash fix remains unproven. No input was sent.
- Secret-free Quartz metadata review found seven verified Roblox window records, with two on-screen layer-0 candidates: a 66×20 auxiliary record and a 943×632 game record. No titles, account data, pixels, or raw diagnostic reports were retained. A separate CLI ScreenCaptureKit source check stopped at permission preflight and did not grant permissions.
- The bounded replacement source now shares one predicate for selection and bound-ID revalidation: verified target identity, Roblox bundle, on-screen state, layer 0, finite frame, and at least 320×240 logical points. It never uses largest-window or title heuristics; multiple qualified windows remain ambiguous, and zero qualified windows reports `window_missing`. Shrink, layer, PID, and bundle changes invalidate the binding before a screenshot. OpenAI Terra-high produced `src/afk_grinder/capture/macos.py` and `tests/test_capture_backends.py`; OpenAI Luna-medium updated `plan.md`, `spec.md`, and `docs/MAC_LIVE_TEST.md`, with Sol integration. Elevated validation passes 205 tests, compilation, artifact validators, and whitespace. Fresh OpenAI Terra-xhigh read-only review passed all five files with no remaining P1/P2/P3 findings after correcting zero-window diagnostics and adding same-ID PID/bundle revalidation coverage. New CI and a verified native retry remain required; M1/native capture remains open.

### Verified CI receipt for current native candidate

- Source `e59450857fceec52ce7317a370dca8c3b95dac50` passed all three jobs in [run 39472952279](https://github.com/hypler-dev/afk-grinder/actions/runs/39472952279) on the first attempt. The six non-expired application and SDK-inventory records were downloaded and statically verified from `/private/tmp/afk-grinder-ci-39472952279/VERIFICATION.json`. All bundles are SDK-free, retain 102 verified notices, and pass exact source, frontend, architecture, SDK-exclusion, and inventory checks. Both Mac archives pass deep strict ad-hoc signature verification. No SDK-bearing binaries were uploaded.

| Target | Application archive SHA-256 | SDK inventory SHA-256 | Inventory counts (embedded / SDK modules / native / legal paths) |
| --- | --- | --- | --- |
| Windows x64 | `b36f814c4a6d1f80d08994adee6bd899256b7d0cc4f385c3fef97c96260d46cd` | `d6c41d292e85f1bd0b965237cb9aafdafab19605de5ddff0f6fe7c0a98e7e6bb` | 505 / 677 / 122 / 126 |
| Mac Apple Silicon | `64df71963ab83523ca7a28c772b19c80cd97569673411f74f2103a68447fd1a3` | `41c6f61581cca2071624fcc81e47faa4aad3f5735ba8225c50615e2845722e2a` | 391 / 558 / 109 / 248 |
| Mac Intel | `d86370597108a2e3be32445518e66491722e3874792f25685c43b3d35e3a2acf` | `4da4e983bae638a503d8c33cf0e78c6d2db4f474af3fc2c1d9789beef1dc8935` | 391 / 558 / 109 / 248 |

- Current verified arm64 executable is staged at `/private/tmp/afk-grinder-current/AFKGrinder.app/Contents/MacOS/AFKGrinder` with SHA-256 `a631279921283aca69a568f3c245738dec8c421a7b6abb55e727a3db3b4b8e59`. The exact updated app is access-blocked after the unsigned update; fresh confirmation of Accessibility, Input Monitoring, and Screen Recording for this build remains pending. The owner again confirmed clear Adopt Me gameplay; no input workflow was started. Native capture remains unproven, and no live-input acceptance is claimed.

### Offline state-inspector foundation

- Authority remains `intent.md` and BUILD.md sections 5, 6 and 10. The pre-capture packet adds `src/afk_grinder/recognition/state.py` and `tests/test_recognition_state.py`; contract/evidence changes are limited to `spec.md` and `plan.md`. It does not change pack schema, launcher, bridge, SDK adapter, input engine or staged native app.
- The inspector combines supplied anchor scores with validated pack states and current-frame metadata. It reports known only for one stable candidate; exclusion conflicts block, and missing/ambiguous/invalid evidence remains unknown and resets stability. Below-threshold evaluated evidence is distinct from unavailable evidence. A unique candidate reports `unknown/unstable` while its valid consecutive-frame count accumulates. Replay watermarks survive resets; sequence gaps, generation/layout changes and candidate changes restart the count. Counts are bounded by the pack's declared 2–5 frames. It retains metadata only, with no observation or pixel references.
- OpenAI Terra-high produced the two source/test files; Sol owns contract, integration and validation. Read-only OpenAI Terra-xhigh contract review closed two P2 documentation gaps by specifying caller-provided monotonic time, the 0.5-second age bound and no pixel retention. A P3 coverage gap prompted candidate/known retention tests. Local validation passes 190 total tests, including 15 inspector tests, compilation, intent/spec/plan artifact checks and whitespace. Fresh independent implementation review passed the exact four-file packet with no remaining P1/P2/P3; the reviewer also passed all 15 targeted tests and compilation. The completed exact-revision CI receipt appears below.
- Synthetic tests cover stability, competing incomplete evidence, exclusions, ambiguity, unavailable versus evaluated-negative evidence, strict scores, freshness boundaries, stale/future frames, replay/order, generation/layout changes, sequence gaps and observation/pixel release. No actual matcher, Maa pipeline, game fixture corpus, transaction detector, care routine or input authorization is supplied. Milestone 2 remains unaccepted. The pending permission request and native test candidate `13fa083` remain unchanged; no live input or game images were collected.
- Source `fa3bc7aa9ecd200795861f1f1a079e7c83440fd0` was committed and pushed. [Run 39428783690](https://github.com/hypler-dev/afk-grinder/actions/runs/39428783690) completed successfully on Windows x64 and both Macs. Both Mac jobs passed their first execution. Windows initially passed all 15 inspector tests but the unchanged `test_new_safe_stages_render_and_unknown_native_details_are_rejected` Node subprocess exceeded its five-second deadline. One `gh run rerun --failed` request reran only Windows on the same commit; its 190-test suite passed with three Mac-specific fixture checks skipped, and all remaining build/package gates passed. No code, assertion or deadline was changed for the retry. The initial timeout is retained as an unresolved CI reliability observation, not a proven host cause or a fixed formatter defect. The source packet's build artifacts have not been selected or separately downloaded/reverified locally; the actual Mac test app and its pending permission request remain pinned to verified `13fa083`.
- Final boundaries: original code remains MIT, with dependency notices and the SDK-bearing distribution gate unchanged. No SDK-bearing binary upload, real game fixture recording, live input, login handling, transactions, signing credentials, production deployment or public release occurred. Fresh OpenAI Luna read-only documentation review resolved a stale CI-pending sentence and passed the final spec/plan update, including validators and whitespace. GLM remained uncontacted because its prior registry gate was stale/future-dated; native OpenAI lanes were used. No Spark lane was used. No unrelated working-tree dirt was present before this receipt update.
