# Supervised macOS Adopt Me control test

Authority: [intent.md](../intent.md). Test only a short supervised session; sign into Roblox manually. Do not enter credentials into AFK Grinder.

## Before testing

The first corrected CI build is [run 39363752157](https://github.com/hypler-dev/afk-grinder/actions/runs/39363752157), source `76c3efbfcb7e846762602577769f2760d4d4991d`. Use that build or a later build confirmed to contain the same focus correction.

1. Download the appropriate Mac artifact from a successful [build run](https://github.com/hypler-dev/afk-grinder/actions/workflows/build.yml). Extract both the GitHub ZIP and the app archive. Record the source commit from `BUILD_INFO.json`. Do not use Mac artifacts from `6cde71e` or `980772a` for live input: their focus detector can remain cached. Use a build containing the Mac foreground-cache correction.
2. Verify `SHA256SUMS.txt`, then open `AFKGrinder.app`. Do not disable macOS security protections. Resolve any trust or input-permission decisions yourself through normal macOS controls. Quit other AFK Grinder copies and open this exact artifact from Finder; multiple copies share an application identifier and can cause macOS to launch a different copy. Unsigned build changes may require refreshing the two input permissions and restarting.
3. Before any live input, verify the running executable belongs to the extracted, checksum-verified artifact. In Terminal run `ps -axo pid=,comm= | grep '[A]FKGrinder.app/Contents/MacOS/AFKGrinder'`. Require exactly one result and compare its full path with this artifact's `AFKGrinder.app/Contents/MacOS/AFKGrinder`; stop if it points to another copy such as a local `dist` build. Confirm the adjacent `BUILD_INFO.json` source commit matches the selected successful CI run. Record that path and source with the test results.
4. In Adopt Me, stand on clear ground, close chat and menus, and dismiss incoming trade/purchase prompts. Do not use this test for purchases or trades.
5. In AFK Grinder, select Live input and refresh readiness. Missing Accessibility/Input Monitoring permission is a blocked test, not a pass. The app must not grant permissions itself.
6. Wait for native discovery to report ready. A uniquely verified Roblox window binds automatically while AFK Grinder stays foreground; no foreground-switch countdown is used. If no target is found, wait or use **Retry**. If multiple verified Roblox windows are listed, explicitly select the intended window. Automatic binding never arms input, starts a run, acknowledges gameplay, or resumes an interrupted run. Repeat discovery if Roblox restarts.

## Movement

Use the bundled input-check template first. It holds W for 250 ms, waits 500 ms, and holds S for 250 ms. Confirm manual sign-in/gameplay readiness, click Start, and switch to Roblox during the countdown. Observe both movements and that the avatar stops after each hold. A completed log alone does not prove the game consumed input.

If the movement is too small to judge, use a single 500 ms W hold from clear ground. Keep the test short and inspect the new position before another run. Mark movement inconclusive if a wall, scene change, menu, or camera angle hides the result.

## Focus-loss cancellation

Use a 2000 ms W hold followed by a 1000 ms wait and a 250 ms S hold, only from clear ground. Start, switch to Roblox during the countdown, then switch back to AFK Grinder while W is held. Verify a focus-loss stop is reported, the held input is released, and the later S action does not run. Refocusing Roblox must not resume the canceled workflow.

## Emergency stop

Use a single 2000 ms W hold. Start and switch to Roblox. While movement is active, hold physical Escape until the run stops. Verify the emergency-stop message, that movement ends before the full hold completes, and that movement does not resume. Escape may also open Roblox's own menu; close it manually before another test.

Test GUI Stop separately if needed. A failed release must be reported as a failure and block further live runs; do not retry until input state has been checked.

## Evidence

Record build/source commit, macOS version, architecture, permission readiness, and PASS/FAIL/INCONCLUSIVE for movement, focus-loss cancellation, Escape cancellation, and held-key cleanup. The actual Mac focus identity and UI result should agree. Do not publish account names, session data, private game screenshots, or other players' information. Windows and unattended gameplay remain separate tests.

The current CI candidate is `e59450857fceec52ce7317a370dca8c3b95dac50` from [run 39472952279](https://github.com/hypler-dev/afk-grinder/actions/runs/39472952279). All three exact-build permissions were refreshed and observed enabled; the reopened app reported native checks ready and automatically bound a unique Roblox target. Explicit capture and a foreground retry both failed at window selection, before the native filter stage. That bootstrap revision passed 199 tests and local frozen checks. The subsequent bounded window-selection correction passes 205 tests, including elevated no-capture bootstrap; its review, new CI, and verified native retry remain required. Neither set of checks establishes native capture or live-input acceptance.
