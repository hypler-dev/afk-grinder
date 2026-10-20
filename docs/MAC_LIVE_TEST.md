# Supervised macOS Adopt Me control test

Authority: [intent.md](../intent.md). Test only a short supervised session; sign into Roblox manually. Do not enter credentials into AFK Grinder.

## Before testing

The first corrected CI build is [run 39363752157](https://github.com/hypler-dev/afk-grinder/actions/runs/39363752157), source `76c3efbfcb7e846762602577769f2760d4d4991d`. Use that build or a later build confirmed to contain the same focus correction.

1. Download the appropriate Mac artifact from a successful [build run](https://github.com/hypler-dev/afk-grinder/actions/workflows/build.yml). Extract both the GitHub ZIP and the app archive. Record the source commit from `BUILD_INFO.json`. Do not use Mac artifacts from `6cde71e` or `980772a` for live input: their focus detector can remain cached. Use a build containing the Mac foreground-cache correction.
2. Verify `SHA256SUMS.txt`, then open `AFKGrinder.app`. Do not disable macOS security protections. Resolve any trust or input-permission decisions yourself through normal macOS controls. Quit other AFK Grinder copies and open this exact artifact from Finder; multiple copies share an application identifier and can cause macOS to launch a different copy. Unsigned build changes may require refreshing the two input permissions and restarting.
3. Before any live input, verify the running executable belongs to the extracted, checksum-verified artifact. In Terminal run `ps -axo pid=,ppid=,args= | grep '[A]FKGrinder.app/Contents/MacOS/AFKGrinder'`. Require exactly one GUI application process for the artifact. A child with the same executable path, that GUI process as its parent, and arguments `-B -S -I -c from multiprocessing.resource_tracker import main;main(<descriptor>)` is an expected Python resource tracker, not another GUI. Do not exempt other unexplained processes. Compare the GUI process path with this artifact's `AFKGrinder.app/Contents/MacOS/AFKGrinder`, then confirm the adjacent `BUILD_INFO.json` source commit matches the selected successful CI run. Record that path and source with the test results.
4. In Adopt Me, stand on clear ground, close chat and menus, and dismiss incoming trade/purchase prompts. Do not use this test for purchases or trades.
5. In AFK Grinder, select Live input and refresh readiness. Missing Accessibility/Input Monitoring permission is a blocked test, not a pass. The app must not grant permissions itself.
6. Wait for native discovery to report ready. A uniquely verified Roblox window binds automatically while AFK Grinder stays foreground; no foreground-switch countdown is used. If no target is found, wait or use **Retry**. If multiple verified Roblox windows are listed, explicitly select the intended window. Automatic binding never arms input, starts a run, acknowledges gameplay, or resumes an interrupted run. Repeat discovery if Roblox restarts.

## Movement

Use the bundled input-check template first. It holds W for 250 ms, waits 500 ms, and holds S for 250 ms. Confirm manual sign-in/gameplay readiness, click Start, and switch to Roblox during the countdown. Observe both movements and that the avatar stops after each hold. A completed log alone does not prove the game consumed input.

If the movement is too small to judge, use a single 500 ms W hold from clear ground. Keep the test short and inspect the new position before another run. Mark movement inconclusive if a wall, scene change, menu, or camera angle hides the result.

## Focus-loss cancellation

Use a 2000 ms W hold followed by a 1000 ms wait and a 250 ms S hold, only from clear ground. Start, switch to Roblox during the countdown, then switch to another application while W is held. The launcher displays the generic result `Run stopped.`; that message alone does not identify the cause. Correlate it with the observed foreground switch, movement stopping before the hold ends, and the later S action not running. Refocusing Roblox must not resume the canceled workflow. A run that completes before the switch is inconclusive.

## Emergency stop

Use a single 2000 ms W hold. Start and switch to Roblox. While movement is active, hold physical Escape until the run stops. Correlate the launcher's generic `Run stopped.` result with the physical key press, movement ending before the full hold completes, and no movement resuming. Escape during the countdown does not establish release of an actively held movement key. Escape may also open Roblox's own menu; close it manually before another test.

Test GUI Stop separately if needed. A failed release must be reported as a failure and block further live runs; do not retry until input state has been checked.

## Evidence

Record build/source commit, macOS version, architecture, permission readiness, and PASS/FAIL/INCONCLUSIVE for movement, focus-loss cancellation, Escape cancellation, and held-key cleanup. The actual Mac focus identity and UI result should agree. Do not publish account names, session data, private game screenshots, or other players' information. Windows and unattended gameplay remain separate tests.

The current CI candidate is `c35a02fb5bfc32ecf37dcc2b1912bf751b2620fa` from [run 39475465316](https://github.com/hypler-dev/afk-grinder/actions/runs/39475465316). All three exact-build permissions were refreshed and observed enabled; the reopened app reported native checks ready and automatically bound a unique Roblox target. Explicit capture succeeded with the correct non-black Roblox window isolated in a private in-memory preview; the runtime filter, screenshot, pixel conversion, child exit, and PNG publication checks passed. Raw window bounds remain unverified. Do not treat this preview as calibration or M1 geometry acceptance.

On macOS 26 arm64, a supervised dry run started through the app's public UI reached `completed`. A separate supervised live run, with Roblox foreground and the operator's movement keys untouched, held S for 2000 ms, waited 1000 ms, then held W for 250 ms. Visual inspection showed actual world/avatar displacement and a stationary scene afterward; the app separately reported `Run completed.` without a cleanup-error banner. Movement and normal-completion cleanup pass for this bounded run. The owner's earlier movement report was retracted as possible manual input and is not acceptance evidence.

A first two-second focus test completed before a confirmed switch and remains inconclusive. A five-second S hold followed by a 1000 ms wait and 250 ms W hold was then used for the stop tests. Focus loss produced an early `Run stopped.`, a read-only foreground probe recorded Roblox losing and regaining focus, and the owner confirmed movement stopped on the switch and did not resume on return. Physical Escape separately produced `Run stopped.` while Roblox remained foreground. The owner noted Roblox's own menu opening; later visual observations showed the menu closed and the avatar stationary while the app remained stopped. Focus-loss and physical Escape cancellation, functional held-key cleanup, and no-resume pass for these supervised runs. These are visual/user observations correlated with app state, not app recognition of gameplay. Tests ended with Dry run selected, Live input off, and no active workflow. No game pixels were persisted. Windows live input, calibration, broader platform acceptance, and unattended use remain unverified.
