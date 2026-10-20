# AFK Grinder: desktop automation build specification

Version: 1.0 • October 20, 2026 • Owner: Jeff / hypler-dev

Status: implementation blueprint. Product direction is agreed; proposed defaults below must be validated. This document does not claim that the planned features are implemented or that unattended gameplay is reliable.

## 1. Product decision

Build a free Windows/macOS desktop application using MaaFramework for visual recognition and task pipelines. Run recognition locally, without an LLM, hosted GPU, or per-image API. Start with Adopt Me pet-care routines for age-up potions. Keep the application engine reusable through declarative, game-specific resource packs.

Target hardware: Intel i5 with 8 GB RAM, plus Apple Silicon Macs. “i5” spans many generations; record the actual CPU, OS, graphics, and Roblox settings during benchmarking. These are targets, not verified minimum requirements. Supported OS versions will be set after SDK and native adapter validation.

The eventual goal is long unattended sessions. Reach that goal incrementally through recognition-only and short supervised milestones. No paid subscription, account system, cloud inference, or remote-control companion app is required for the first release. A companion app is deferred.

### Current implementation versus planned work

| Area | Existing repository baseline | Planned extension |
| --- | --- | --- |
| Desktop app | Python/Tk, Python 3.11+ | Retain initially; avoid a UI rewrite during engine integration |
| Input | Native Windows/macOS adapters, foreground binding | Window-relative positional input and guarded Maa controller integration |
| Execution | Version-1 JSON; bounded hold/wait/current-pointer click | Recognized states, conditional task graph, bounded retries |
| Safety | Stop/Escape, focus checks, held-input cleanup | Fresh-frame and layout guards, recognized gameplay gating |
| Recognition | None | Local MaaFramework template matching and selective OCR |
| Adopt Me | Movement/input-check template only | Tested pet-care resource pack |
| Distribution | Unsigned test-binary build workflow | Verified SDK packaging; signed production distribution is a separate milestone |

The existing `spec.md` describes the implemented prototype. This blueprint extends the roadmap; it does not silently relax its live-run limits. Update the runtime specification alongside each implemented milestone.

## 2. Scope and boundaries

First game: Adopt Me. First environment: a prescribed house setup with repeatable furniture positions, starting position, and camera setup. Support only the care tasks that can be demonstrated reliably in that setup before adding map travel.

Candidate indoor tasks discussed: eating, drinking, sleeping, showering, potty, petting, catch, and riding. Verify each task's current mechanics and equipment prerequisites before enabling it. Do not assume every task is stationary or equally easy to automate.

Location-based tasks, including camping, school, playground, beach, salon, pizza party, and café visits, are later work. Navigation must be observed and verified, not inferred from a long timed key sequence. In-game shortcuts can be considered after their behavior is tested; no client injection or teleport exploits.

The user's stated age-up-potion rule is 30 completed tasks on a full-grown pet, without a daily cap. Treat this as a requirement to verify against current game behavior, not a hard-coded guarantee. Progress and rewards require visible evidence; elapsed time or action count alone is insufficient.

Explicit exclusions:

- Automated purchases with real money, Robux, or game currency; sales, trades, gifts/transfers, and pet disposal.
- Credentials, login automation, account switching, session-token access, and arbitrary chat/text entry.
- Process-memory access, game-client injection, private game APIs, and anti-cheat bypass.
- Downloaded executable routines, arbitrary plugins, shell commands, or runtime-generated code.
- Mobile automation, background-input guarantees, automatic reconnection/login, and guaranteed 24/7 operation.

Manual login and explicit setup remain necessary. Missing supplies or equipment pause the task; the app does not buy replacements.

## 3. Architecture

| Component | Contract |
| --- | --- |
| Desktop UI | Select window, setup checklist, calibration preview, task choices, dry run, start/stop, status and errors |
| Platform adapter | Window/process identity, content bounds, display scale, capture, foreground state, input and cleanup |
| Observation service | Timestamped frames, coordinate transforms, layout generation, capture validity |
| Maa adapter | Pinned SDK lifecycle, recognition/task execution, cancellation and result translation |
| Policy/action gate | Validate every action against target identity, fresh observation, current layout, foreground state, allowed game state and session bounds |
| Pack compiler | Validate a restricted application schema and generate engine-owned Maa resources/pipelines |
| Session coordinator | State transitions, scheduling, deadlines, retry budget, verification and counters |
| Pack manager | Curated downloads, integrity/authenticity checks, staging, activation, rollback and provenance |

