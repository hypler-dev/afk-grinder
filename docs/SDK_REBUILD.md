# Private SDK source-replacement procedure

Authority: [intent.md](../intent.md). Distribution gate: [DEPENDENCIES.md](DEPENDENCIES.md#sdk-bearing-distribution-gate). Current evidence: [plan.md](../plan.md).

This developer-only tooling supports a private frozen-copy experiment. It does not publish SDK binaries, install an application, grant macOS permissions, capture a window, send native input, or change the downloadable prototype. The verifier requires a matching host process: `macos-arm64` on arm64 macOS, `macos-x64` on x64 macOS, or `windows-x64` on Windows AMD64. A mismatched target label is rejected; physical hardware and emulation status are not independently attested.

## Prepare pinned sources

Run from the repository root. Choose a new destination whose parent already exists:

```sh
python3 -m tools.fetch_sdk_sources --destination /private/tmp/afk-grinder-sdk-source
```

`tools/sdk_sources.json` pins four official source archives, revisions, sizes, SHA-256 values and layout. The preparer verifies bytes before inspection, rejects unsafe paths, links, special files, traversal and duplicates, limits archive size/member count, and publishes by exclusive rename. It retains source archives, manifest, notices and provenance. It does not build or execute downloaded source.

The output contains `source/MaaFramework`, `archives/`, `sdk_sources.json` and `PROVENANCE.json`. MaaUtils is the pinned Framework submodule; MaaDeps supplies its separately pinned build recipe.

## Prepare binary build prerequisites

The native build also needs one official MaaDeps v3.0.0 archive. The repository manifest fixes target, URL, byte size and SHA-256 for all three labels:

| Label | Archive | Size | SHA-256 |
| --- | --- | ---: | --- |
| `macos-arm64` | `MaaDeps-arm64-osx.tar.xz` | 49,529,768 | `407f07b5a98d91e66331058dd1ed50f2d95d93a4e9a1df4615c2b73ef1b5db67` |
| `macos-x64` | `MaaDeps-x64-osx.tar.xz` | 53,935,236 | `794607ac2d45bae117fb97ba866ba43e1d7495d7f52410a90fc12a5c419fa0a4` |
| `windows-x64` | `MaaDeps-x64-windows.tar.xz` | 125,763,732 | `3638891ca4b9424808598ab917ef73d8811b235ef2dd2246e3af25edd416dfd6` |

Prepare one target in a new destination:

```sh
python3 - <<'PY'
from tools.sdk_build_dependencies import prepare_dependencies
prepare_dependencies("macos-arm64", "/private/tmp/afk-grinder-sdk-deps")
PY
```

Replace the label for another matching host. The helper downloads over HTTPS, verifies fixed size and SHA-256, safely inspects and extracts only the expected tree (`vcpkg`, `runtime`, `msbuild`, `maadeps.cmake`), rejects traversal, unsafe links, duplicate paths and extraction overwrite, then writes `PROVENANCE.json`. All three raw dependency archives have been verified and safely inspected. MaaDeps remains a binary build prerequisite; it is not corresponding dependency source or distribution approval.

## Run private replacement verifier

Use a clean committed checkout and build a private SDK-bearing diagnostic bundle with locked build and recognition extras. Default builds remain SDK-free. The verifier takes an existing bundle and writes evidence to a new location. Its output parents must already exist:

```sh
uv sync --locked --extra build --extra recognition
uv run --locked --extra build --extra recognition python tools/build.py --with-recognition
mkdir -p build-evidence
uv run --locked --extra build --extra recognition python -m tools.verify_sdk_replacement \
  --label macos-arm64 \
  --commit "$(git rev-parse HEAD)" \
  --bundle dist/AFKGrinder.app \
  --work build/sdk-source-replacement-macos-arm64 \
  --output build-evidence/sdk-replacement.json
```

Use Windows bundle path `dist/AFKGrinder` and label `windows-x64` in Git Bash on Windows; use `macos-x64` with `dist/AFKGrinder.app` on x64 macOS. `--work` and `--output` must not already exist and must stay outside the input bundle. The verifier requires CMake 3.28 or newer, pins MaaFramework 5.14.3, builds only the custom-controller configuration, and sets macOS deployment target 13.3. The 13.3 setting is build configuration, not proof of minimum supported macOS. These synthetic checks do not require or fetch OCR models.

The verifier adds a synthetic marker export to the temporary source tree, builds `MaaFramework`, `MaaUtils` and `MaaCustomControlUnit`, copies the frozen app to a separate private directory, replaces every matching core copy, and preserves each original hash in JSON evidence. Original executable, core-library and version-metadata hashes are checked before and after and must remain unchanged. The frozen synthetic worker must report SDK 5.14.3, the pinned source revision, CPU-only operation, no image/log persistence, no native input, cancellation success and the marker. It must also find an original in-memory 16×16 template at its exact expected position in a 96×64 synthetic frame. No game pixels are used. Mac checks require matching architecture, removal of absolute development RPATHs, only `@loader_path`/`@executable_path`, local ad-hoc signatures and deep strict verification. Mac loader tracing must show replaced cores and bundled dependencies loaded from the private copy.

On Windows, the replacement-only frozen worker observes its own loader metadata through `GetCurrentProcess`, `K32EnumProcessModules` and `GetModuleFileNameW`. It never opens another process or reads game memory. Microsoft documents the current-process handle and loaded-module path APIs in [EnumProcessModules](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-enumprocessmodules) and [GetModuleFileNameW](https://learn.microsoft.com/en-us/windows/win32/api/libloaderapi/nf-libloaderapi-getmodulefilenamew). Enumeration is bounded to 4,096 modules, each path to 32,767 characters and all path strings to 1,048,576 characters; failures or truncation reject the probe. Only direct DLLs in the copied `_internal/maa/bin/` directory are eligible for reporting. The expected set is bounded to 64 files, 128 MiB per file and 512 MiB total, with links, ambiguous names and unknown Maa libraries rejected. An expected basename loaded from outside its exact copied location fails the check. Unrelated OS/user paths are transient and never included in reports or errors.

Receipt schema version 2 adds `synthetic_template_match` to `sdk_report`, `windows_sdk_loads` and `loader_evidence_scope`. The Windows observation has its own schema version 1: `scope` is `synthetic-replacement-worker`; `loaded` contains sorted bundle-relative paths, sizes and SHA-256 hashes; `unobserved` explicitly lists expected files absent from this snapshot. The three replaced cores must be observed. The parent independently checks the exact partition and current file hashes. Mac receipts retain `mac_loaded_sdk_libraries` and use `null` for `windows_sdk_loads`. Strict worker JSON rejects duplicate keys, non-finite numbers and reports larger than 64 KiB. This is evidence for the bounded synthetic probe only. Optional or lazy imports may remain unobserved; that does not justify pruning them or claiming complete loader, source or distribution coverage.

The command prints pass only after these checks. The JSON receipt does not remove SDK publication, production signing, installation or permission gates.

## CI entry point

GitHub Actions runs the verifier only for manual dispatch with boolean input `verify_source_replacement=true`; the default is `false`. The optional upload contains only `build-evidence/sdk-replacement.json`. Normal push and pull-request builds still produce SDK-free downloadable test bundles.

```sh
gh workflow run build.yml --ref main -f verify_source_replacement=true
```

## Current evidence and open gates

All three jobs passed [CI run 39531946057](https://github.com/hypler-dev/afk-grinder/actions/runs/39531946057) for corrected source `c7e02e4cfd13698b37d15da104e8df750073d5ad`. Each rebuilt and replaced the three selected cores, verified the marker and original synthetic template match, preserved the original hashes, and produced SDK-free downloads. Receipt schema 2 binds all four source pins and the target binary prerequisite. Both Mac receipts retain seven internal library paths and ad-hoc strict signature checks. The earlier `39531392073` run found a Windows-host path bug in the new Mac test fixture; only that fixture and its evidence note changed before the passing retry. Runtime checks were not weakened.

The Windows snapshot records eight loaded files from `_internal/maa/bin/`: the three Maa cores, `DirectML.dll`, `fastdeploy_ppocr_maa.dll`, `onnxruntime_maa.dll`, `opencv_world4_maa.dll` and `webgpu_dawn_maa.dll`. Its explicit unobserved set is `ViGEmClient.dll`, `dxcompiler.dll` and `dxil.dll`. Loaded core hashes match the rebuilt replacements; other observed hashes and sizes match the separate pre-replacement inventory. Presence of a library does not imply use of its accelerator. The SDK resources still require CPU configuration. This one snapshot does not cover every lazy import and is not a basis for pruning unobserved dependencies.

All nine outer GitHub ZIPs and their flat payloads are preserved at `/private/tmp/afk-grinder-ci-39531946057`. Controller and fresh independent OpenAI Luna static audits pass source/version, SDK-free app contents, module/version bytecode, web assets, notices, architecture, Mac signatures and replacement-receipt relationships. Receipt hashes and exact artifact counts are recorded in [plan.md](../plan.md). No downloaded application was launched or installed. The local corrected source suite passes 441 tests without skips. This audit is independent static verification of CI evidence, not an independent native rerun.

All three jobs passed [CI run 39516584326](https://github.com/hypler-dev/afk-grinder/actions/runs/39516584326) for source `1c1e51776431e928132e2b6c37a39cf7af72b7c9`. Each rebuilt and replaced the three selected cores in a private frozen copy, passed the replacement-marker/read-only lifecycle check and preserved the original executable/core/version hashes. Both Macs recorded seven SDK libraries loaded from inside the copy and passed local ad-hoc deep strict signature verification. The Windows receipt does not attest every transitive DLL load path. Normal SDK-free rebuild, packaged checks and all nine application/inventory/replacement uploads passed afterward. The optional artifacts contain JSON only, not source SDK binaries.

The downloaded replacement receipts pass controller checks against all four source pins and the matching binary-prerequisite manifest. All three raw MaaDeps archives also passed fixed size/SHA verification and safe inspection locally; the local 351-test source suite passed without skips; the synthetic worker correctly rejected the installed unmodified SDK when its replacement marker was required. Earlier manual arm64 source build/replacement remains separate historical evidence. This proves one compatible modification on the three CI hosts, not arbitrary ABI changes, native OCR accuracy or gameplay.

Current private candidate `bc35b6c` and calibration app remain unchanged. Screen Recording approval, native gameplay/calibration evidence, complete corresponding-source and license review, signed distribution, installation and release gates remain open. SDK-bearing publication remains blocked.
