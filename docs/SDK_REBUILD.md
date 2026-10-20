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

Use Windows bundle path `dist/AFKGrinder` and label `windows-x64` in Git Bash on Windows; use `macos-x64` with `dist/AFKGrinder.app` on x64 macOS. `--work` and `--output` must not already exist and must stay outside the input bundle. The verifier requires CMake 3.28 or newer, pins MaaFramework 5.14.3, builds only the custom-controller configuration, and sets macOS deployment target 13.3. The 13.3 setting is build configuration, not proof of minimum supported macOS. This synthetic marker check does not require or fetch OCR models.

The verifier adds a synthetic marker export to the temporary source tree, builds `MaaFramework`, `MaaUtils` and `MaaCustomControlUnit`, copies the frozen app to a separate private directory, replaces every matching core copy, and preserves each original hash in JSON evidence. Original executable, core-library and version-metadata hashes are checked before and after and must remain unchanged. The frozen synthetic worker must report SDK 5.14.3, the pinned source revision, CPU-only operation, no image/log persistence, no native input, cancellation success and the marker. Mac checks require matching architecture, removal of absolute development RPATHs, only `@loader_path`/`@executable_path`, local ad-hoc signatures and deep strict verification. Mac loader tracing must show replaced cores and bundled dependencies loaded from the private copy; the Windows receipt does not attest every transitive DLL load path.

The command prints pass only after these checks. The JSON receipt does not remove SDK publication, production signing, installation or permission gates.

## CI entry point

GitHub Actions runs the verifier only for manual dispatch with boolean input `verify_source_replacement=true`; the default is `false`. The optional upload contains only `build-evidence/sdk-replacement.json`. Normal push and pull-request builds still produce SDK-free downloadable test bundles.

```sh
gh workflow run build.yml --ref main -f verify_source_replacement=true
```

## Current evidence and open gates

The new automated native rebuild/replacement verifier has not yet produced a positive run. Current evidence: all three raw MaaDeps archives pass fixed size/SHA verification and safe inspection; the full 351-test source suite passes; the synthetic worker correctly rejects the original SDK when its replacement marker is required. Prior local arm64 manual source build/replacement remains historical evidence only. It does not prove that all three targets source-build successfully.

Current private candidate `bc35b6c` and calibration app remain unchanged. Screen Recording approval, native gameplay/calibration evidence, complete corresponding-source and license review, signed distribution, installation and release gates remain open. SDK-bearing publication remains blocked.
