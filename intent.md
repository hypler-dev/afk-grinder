<!-- intent-driven-delivery:intent:v1 -->
# Intent: AFK Grinder desktop application

Status: accepted
Authority: this file
Owner: Jeff / hypler-dev
Accepted by: Jeff, through the October 19 prototype/publication instructions and the October 20, 2026 instruction to develop the free, open-source application using the supplied BUILD.md blueprint and choose an appropriate license with warranty/liability disclaimers
Last updated: 2026-10-20

Acceptance covers development against the owner-supplied [BUILD.md](BUILD.md), preserved verbatim from `/Users/jeff/Downloads/BUILD.md`. This intent remains the canonical authority; BUILD.md defines the accepted product roadmap and acceptance gates, spec.md describes implemented runtime behavior, and plan.md records current evidence. The application is free and open source under MIT; third-party components retain their own licenses. Standard warranty and liability disclaimers do not promise immunity from every legal claim. Longer sessions and care routines require their blueprint milestones and live evidence before enablement. Production signing/release, mobile automation, transactions, and login automation remain excluded unless separately authorized.

## Problem and evidence

The user currently uses macOS Automator for Roblox actions and wants a shared application with editable workflows and an initial Adopt Me template. The local project directory was empty and was not a Git repository at startup.

## Desired outcome

Build a local Windows/macOS prototype that executes bounded keyboard and mouse actions only against an explicitly selected foreground Roblox process, stops on focus loss or Escape, and releases held inputs on exit. Provide dry-run execution and a small editable action template. Roblox login stays manual. No runtime LLM is required.

Commit and push the reviewed prototype, then automate downloadable test builds for Windows x64 and macOS Apple Silicon/Intel. Record the source revision, target architecture, and checksums with each artifact. The project began as a fun family project for Jeff's kids, with the aim of spending less time on repetitive game chores and more time outdoors.

Extend the existing Python/Tk application incrementally with pinned local MaaFramework recognition, window-only in-memory capture/calibration, a restricted declarative resource-pack format, guarded session coordination, verified indoor Adopt Me care routines, curated signed pack updates, and evidence-gated endurance sessions. No runtime LLM, cloud inference, account system, subscription, or paid feature is needed. Preserve the existing 30-second live-run limit until the longer-session milestone has supporting soak evidence. Recording and visual action editing are not prerequisites.

The owner additionally requested a polished gaming interface on October 20, selected a dark launcher with violet/cyan accents and bold game cards, and requested previews and cards for multiple games. Use a game library with separate game workspaces and explicit support status. Adopt Me remains the first input-check profile; additional game previews must not imply working automation. Changing games must invalidate window binding and live arming, and must never clear a cleanup-failure block. The interactive visual design is a separate deliverable while the native recognition foundation is integrated; it does not establish native shell or gameplay acceptance.

The owner subsequently instructed “we need to autobind” and approved using the gaming preview as the actual application interface. Integrate that accepted visual direction into the Windows/macOS desktop application using a local bundled web interface, retaining the existing guarded Python input engine. Automatically select a uniquely verified running Roblox target without a foreground-switch countdown; zero targets wait, and ambiguous targets require explicit selection. Automatic binding must never steal focus, arm input, acknowledge gameplay, start a run or resume after interruption. Live Start retains its supervised countdown, foreground checks, manual gameplay acknowledgment and 30-second limit. Expose the application version/source in Settings so older test copies can be distinguished. Capture failures require safe actionable stage/reason diagnostics; native capture acceptance remains open until a real preview succeeds.

The owner additionally requested scaling for the accepted launcher. Support small and large desktop windows, HiDPI displays and 200% interface zoom while retaining visible emergency Stop, reachable navigation and controls, readable wrapped statuses and source-pixel preview geometry. Window or interface scaling must not change the selected source area, arm input or clear safety state.

## Users and systems

