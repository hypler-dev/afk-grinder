<!-- intent-driven-delivery:intent:v1 -->
# Intent: Bootstrap AFK Grinder

Status: accepted
Authority: this file
Owner: Jeff / hypler-dev
Accepted by: Jeff, through the October 19, 2026 chat instruction to create a GitHub repository with Windows/macOS installers planned, Linux excluded, and mobile research deferred
Last updated: 2026-10-19

Acceptance covers only repository bootstrap and desktop platform targets. Detailed application design remains proposed.

## Problem and evidence

The user currently uses macOS Automator for Roblox actions and wants a shared application with editable workflows and an initial Adopt Me template. The local project directory was empty and was not a Git repository at startup.

## Desired outcome

Create a private GitHub repository named `afk-grinder`, connect this local directory, and publish an initial project scope. Record Windows and macOS installer binaries as delivery targets. Keep iOS and Android as research, with Linux excluded.

The eventual application should allow users to record, edit, test, and update action templates without rebuilding the application. Architecture, specific task coverage, and implementation acceptance criteria remain proposed until a bounded implementation packet is accepted.

## Users and systems

- Owner and initial user: Jeff.
- Repository: `hypler-dev/afk-grinder`.
- Initial target systems: Windows and macOS running Roblox.
- First proposed game template: Adopt Me.
- iOS and Android: research only.

## Constraints

- The current authorized slice is repository initialization and scope documentation.
- Keep the repository private by default; no public publication was requested.
- Produce no application or installer claims without platform-specific validation.
- Do not add Linux delivery or imply that desktop framework support proves mobile automation support.
- Keep credentials, input recordings, screenshots, local profiles, and generated installers out of source control.
- Roblox sign-in remains manual. The user explicitly removed login automation from scope on October 19, 2026; do not collect credentials, manage login sessions, or record/play back authentication screens.
- Repository creation and its initial push are authorized. Signing, publishing binaries, app-store submission, and live gameplay execution are separate future work.

## Non-goals

- Implementing or running gameplay automation in this bootstrap.
- Building or publishing installer binaries in this bootstrap.
- Committing to mobile delivery, a production framework, or an input library.
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

- Local Git repository uses `main` and has a clean initial commit containing only the bootstrap files.
- GitHub repository is private, owned by `hypler-dev`, and named `afk-grinder`.
- Local `origin` points to that repository; local HEAD matches fetched `origin/main`.
- README explicitly distinguishes planned installers and mobile research from working functionality.
- Run the intent artifact validator and Git whitespace checks.
- Obtain independent read-only review of the exact bootstrap files before committing and pushing.
- Final task response records the repository URL, commit, validation, review, and remaining work; this record does not duplicate live Git status.

## Source-of-truth links

- Canonical authority: this `intent.md`.
- Product overview and proposed roadmap: [README.md](README.md).
- Accepted scope source: the October 19, 2026 user instruction in this chat.