Keep the current input backend behind the action gate. Confirm Maa's custom-controller integration contract for the selected release before implementation. Do not allow a second native input path that bypasses the gate. Recognition callbacks are observations, not authorization to act.

Suggested module boundaries: `capture/`, `coordinates.py`, `recognition/maa_adapter.py`, `packs/schema.py`, `packs/compiler.py`, `packs/installer.py`, `session.py`, and `policy.py`. These are proposed responsibilities, not files already implemented.

Pin an exact tested MaaFw version and dependency lock. Verify packages for Windows x64, macOS x64, and macOS arm64; library support does not prove native Roblox capture/input compatibility. Audit SDK screenshot/error logging defaults and disable persistent captures by default.

## 4. Capture, display scaling, and calibration

Maintain three explicit coordinate spaces: physical capture pixels, normalized/reference content coordinates, and native input coordinates. Define and test transformations between them. Never infer the target window size from monitor resolution alone.

Each observation carries a monotonic capture timestamp, target process/window identity, content rectangle, capture dimensions, monitor/scale information, layout generation, and validity status. Any resize, monitor change, DPI change, window replacement, or content-area change invalidates queued actions and requires a new observation/calibration.

Recognition strategy:

1. Locate the game content rectangle and stable UI anchors.
2. Search small regions relative to those anchors.
3. Use a bounded template-scale range, with alternate templates for layouts that actually change.
4. Use OCR only for fields that require text; constrain language and expected values.
5. Require suitable temporal stability for action-triggering detections.
6. Convert the recognized target through the current coordinate transform immediately before input.

Do not stretch the entire frame to a fixed aspect ratio. Preserve aspect ratio, and account for letterboxing and edge-anchored UI. Upscaling a small image does not restore lost detail. Establish a tested minimum game-content size rather than promising arbitrary tiny-window support.

Calibration UI displays the selected content area, detected anchors, target boxes, and recognition state without input. Explain why a setup fails. Save only non-sensitive calibration metadata; invalidate it when its assumptions change.

Test: 1080p, 1440p, 4K and 5K displays; small/medium/maximized windows; 16:9, 16:10 and ultrawide; Windows scaling 100/125/150/200%; macOS Retina/scaled modes; mixed-DPI monitors; window movement and resize mid-task. These are test cases, not launch support promises.

A valid capture may be possible while a window is occluded, but input is permitted only while the bound target is foreground. Pause for minimized/unavailable capture, focus loss, display sleep/lock, permission revocation, or unknown capture state. Do not automatically steal focus or resume after focus returns.

## 5. Session and routine behavior

Session states: Idle → Setup → Calibrating → Ready → Running. Running may enter Verifying, Recovering, Paused, Stopping, Completed, or Failed. Stop is available during recognition and waits as well as input. Stop cancels future actions and releases all tracked held inputs.

Each routine follows: observe → identify a supported need/state → select a permitted action → recheck guards → act → observe outcome → confirm or stop/retry. Do not queue long blind action sequences.

State descriptions should cover gameplay, known location, active pet, visible need, interaction menu, task in progress, task completion, loading, disconnected, purchase/trade UI, and unknown screen. Unknown or conflicting evidence blocks actions. Distinguish “not visible” from “not present.”

Every node has a deadline; every recovery path has a bounded retry count; the whole session has a duration/task limit. Backoff should not block cancellation. Hold durations remain bounded. After timeout or repeated failure, pause with the last recognized state and a concrete corrective instruction.

Progress counters update only after verified completion, with duplicate-event suppression. Display confidence/uncertainty honestly. Do not label an inferred task count as a confirmed potion reward. Resuming after interruption starts with fresh state discovery, not the previous queued click.

Preserve existing short live-run limits during integration. Longer sessions require an explicit implementation milestone and supporting soak-test evidence. Run only one routine at a time for the first release.

## 6. Resource-pack format

