# AFK Grinder

A planned desktop application for editable Roblox action workflows, starting with an Adopt Me template.

**Current state:** repository bootstrap and product scope only. There is no application, tested game template, installer, or published release yet.

## Platforms and distribution

| Platform | Scope | Planned distribution |
| --- | --- | --- |
| Windows | Initial desktop target | Installer binary; format to be selected during packaging work |
| macOS | Initial desktop target | Packaged application and installer/download; format to be selected during packaging work |
| Linux | Excluded | None |
| iOS / Android | Feasibility research only | No committed implementation or distribution plan |

Desktop CPU architectures and minimum OS versions remain to be selected and tested. Linux is excluded because Roblox does not officially support it; see [Roblox requirements](https://en.help.roblox.com/hc/en-us/articles/203312800-Computer-Hardware-Operating-System-Requirements).

## Proposed workflow

1. Select the Roblox window and calibrate the starting view.
2. Record a short keyboard/mouse sequence or build it from action blocks.
3. Edit timings, visual targets, conditions, and bounded retries.
4. Test one step at a time before running a complete routine.
5. Save and export versioned templates independently of application updates.

The first Adopt Me template should provide guided calibration and reusable movement/interaction routines. Actual task coverage, routes, visual targets, and completion checks require current-game testing. Existing macOS Automator sequences can inform that first test; automatic import is not promised.

## Proposed technical direction

- Shared desktop interface and workflow engine, with OS-specific input/capture adapters.
- A Tauri/React application is a candidate, not a final architecture decision.
- Validate normal keyboard/mouse input in Roblox on both target systems before selecting the production input library.
- Store templates as declarative data rather than executable scripts.
- Use visual checkpoints, timeouts, focus checks, an emergency stop, and held-key cleanup.
- Assume the game must remain visible and in the foreground until testing proves otherwise.

## Delivery roadmap

1. Prove desktop input, focus detection, and emergency-stop behavior on Windows and macOS.
2. Build a local recorder, editable playback, and a versioned workflow format.
3. Calibrate and test the first Adopt Me routine with visual checkpoints.
4. Build installers on the respective target operating systems; test installation, permissions, launch, and uninstall on clean machines.
5. Evaluate signing, macOS notarization, release checksums, and update/rollback behavior before public distribution.
6. Research mobile feasibility separately before committing to mobile support.

Installer compilation is not proof that gameplay automation works. Published support claims require end-to-end evidence on each supported platform and architecture.

## Mobile research questions

- Can an ordinary application capture the game and send the required inputs under current iOS/Android restrictions?
- Which accessibility, recording, foreground-service, or other permissions would be required?
- Would any approach require a desktop companion, special device state, or distribution outside an app store?
- Do platform rules, Roblox rules, and Adopt Me rules permit the intended behavior and distribution?
- Can stop controls, privacy, power use, and session recovery meet an acceptable standard?

These questions are open. A shared desktop UI framework does not establish mobile automation feasibility.

## Use and data boundaries

Roblox prohibits cheating/exploits and disruptive automation. Permission for this specific use in Adopt Me has not been established. See [Roblox Community Standards](https://en.help.roblox.com/hc/en-us/articles/203313410-Roblox-Community-Standards) and [Adopt Me support](https://www.playadopt.me/support).

The proposed product uses normal OS input and screen capture. Code injection, client modification, memory access, anti-cheat bypass, credential collection, and automated purchases or trades are outside the proposed scope. Screen captures and input recordings should remain local by default; capture must be explicit and limited to the intended game session.

## Project authority

[intent.md](intent.md) is the canonical scope and acceptance record. Repository creation and desktop platform targets are authorized; detailed application design and mobile support remain proposed.
