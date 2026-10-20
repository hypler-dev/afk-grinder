# Local desktop launcher bridge

Authority: [intent.md](../intent.md). The owner approved automatic Roblox binding and adopting the accepted dark game-library preview as the real application interface on October 20, 2026. This contract describes implementation work, not completed native acceptance. The Python engine remains the only input path. No remote content, account system, login automation or runtime LLM is involved.

## Boundary

The bundled frontend receives exactly three public methods: `get_state()`, `get_preview(preview_id)` and `command(name, payload)`. The WebView loads trusted application HTML/CSS/JavaScript and original local artwork only. No navigation to remote pages, arbitrary file access, command execution, generic Python evaluation or native-controller methods is exposed. Backend state is authoritative; the frontend never simulates readiness, captures, input or completion. Replay settings and bounded session/frame metadata are exposed in state; encoded frame bytes are returned only through an explicit replay-frame preview request.

The pinned pywebview 6.2.1 integration runs its utility workers for bridge injection and API-response delivery as daemon threads. A response waiting on a disposed native UI cannot retain the application after close. This does not alter input-worker lifetime: the runner remains non-daemon, and the existing controller close gate still waits for cancellation and input cleanup. The three-method dispatch allowlist and navigation guards remain in force.

`command` returns `{ "ok": true|false, "error": null|{"code": "...", "message": "..."}, "state": STATE }`. State polling uses `get_state()` approximately every 250 milliseconds while visible. Preview images are excluded from polling. `get_preview(preview_id)` accepts either the current integer preview ID or exactly `{ "replay_frame_id": "opaque-32-hex-id" }`; the first returns `{ "id": integer, "data_url": "data:image/png;base64,..." }` for the current bounded PNG. The second returns `{ "frame_id": opaque-id, "data_url": "data:image/webp;base64,..." }` or the JPEG equivalent for the exact frame currently cached after an explicit `replay_frame` request. Invalid, stale, unselected, or closed requests return no image.

## State version 1

```json
{
  "schema_version": 1,
  "app": {"version":"0.2.0","commit":"development","platform":"macos-arm64","limit_seconds":30,"countdown_seconds":3},
  "games": [
    {"id":"adopt","name":"Adopt Me","genre":"Social roleplay","supported":true,"art":"assets/pet-world.png"},
    {"id":"bee","name":"Bee Swarm Simulator","genre":"Collection adventure","supported":false,"art":"assets/bee-fields.png"},
    {"id":"blox","name":"Blox Fruits","genre":"Action adventure","supported":false,"art":"assets/ocean-adventure.png"}
  ],
  "game_id":"adopt",
  "mode":"dry",
  "binding":{"phase":"searching","label":"","message":"Looking for Roblox.","selected_id":null,"candidates":[]},
  "readiness":{"phase":"unknown","issues":[]},
  "session":{"phase":"idle","message":"Ready for a dry run.","can_start":true,"acknowledged":false,"input_locked":false,"cleanup_failed":false},
  "preview":{"phase":"empty","id":0,"width":0,"height":0,"content_verified":false,"region_kind":"none","area":null,"geometry":"none","calibration_method":"none","error":null},
  "sdk":{"phase":"unchecked","message":"Recognition has not been checked."},
  "popup":{"phase":"idle","state":"unknown","message":"Calibrate content before checking popups.","busy":false,"can_check":false,"can_resolve":false,"allow_reconnect":false},
  "replay":{"settings":{"enabled":false,"retention_days":7,"image_format":"webp","max_width":960,"quality":60,"interval_seconds":2,"max_bytes":2147483648},"phase":"loading","sessions":[],"frames":[],"frame":null},
  "template":{"json":"...","valid":true,"error":"","name":"Supervised movement check","steps":3,"duration_ms":1000}
}
```

Binding phases: `searching`, `missing`, `bound`, `multiple`, `error`, `unsupported`. Candidate records contain only `{id,label}` for verified Roblox targets; unrelated titles, application names and paths are excluded. Exactly one verified candidate may bind automatically. Multiple candidates require `select_target`; native identity is revalidated. No operation steals focus.

Readiness phases: `unknown`, `ready`, `blocked`, `unavailable`. Safe issues explain required permissions without granting them. Foreground is checked by the engine during live execution; viewing the launcher is not itself a setup error.

Session phases: `idle`, `countdown`, `running`, `stopping`, `stopped`, `completed`, `error`, `cleanup_blocked`. Dry run is the default. `can_start` is computed by Python, including game support, valid template, idle/capture state and all live gates. Every live start attempt consumes acknowledgment. Stop and interruption consume acknowledgment. Cleanup failure remains global and cannot be cleared by any bridge command. No automatic start, arming, acknowledgment or resume occurs.

Preview phases: `empty`, `capturing`, `available`, `historical`, `checking`, `error`. Preview errors contain only allowlisted `{code,stage,error_type,message}`. Never expose raw exceptions, NSError descriptions, filenames, other window titles or pixels in diagnostics. Raw Mac window bounds remain unverified after a manual geometry check. `geometry` is `none`, `matched` or `historical`; `calibration_method` is `none` or `manual`. It never establishes gameplay recognition or permission to act. `check_area` requires exact `attested: true`; arbitrary aspect ratios are allowed and pixels are not stretched.

