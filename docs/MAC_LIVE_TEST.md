# Supervised macOS Adopt Me control test

Authority: [intent.md](../intent.md). Test only a short supervised session; sign into Roblox manually. Do not enter credentials into AFK Grinder.

## Before testing

1. Download the appropriate Mac artifact from a successful [build run](https://github.com/hypler-dev/afk-grinder/actions/workflows/build.yml). Extract both the GitHub ZIP and the app archive. Record the source commit from `BUILD_INFO.json`.
2. Verify `SHA256SUMS.txt`, then open `AFKGrinder.app`. Do not disable macOS security protections. Resolve any trust or input-permission decisions yourself through normal macOS controls.
3. In Adopt Me, stand on clear ground, close chat and menus, and dismiss incoming trade/purchase prompts. Do not use this test for purchases or trades.
4. In AFK Grinder, select Live input and refresh readiness. Missing Accessibility/Input Monitoring permission is a blocked test, not a pass. The app must not grant permissions itself.
5. Click **Bind Roblox after 3 seconds**, then manually switch to Roblox during the three-second countdown. Return to AFK Grinder and confirm a Roblox target is bound. Repeat binding if Roblox restarts.

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
