# Desktop UI direction

Authority: [intent.md](../intent.md). Product roadmap: [BUILD.md](../BUILD.md). On October 20, 2026, the owner selected “Dark launcher — violet/cyan, bold game cards” and requested multiple games with previews and cards. This replaces the earlier cream/green direction.

Open [the interactive desktop design](design/index.html). It works offline and uses local artwork and system fonts. It has no game connection, native input, capture, SDK calls, accounts, or telemetry. A permanent design ribbon identifies simulated states. This remains the simulated visual reference. The native application now adopts its game cards and workspace through bundled pywebview files and the guarded Python engine. [DESKTOP_BRIDGE.md](DESKTOP_BRIDGE.md) defines authoritative state; [plan.md](../plan.md) records exact native/build acceptance.

## Game library

Start on Home with a large featured Adopt Me cover and a grid of distinct game cards. Library provides the full catalog. Each card has original preview artwork, game name, genre, support badge, and one clear action. Keep the owner's tagline: “Helping kids touch grass by automating their games.”

The initial design includes Adopt Me, Bee Swarm Simulator, and Blox Fruits. Adopt Me exposes the current input-check workspace and marks care routines as unverified. The other two are proposed profiles, explicitly marked as not supported yet; they expose details but cannot start input. Their inclusion does not commit to gameplay automation or establish permission under any game's rules. An unavailable Add Game card communicates future extensibility without accepting arbitrary executable packs.

Artwork is original concept illustration, not an official logo, game screenshot, or evidence of a working preview. The files and exact image-generation prompts live in [design/assets](design/assets/) and [design/asset-prompts.txt](design/asset-prompts.txt).

Each selected game owns its setup instructions, routine availability, pack compatibility, and preview state. Switching games clears binding, access readiness, gameplay acknowledgment, progress, and any captured preview. A cleanup-failure block belongs to the application and survives game changes. No selection, card, image, or recognition result authorizes input.

## Workspace and states

Navigation contains Library, Session, Setup, Routines, Packs, and Settings. Session shows the selected game, routine, current input step, readiness, preview, and the existing 30-second supervised limit. Setup keeps manual sign-in, window selection, access checks, and routine selection distinct. No credentials form, focus stealing, or automatic Resume.

Dry run remains the default. Live input requires fresh setup and manual gameplay acknowledgment. Focus loss consumes live acknowledgment and requires a fresh manual gameplay check before another start. Stopping blocks a new run while release is in progress. Cleanup failure remains latched until the application is restarted after manual input-state checks. Future recognition states and care routines stay labelled as unavailable. No fictional task completions, reward counts, potion progress, or elapsed-time success claims appear.

Settings shows the dark appearance, privacy boundary, session limit, cleanup state, and the local Interface menu. The Interface menu offers 100–200% launcher-visual size options, retains source-pixel preview-reference coordinates, and never arms or starts input. Existing focus-loss and Stop rules still apply. Permissions remain in operating-system settings. The optional synthetic SDK check remains available through the command-line diagnostic and legacy Recognition Setup; the launcher does not simulate it. Keep process IDs, raw JSON, SDK configuration, and developer diagnostics out of the primary flow. Real window previews remain separate from promotional card artwork and must state whether content bounds are verified.

## Visual and accessibility rules

Use a near-black canvas, layered navy panels, violet primary actions, cyan highlights, large artwork, and restrained glow. Reference tokens: canvas `#0B0C13`, panel `#151725`, raised panel `#20233A`, text `#F5F6FF`, muted text `#A9AEC6`, violet `#8E5BF0`, cyan `#50DBF7`. Button text and hover states must meet AA contrast. Status always has text, not color alone.

Reference desktop width is 1240 px. At 1001 px and above, use the 270 px rail, three profile cards and two content columns. From 761–1000 px, retain the 270 px rail with two cards and one content column. From 621–760 px, use the 74 px rail, two cards and one content column. At 620 px and below, use the compact brand, horizontally scrollable navigation, one card and the sticky global Stop control; at 420 px, header text may wrap or ellipsize but Stop remains visible. The wide workspace remains capped at 1550 px. The existing hero and cards retain their 318 px and 265 px minimum heights, respectively, and their artwork uses `object-fit: cover`; this slice does not add a separate large-window crop or clamp rule. Navigation contracts on narrower windows and cards stack without overlapping controls. The design ribbon and global Stop stay visible when content scrolls. The navigation body scrolls independently with Stop pinned at the bottom, including short windows and 200% scaling. At 620 × 450, the library hero may contract to 250 px while retaining its profile text, badges and setup action. Preserve visible keyboard focus, accessible names, reduced-motion support, Escape and Cmd/Ctrl+. for Stop, and Cmd/Ctrl+, for Settings.

The optional preview-reference canvas uses CSS-pixel dimensions with a device-pixel-ratio backing store. Pointer coordinates derive from its live client rectangle and the native preview dimensions, so the metadata area stays accurate through zoom and resize. Redraw on wrapper, window and visual-viewport resize. It remains 16:9-clamped and preserves preview/game identity guards, draft handling, cleanup gates, and empty, capturing and error states.

## Integration boundary

The guarded Python engine remains the only native action path. The new launcher uses a three-method typed bridge for state, explicit commands and bounded in-memory previews. It opens no HTTP server, loads no remote resources, blocks navigation away from the bundled entry point, and rejects unregistered or dotted bridge method names. Native capture remains an explicit no-input action. The earlier Tk Recognition Setup remains available only through the legacy interface. Game-specific automation requires reviewed profiles, supported screen states, calibration, guarded actions, and native outcome evidence before a card can advertise it as supported. Current care routines, pack installation, longer sessions, assistive-technology acceptance, and hardware verification remain open in [plan.md](../plan.md).