Popup phases are `idle`, `checking`, `result`; popup states include `bank_reward`, `disconnected`, `protected`, `unknown`, `blocked`, `verifying`, `popup_dismissed`, and `reconnect_requested`. `popup_check` is read-only. `popup_resolve` is allowed only for a stable bank reward or, with `allow_reconnect: true`, a stable known reconnectable dialog. It performs one bounded click and verifies disappearance; no login, purchase, trade, unknown-screen action, auto-resume, or stale-target reuse is permitted.

Replay is opt-in and off by default. `replay_settings` accepts the complete settings object: `enabled` is boolean; `retention_days` is integer 1–365; `image_format` is `webp` or `jpeg`; `max_width` is integer 320–1920; `quality` is integer 30–85; `interval_seconds` is integer 1–30; and `max_bytes` is integer 100 MiB–20 GiB. `replay_select`, `replay_frame`, `replay_delete`, `replay_older`, and `replay_sessions` operate on opaque IDs and bounded pages. Session pages cap at 100 records and frame pages at 4096 records. Replay state exposes settings plus session/frame metadata and IDs, never paths or frame data URLs. The recorder may queue a raw in-memory crop; the store applies privacy before encoding or disk write. Login, unknown, restricted, and currently unclassified gameplay frames are opaque placeholders; purchase and trade frames are blurred before encoding.

After an allowlisted response, verification requires two fresh negative observations in which the old dialog is no longer recognized. A changed or new screen is reported as unknown; `popup_dismissed` or `reconnect_requested` does not assert gameplay, safety, or successful reconnection.

Parent-side capture failures distinguish `ipc_read`, `worker_exit` and `worker_deadline`, retaining only allowlisted codes and exception categories. A child frame is never accepted when native teardown exits unsuccessfully or exceeds its deadline. Launcher preparation reports `preview_geometry` or `preview_encoding`; encoding failure clears retained pixels, layout and calibration rather than leaving a usable preview state.

An expired manual-calibration capture reports code `stale` at `capture_freshness` (already expired at IPC receipt), `worker_exit_freshness` (expired by successful native teardown), or `preview_freshness` (expired only by controller consumption, or detailed timing unavailable). The parent records the two intermediate timestamps locally; neither timestamp nor numerical timing is exported or persisted. The active ScreenCaptureKit query uses `excludeDesktopWindows=true` and `onScreenWindowsOnly=true`; fresh pre/post-discovery checks still require target identity, bundle, window/layer, on-screen state, display, bounds and scale agreement. The 0.5-second bound and source capture timestamp remain unchanged. An optional fixed `capture_expiry_stage` diagnostic may identify `screenshot`, `pixel_conversion`, or `frame_validation` only after the parent proves staleness; it never exports raw timings, exception text or pixels. An exact-layout mismatch instead reports `geometry` at `preview_geometry`; all failures clear calibration and authorize no input.

## Commands

All names and payload keys are allowlisted. Unknown or malformed input is rejected before mutation. Mutations that conflict with active input or cleanup are rejected. Stop is always available and has priority over ordinary mutations.

| Name | Payload | Meaning |
| --- | --- | --- |
| `select_game` | `{"game_id":"adopt"}` | Select a known profile; clear target/setup/ack/preview; preserve cleanup latch |
| `set_mode` | `{"mode":"dry"}` or `{"mode":"live"}` | Change mode while idle; clear acknowledgment |
| `refresh_targets` | `{}` | Retry automatic discovery without changing foreground |
| `select_target` | `{"target_id":"opaque-current-id"}` | Choose one current verified Roblox candidate |
| `refresh_readiness` | `{}` | Refresh native permission checks without prompting |
| `set_ack` | `{"acknowledged":true}` or `false` | Explicit manual sign-in/gameplay/chat check; never generated by discovery; false revokes it |
| `set_template` | `{"json":"version-1 JSON"}` | Validate with the existing bounded declarative template parser |
| `start` | `{}` | Start the current template in the stored mode; live has existing 3-second manual switch and 30-second cap |
| `stop` | `{}` | Cancel input, consume acknowledgment and release held inputs |
| `capture` | `{}` | Capture the selected Roblox window in memory, while input is stopped |
| `clear_preview` | `{}` | Cancel preview and discard pixels, area and geometry |
| `set_area` | `{"preview_id":1,"rect":{"x":0,"y":0,"width":640,"height":360}}` | Store a validated arbitrary-aspect physical-pixel rectangle as reference metadata |
| `reset_area` | `{}` | Clear area/geometry |
| `check_area` | `{"preview_id":1,"attested":true}` | Require strict manual content attestation, retain only area/source layout, discard old pixels, capture fresh and check exact layout plus freshness |
| `sdk_check` | `{}` | Optional synthetic SDK check; never game input |
| `popup_check` | `{}` | Run bounded local allowlist recognition without input |
| `popup_resolve` | `{}` | Perform one supervised allowlisted response, then verify disappearance |
| `set_reconnect` | `{"enabled":true}` | Opt in to known reconnectable-dialog response; never logs in or resumes |
| `replay_settings` | `{"settings":{...}}` | Explicitly enable or configure private local replay |
| `replay_select` / `replay_frame` / `replay_delete` | `{"session_id":"..."}` / `{"frame_id":"..."}` | Select, fetch, or delete opaque replay records |
| `replay_older` / `replay_sessions` | `{"session_id":"..."}` / `{"older":true}` | Request bounded older frame/session pages |

The frontend owns route navigation and accessible visual controls only. Unsupported profiles show their concept artwork and details but expose no input, capture, routine or pack actions. The current Adopt Me routine is a short supervised input check; game care, pack installation, longer sessions and other-game automation remain unavailable.