Use our own versioned, restricted JSON contract; compile it into Maa's supported protocol. Do not mistake the example below for a native Maa pipeline or a finished schema.

A pack contains:

- Manifest: pack/schema versions, game ID, compatible app versions, source revision, licenses/attribution and asset hashes.
- Recognition definitions: image asset references, anchors, regions, reference dimensions, scale bounds, thresholds and optional constrained OCR rules.
- State definitions: positive evidence, exclusions, expected transitions and uncertain/unknown handling.
- Routine definitions: supported semantic actions, preconditions, expected outcomes, deadlines and retry limits.
- Setup requirements: furniture, starting view, pet prerequisites, language and tested layouts.
- Test fixtures and expected labels, distributed only with appropriate permission and no private data.

Illustrative manifest:

```json
{
  "schema_version": 1,
  "pack_id": "adopt-me.indoor-care",
  "pack_version": "0.1.0",
  "game": "adopt-me",
  "status": "experimental",
  "reference_content_size": [1920, 1080],
  "languages": ["en"],
  "routines": ["sleep"],
  "requires_manual_setup": true
}
```

Use namespaced semantic capabilities such as `care.sleep` that resolve to reviewed implementation paths. Do not let arbitrary imports nominate unrestricted click targets under a friendly action name. Spatial/recognition constraints still require validation and runtime checks; semantic names alone are not a safety boundary.

Keep existing version-1 input-check templates in an explicit legacy/test mode. Do not silently reinterpret them as trusted unattended routines. Unknown schema versions are rejected; migrations produce reviewable output and keep the original.

Pack preferences may select supported tasks, session length, language and validated recognition presets. Global security policy, protected states, application code, credentials and native-controller selection are never pack-configurable.

## 7. Import security and transaction prevention

Validate before loading resources into the engine. Reject duplicate JSON keys, unknown fields, invalid types, non-finite numbers, invalid references and unsupported actions. Set concrete caps for file size, nesting, node count, image dimensions, expanded archive size and recognition workload before enabling imports.

Extract into a new staging directory. Reject traversal, absolute paths, symlinks/hardlinks and archive bombs. Resolve assets within the pack root; no external URLs or arbitrary local paths in recognition definitions. Decode images with supported libraries under size/time limits.

Compile only allowlisted constructs. Disable imported shell/command actions, custom executable agents, plugin loading, code expressions and arbitrary Maa overrides. Network access belongs to the pack manager, not routines. AI-assisted conversion is an offline authoring aid whose output faces the same checks; never execute its output directly.

Use an unprivileged recognition worker where feasible, with cancellation/timeouts and restricted filesystem/network access. Native dependencies remain a supply-chain risk even with JSON validation. A plain subprocess without OS restrictions is not a sandbox.

Transaction defense has multiple layers: omit transaction capabilities; restrict routines to reviewed care interactions; require current known gameplay state; stop on purchase/trade dialogs and unfamiliar overlays; verify outcomes. Recognition mistakes and the OS focus-check/input race remain possible. Do not advertise a mathematical guarantee that a generic screen-input tool can never click a transaction.

Stop/cleanup failure blocks further live input. Retain a visible stop control and global emergency-stop mechanism. Test that canceling Maa work cannot leave late actions queued.

## 8. Internet resources and updates

Use curated upstream material to accelerate development. Public availability and “free download” are not sufficient evidence of permission, safety or compatibility. Inspect license and actual source/assets before adoption. Repository licensing may not cover third-party game artwork independently.

Record origin URL, exact commit/release, file hashes, license, attribution, adaptation notes and local validation evidence. Never pull a moving upstream branch directly into active gameplay. Pin dependencies and pack revisions. Reject opaque installers or executor/injection-based routines as incompatible with this architecture.

Initial research leads:

| Source | Finding | Decision |
| --- | --- | --- |
| MaaXYZ/MaaFramework | Recognition engine, official Python binding, pipeline tools; LGPL-3.0 | Selected foundation; pin and test SDK |
| NatroTeam/NatroMacro | Windows AutoHotkey Bee Swarm routines, image assets, paths; GPL-3.0 | Reference/adaptation candidate after license and technical review; not an Adopt Me pack |
| Vvamp/AdoptMe_CarveTheCliff | Event-specific AHK script and PNG; README requires 1920×1080; no root license observed | Research lead only; permission and live relevance unverified |

