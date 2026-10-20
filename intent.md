<!-- intent-driven-delivery:intent:v1 -->
# Intent: AFK Grinder desktop prototype

Status: accepted
Authority: this file
Owner: Jeff / hypler-dev
Accepted by: Jeff, through the October 19, 2026 chat instructions to build the prototype, commit/push it, and set up downloadable Windows/macOS automated builds
Last updated: 2026-10-19

Acceptance covers the bounded desktop prototype, its commit/push to the private repository, and automated Windows/macOS test-binary builds. Signed releases, production installers, mobile delivery, and unattended gameplay claims remain outside this slice.

## Problem and evidence

The user currently uses macOS Automator for Roblox actions and wants a shared application with editable workflows and an initial Adopt Me template. The local project directory was empty and was not a Git repository at startup.

## Desired outcome

Build a local Windows/macOS prototype that executes bounded keyboard and mouse actions only against an explicitly selected foreground Roblox process, stops on focus loss or Escape, and releases held inputs on exit. Provide dry-run execution and a small editable action template. Roblox login stays manual. No runtime LLM is required.

Commit and push the reviewed prototype, then automate private downloadable test builds for Windows x64 and macOS Apple Silicon/Intel. Record the source revision, target architecture, and checksums with each artifact. The project began as a fun family project for Jeff's kids, with the aim of spending less time on repetitive game chores and more time outdoors.

The eventual application should allow users to record, edit, test, and update action templates without rebuilding the application. Recording, visual recognition, and specific Adopt Me gameplay routines remain future work. The Python/Tk prototype establishes the deterministic safety and input seam before a final production framework is selected.

## Users and systems

- Owner and initial user: Jeff.
- Repository: `hypler-dev/afk-grinder`.
- Initial target systems: Windows and macOS running Roblox.
- First proposed game template: Adopt Me.
- iOS and Android: research only.

## Constraints

- The current authorized slice includes prototype commit/push, GitHub Actions execution, and private test-binary artifact uploads in addition to implementation, documentation, and validation.
- Keep the repository private by default; no public publication was requested.
- Produce no application or installer claims without platform-specific validation.
- Do not add Linux delivery or imply that desktop framework support proves mobile automation support.
- Keep credentials, input recordings, screenshots, local profiles, and generated installers out of source control.
- Roblox sign-in remains manual. The user explicitly removed login automation from scope on October 19, 2026; do not collect credentials, manage login sessions, or record/play back authentication screens.
- Process focus cannot establish whether Roblox shows gameplay, login, chat, or an in-game purchase. Require an explicit signed-in/gameplay acknowledgment and a short bounded run; do not claim screen-state recognition.
- Private CI test artifacts are authorized. Keep CI permissions minimal, use hosted target-OS runners, and do not add signing credentials, public releases, app-store submissions, or live gameplay execution.

## Non-goals

- Running live gameplay automation during development or claiming Adopt Me task completion.
- Publishing production installers, signed binaries, public releases, or app-store submissions.
- Committing to mobile delivery or a final production framework.
- Login, screen recording, action recording, visual recognition, account switching, or LLM orchestration.
- Client injection, memory access, anti-cheat bypass, credential collection, automated purchases, or automated trades.

## Assumptions and verified facts

- Verified: the user selected Windows and macOS installers, excluded Linux, and requested further mobile research.
- Verified: the directory was empty and had no Git history at task startup.
- Verified: the authenticated GitHub CLI API identifies `hypler-dev` as the active account.
- Verified: [Roblox requirements](https://en.help.roblox.com/hc/en-us/articles/203312800-Computer-Hardware-Operating-System-Requirements) state that Linux is unsupported; source checked during the initial discussion.
- Assumption: private visibility is appropriate because no public visibility was requested.
- Assumption: normal OS input and screen capture can support a useful desktop routine; this requires proof on both target systems.
- Open: permission for this specific use under Roblox and Adopt Me rules has not been established.

## Risks

- Synthetic input may not work consistently in Roblox across platforms.
- Camera position, timing, display scaling, and game updates may invalidate recorded actions.
- Screen capture and input recording can expose unrelated personal data without careful scoping.
- Signing, notarization, permissions, supported architectures, and clean-machine behavior may change packaging requirements.
- Mobile OS restrictions and game/platform rules may prevent the desired mobile behavior.

## Acceptance evidence

- Named unit tests prove focus loss, Escape, GUI stop, errors, and completion release all held input and prevent later actions.
- Dry run emits no OS input. Invalid templates fail before execution. Runs are bounded; waits are interruptible.
- Native Windows and macOS adapters check target identity, permissions/readiness, foreground focus, and Escape state without collecting credentials or recording other keys.
- The desktop UI exposes binding, dry run, live arming, countdown, stop, and actionable errors without automatic login or automatic focus acquisition.
- Run `python3 -m unittest discover -s tests -v`, compile checks, artifact validators, and Git whitespace checks.
- Obtain fresh independent read-only code and UI review before closeout. Record actual host validation separately from Windows/macOS manual test gates.
- README provides exact local run/build commands, remaining platform tests, and honest limitations. No release or platform support claim is based only on unit tests.
- The prototype is committed and pushed; local and fetched remote main match after the final documentation update.
- Automated Windows/macOS builds test and smoke-check packaged binaries before uploading private, revision-labeled artifacts. Verify completed runs and actual downloadable artifact records before claiming builds are ready.

## Source-of-truth links

- Canonical authority: this `intent.md`.
- Product overview and proposed roadmap: [README.md](README.md).
- Prototype behavior: [spec.md](spec.md); execution and evidence: [plan.md](plan.md).
- Accepted scope source: the October 19, 2026 user instruction in this chat.