- Owner and initial user: Jeff.
- Repository: `hypler-dev/afk-grinder`.
- Initial target systems: Windows and macOS running Roblox.
- First proposed game template: Adopt Me.
- iOS and Android: research only.

## Constraints

- The current authorized slice includes prototype commit/push, GitHub Actions execution, and test-binary artifact uploads in addition to implementation, documentation, and validation.
- The October 20 instruction additionally authorizes implementation of BUILD.md, a free open-source application, and license/disclaimer selection. The earlier publication and short supervised test authorizations persist. New recognition/capture features must preserve safety and privacy gates rather than silently expanding live execution.
- Produce no application or installer claims without platform-specific validation.
- Do not add Linux delivery or imply that desktop framework support proves mobile automation support.
- Keep credentials, input recordings, screenshots, local profiles, and generated installers out of source control.
- Roblox sign-in remains manual. The user explicitly removed login automation from scope on October 19, 2026; do not collect credentials, manage login sessions, or record/play back authentication screens.
- Process focus cannot establish whether Roblox shows gameplay, login, chat, or an in-game purchase. Require an explicit signed-in/gameplay acknowledgment and a short bounded run; do not claim screen-state recognition.
- CI test artifacts and public repository contents are authorized. Keep CI permissions minimal and use hosted target-OS runners. No signing credentials, public release publishing, or app-store submissions are authorized. Live execution is limited to short supervised movement, focus-loss, and Escape tests in the user's manually authenticated Adopt Me session.
- Publication must exclude credentials, session data, private game screenshots, input recordings, and other users' data. Verify tracked history before changing visibility. Generated artwork uses fictional subjects and contains no photos of the user's children.

## Non-goals

- Enabling unattended gameplay or claiming care-task completion before the relevant BUILD.md milestone has native and game-specific acceptance evidence. The long-term unattended goal remains on the roadmap; the current runtime stays bounded and supervised.
- Publishing production installers, signed binaries, public releases, or app-store submissions.
- Committing to mobile delivery or a final production framework.
- Login, account switching, arbitrary text/chat entry, action recording, persistent screen recording by default, or LLM orchestration. Local window capture and recognition are authorized development work under BUILD.md; diagnostic recording requires explicit consent.
- Client injection, memory access, anti-cheat bypass, credential collection, automated purchases, or automated trades.

## Assumptions and verified facts

- Verified: the user selected Windows and macOS installers, excluded Linux, and requested further mobile research.
- Verified: the directory was empty and had no Git history at task startup.
- Verified: the authenticated GitHub CLI API identifies `hypler-dev` as the active account.
- Verified: [Roblox requirements](https://en.help.roblox.com/hc/en-us/articles/203312800-Computer-Hardware-Operating-System-Requirements) state that Linux is unsupported; source checked during the initial discussion.
- Verified: the user subsequently requested public repository visibility and appropriate topics.
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
- Automated Windows/macOS builds test and smoke-check packaged binaries before uploading revision-labeled artifacts. Verify completed runs and actual downloadable artifact records before claiming builds are ready.
- Public visibility and topics are verified through GitHub after the change. README embeds the committed original artwork through a repository-relative path. No secret findings remain in the tracked-history publication check.
- Live test evidence distinguishes observed avatar movement, actual focus-loss cancellation, Escape cancellation, and held-key cleanup. Mark tests pending if Roblox/manual login or input permissions are unavailable; do not substitute fake-backend unit tests for live-game proof.

## Source-of-truth links

- Canonical authority: this `intent.md`.
- Accepted implementation blueprint: [BUILD.md](BUILD.md), supplied and adopted October 20, 2026.
- Project license: [LICENSE](LICENSE); dependency notices: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Product overview and proposed roadmap: [README.md](README.md).
- Prototype behavior: [spec.md](spec.md); execution and evidence: [plan.md](plan.md).
- Accepted scope source: the October 19, 2026 user instruction in this chat.