No verified reusable Adopt Me pet-care pack or comprehensive recognition dataset has been found. Plan to capture missing fixtures locally with user consent. Never label an upstream routine “working” based only on its README, stars or downloads.

Update flow: fetch curated metadata → verify trusted signature and hashes → stage → validate → preview changes → activate while idle → retain rollback. A hash proves consistency, not publisher identity. Define signing-key rotation/revocation before shipping automatic updates. Never hot-swap packs in a running session. Offline operation continues with the last validated installed pack.

## 9. Privacy, permissions and performance

Login remains manual. Explain and guide macOS Screen Recording/Accessibility permissions; do not attempt to grant them silently or bypass OS consent. Request only what implemented features need. Avoid administrator/root execution.

Keep screenshots in memory by default. Diagnostic recording is explicit, local, bounded and deletable; mask user identifiers where practical. No telemetry or screenshot uploads by default. Logs record state, timing, errors and pack versions, not credentials, chat or unrelated windows.

Start with a configurable observation interval around 1–3 seconds while idle, and short bounded bursts during interactions; this is an initial tuning hypothesis. Keep emergency-stop/focus monitoring independent of capture cadence. Benchmark latency and CPU rather than assuming low resolution makes processing negligible.

Use cropped recognition, bounded scale search, cached resources, limited worker threads and selective OCR. Measure median/p95 observation latency, peak RAM, CPU, Roblox responsiveness, false detections and timeouts. Limit frame caches so native SDK defaults cannot accumulate thousands of full-resolution frames.

With local execution, 10–15k users do not create centralized per-frame inference costs. Distribution bandwidth, updates, support and maintenance still grow with usage. Do not promise a fixed infrastructure cost until package sizes and download frequency are measured.

## 10. Build milestones and acceptance gates

| Milestone | Deliverable | Acceptance gate |
| --- | --- | --- |
| 0 — Baseline and SDK | Preserve existing behavior; pin MaaFw; dependency/license inventory | Existing tests pass; SDK loads and packages on all three target architectures |
| 1 — Capture/calibration | Window-only preview and coordinate transforms | Correct boxes on tested layouts; move/resize/DPI changes invalidate targets; no input emitted |
| 2 — Recognition | Restricted pack loader and state inspector | Labeled held-out fixtures; explicit unknown states; transaction/overlay fixtures block actions; documented failure cases |
| 3 — One routine | One indoor care task in a prescribed setup | Repeated supervised completion on target hardware; outcome verification; stop/focus/permission/cleanup tests pass |
| 4 — Indoor task pack | Additional tasks and bounded recovery | Per-task evidence, interruption tests, no purchase/trade capabilities; minimum content size published |
| 5 — Pack distribution | Curated signed pack updates with provenance | Tampering, traversal, incompatible versions, partial downloads and rollback tested |
| 6 — Longer sessions | Opt-in endurance mode with limits | Increasing-duration soak tests, resource stability, no uncontrolled input; supported configurations documented |
| Later | Location navigation, more games, optional companion UI | Separate game/profile and platform acceptance evidence |

Before milestone 2, define a labeled fixture corpus with different window sizes, aspect ratios, languages, animation states, popups and deliberate lookalikes. Separate tuning images from held-out evaluation. Report confusion by state; a high aggregate accuracy can hide dangerous purchase-dialog mistakes. Zero observed failures in a finite suite is not a guarantee.

Before milestone 3, test cancellation during every lifecycle phase, focus loss during holds, game exit, sleep/wake, permission revocation, stale frames, resize immediately before input, recognition timeout, failed cleanup and late callback delivery. Native behavior must be checked on Windows, Intel Mac and Apple Silicon, not inferred from Linux/fake-backend tests.

Record device/OS/display/game/pack/SDK versions with every live acceptance run. CI must not authenticate to Roblox or run unattended gameplay. It should validate schemas, fixture recognition where distributable, compiler restrictions, lifecycle behavior and packaged startup.

## 11. First implementation handoff

