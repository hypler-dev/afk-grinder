# Local desktop launcher bridge

Authority: [intent.md](../intent.md). The owner approved automatic Roblox binding and adopting the accepted dark game-library preview as the real application interface on October 20, 2026. This contract describes implementation work, not completed native acceptance. The Python engine remains the only input path. No remote content, account system, login automation or runtime LLM is involved.

## Boundary

The bundled frontend receives exactly three public methods: `get_state()`, `get_preview(preview_id)` and `command(name, payload)`. The WebView loads trusted application HTML/CSS/JavaScript and original local artwork only. No navigation to remote pages, arbitrary file access, command execution, generic Python evaluation or native-controller methods is exposed. Backend state is authoritative; the frontend never simulates readiness, captures, input or completion. Session state stays in memory.

The pinned pywebview 6.2.1 integration runs its utility workers for bridge injection and API-response delivery as daemon threads. A response waiting on a disposed native UI cannot retain the application after close. This does not alter input-worker lifetime: the runner remains non-daemon, and the existing controller close gate still waits for cancellation and input cleanup. The three-method dispatch allowlist and navigation guards remain in force.

`command` returns `{ "ok": true|false, "error": null|{"code": "...", "message": "..."}, "state": STATE }`. State polling uses `get_state()` approximately every 250 milliseconds while visible. Preview images are excluded from polling; fetch a bounded in-memory PNG only when `preview.id` changes. `get_preview(id)` returns `{ "id": id, "data_url": "data:image/png;base64,..." }` only for the current image, otherwise no image.

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
  "preview":{"phase":"empty","id":0,"width":0,"height":0,"content_verified":false,"region_kind":"none","area":null,"geometry":"none","error":null},
  "sdk":{"phase":"unchecked","message":"Recognition has not been checked."},
  "template":{"json":"...","valid":true,"error":"","name":"Supervised movement check","steps":3,"duration_ms":1000}
}
```

Binding phases: `searching`, `missing`, `bound`, `multiple`, `error`, `unsupported`. Candidate records contain only `{id,label}` for verified Roblox targets; unrelated titles, application names and paths are excluded. Exactly one verified candidate may bind automatically. Multiple candidates require `select_target`; native identity is revalidated. No operation steals focus.

Readiness phases: `unknown`, `ready`, `blocked`, `unavailable`. Safe issues explain required permissions without granting them. Foreground is checked by the engine during live execution; viewing the launcher is not itself a setup error.

Session phases: `idle`, `countdown`, `running`, `stopping`, `stopped`, `completed`, `error`, `cleanup_blocked`. Dry run is the default. `can_start` is computed by Python, including game support, valid template, idle/capture state and all live gates. Every live start attempt consumes acknowledgment. Stop and interruption consume acknowledgment. Cleanup failure remains global and cannot be cleared by any bridge command. No automatic start, arming, acknowledgment or resume occurs.

Preview phases: `empty`, `capturing`, `available`, `historical`, `checking`, `error`. Preview errors contain only allowlisted `{code,stage,error_type,message}`. Never expose raw exceptions, NSError descriptions, filenames, other window titles or pixels in diagnostics. Raw Mac window bounds remain unverified after a manual geometry check. `geometry` is `none`, `matched` or `historical`; it never establishes gameplay recognition or permission to act.

Parent-side capture failures distinguish `ipc_read`, `worker_exit` and `worker_deadline`, retaining only allowlisted codes and exception categories. A child frame is never accepted when native teardown exits unsuccessfully or exceeds its deadline. Launcher preparation reports `preview_geometry` or `preview_encoding`; encoding failure clears retained pixels, layout and calibration rather than leaving a usable preview state.

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
| `set_area` | `{"preview_id":1,"rect":{"x":0,"y":0,"width":1280,"height":720}}` | Store a validated image-bounded 16:9 physical-pixel rectangle as reference metadata |
| `reset_area` | `{}` | Clear area/geometry |
| `check_area` | `{"preview_id":1}` | Retain only area/source layout, discard old pixels, capture fresh and check exact layout plus freshness |
| `sdk_check` | `{}` | Optional synthetic SDK check; never game input |

The frontend owns route navigation and accessible visual controls only. Unsupported profiles show their concept artwork and details but expose no input, capture, routine or pack actions. The current Adopt Me routine is a short supervised input check; game care, pack installation, longer sessions and other-game automation remain unavailable.