Start with milestone 0, then a recognition-only calibration window. Do not start by replacing the UI, importing arbitrary AHK scripts, or enabling indefinite loops.

1. Inspect existing engine/backend tests and preserve their guarantees.
2. Pin and smoke-test the SDK; confirm custom controller and cancellation APIs from that release.
3. Add observation/coordinate types and native capture adapters.
4. Implement calibration preview with no live action path.
5. Define the restricted pack schema and a tiny reviewed fixture pack.
6. Add template recognition and display results; capture missing Adopt Me fixtures with consent.
7. Document actual results and remaining platform blockers before the first supervised care task.

Open decisions to resolve through prototypes: exact minimum OS/CPU/window size; SDK release; capture APIs and cursor behavior per OS; tested languages; recognition thresholds/freshness budgets; initial care task; production signing and pack-update hosting. None requires inventing game-specific assets or claiming unperformed tests.

## 12. Schedule-aware planning: supplied community infographic

Source: user-supplied `needs-schedule-infographic-v0-cvpiu56knyqg1.jpeg`, credited in the image to Perry / @PerryplaysRBLX. Read during this planning session. Publication date, time basis, current game version and accuracy are unverified. Do not redistribute the artwork in the application without checking permission.

The image claims the following schedule (its `xx` notation denotes an unspecified hour):

| Event | Infographic claim |
| --- | --- |
| In-game day | 10 real-life minutes; starts at xx:10, xx:20, xx:30, etc.; 7 minutes daytime and 3 minutes night |
| Sleepy | Minute ending in 7: xx:07, xx:17, xx:27, etc. |
| Dirty | Minute ending in 9: xx:09, xx:19, xx:29, etc. |
| Blue or mystery task | Minute ending in 0, with 1–3 additional blue/mystery tasks during the in-game day |
| Camping | xx:27 and xx:57 |
| Hospital/sickness | xx:30 and xx:00 |
| Daily orange task | Every 10 minutes; stated cycle: school → beach party → pizza party → hair salon → playground |

The chart distinguishes blue tasks available to babies and pets (dirty, hungry, thirsty, sleepy) from pet-only tasks (catch, potty, ride, walk, pet me). These classifications also require gameplay validation. Its daily-orange list may be incomplete relative to the current game; keep unsupported events as unknown.

Implementation requirements:

- Store schedule hypotheses in a versioned game-data section, separately from executable routines, with source and verification date.
- Use expected times to prioritize observation and prepare permitted actions. A timer never authorizes input or proves a need exists.
- Establish cycle phase from observed events; the chart does not identify which 10-minute boundary begins the orange-task sequence. Do not invent a fixed phase or assume local wall time matches the server.
- Resynchronize after joining, reconnecting, sleep/wake, clock changes or conflicting observations. Use monotonic time for deadlines and wall time only as advisory schedule data.
- Multiple needs may coexist, including special and daily orange tasks. Keep an observed queue; support skipping location tasks while continuing supported indoor care.
- Missing a predicted event is not an error requiring blind retries. Continue observation within a budget, then mark the prediction uncertain.
- Schedule data may be updated without an app rebuild, but receives the same provenance, validation and version controls as the rest of the pack.

## 13. References

- Repository: https://github.com/hypler-dev/afk-grinder
- MaaFramework: https://github.com/MaaXYZ/MaaFramework
- Integration: https://github.com/MaaXYZ/MaaFramework/blob/main/docs/en_us/2.1-Integration.md
- API overview: https://github.com/MaaXYZ/MaaFramework/blob/main/docs/en_us/2.2-IntegratedInterfaceOverview.md
- Pipeline: https://github.com/MaaXYZ/MaaFramework/blob/main/docs/en_us/3.1-PipelineProtocol.md
- License: https://github.com/MaaXYZ/MaaFramework/blob/main/LICENSE.md
- Natro Macro: https://github.com/NatroTeam/NatroMacro
- Adopt Me example: https://github.com/Vvamp/AdoptMe_CarveTheCliff

Sources were inspected during planning on October 20, 2026; no upstream macro was executed. Review upstream licenses and distribution requirements for the exact versions adopted. Making the app free does not establish permission under Roblox/Adopt Me rules; that remains unresolved. No bypass of game protections is part of this build.
