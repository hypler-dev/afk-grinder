# Private SDK source and replacement procedure

Authority: [intent.md](../intent.md). Distribution requirements and open gates: [DEPENDENCIES.md](DEPENDENCIES.md#sdk-bearing-distribution-gate). Current acceptance evidence: [plan.md](../plan.md).

This procedure covers a private macOS arm64 recognition build. It does not publish SDK binaries, install an application, grant macOS permissions, or establish complete corresponding-source coverage. The source-preparation tool supports Windows and macOS; the native rebuild and replacement below have been tested only on this Mac. Windows, Intel Mac, signed distribution and clean-machine replacement remain open.

## Prepare the pinned source chain

From the repository root, choose a new destination whose parent already exists:

```sh
python3 -m tools.fetch_sdk_sources --destination /private/tmp/afk-grinder-sdk-source
```

The fixed [sdk_sources.json](../tools/sdk_sources.json) is the source of truth for four official archives, their exact revisions, byte sizes, SHA-256 values and layout. The tool uses TLS-verifying HTTPS transport, verifies bytes before inspection, rejects links/special files/traversal/duplicate paths and limits total regular-file payload and member count. It retains the archives, manifest, upstream source/notices and `PROVENANCE.json`. Publication uses an exclusive native rename; an existing destination, including one created during preparation, is not replaced. Unsupported hosts/filesystems fail closed. It does not build or execute downloaded source and is never called by the application.

The resulting layout is:

```text
source/MaaFramework/
  source/MaaUtils/
    MaaDeps/
      vcpkg/
archives/
sdk_sources.json
PROVENANCE.json
```

MaaUtils is a pinned Framework submodule. Its tree has no further submodules, but `MaaUtils.cmake` includes the separately supplied MaaDeps CMake file. MaaDeps pins vcpkg. The preparer assembles this chain explicitly. Other Framework submodules are not used by the selected build flags and are not fetched.

## Supply the native build dependencies

The verified local experiment used CMake 4.4.3, Xcode 26.3 / AppleClang 17 and macOS 26.0 on arm64. CMake upstream requires at least 3.28. These are observed tools, not verified minimum supported systems.

The experiment uses the official prebuilt [MaaDeps v3.0.0 arm64 archive](https://github.com/MaaXYZ/MaaDeps/releases/download/v3.0.0/MaaDeps-arm64-osx.tar.xz). It is a **binary build prerequisite**, not a substitute for dependency source. Its 49,529,768 bytes and SHA-256 match official release metadata:

```text
407f07b5a98d91e66331058dd1ed50f2d95d93a4e9a1df4615c2b73ef1b5db67
```

```sh
SDK_ROOT=/private/tmp/afk-grinder-sdk-source
SDK_SOURCE="$SDK_ROOT/source/MaaFramework"
SDK_BUILD="$SDK_ROOT/build-arm64"
SDK_PREFIX="$SDK_SOURCE/source/MaaUtils/MaaDeps"

curl --disable --fail --location --proto '=https' --proto-redir '=https' \
  --max-time 120 --max-filesize 49529768 \
  --output "$SDK_ROOT/MaaDeps-arm64-osx.tar.xz" \
  https://github.com/MaaXYZ/MaaDeps/releases/download/v3.0.0/MaaDeps-arm64-osx.tar.xz
python3 - "$SDK_ROOT/MaaDeps-arm64-osx.tar.xz" "$SDK_PREFIX" <<'PY'
import hashlib
from pathlib import Path
import subprocess
import sys
archive = Path(sys.argv[1])
if archive.stat().st_size != 49529768:
    raise SystemExit("MaaDeps archive size did not match the pinned release.")
if hashlib.sha256(archive.read_bytes()).hexdigest() != "407f07b5a98d91e66331058dd1ed50f2d95d93a4e9a1df4615c2b73ef1b5db67":
    raise SystemExit("MaaDeps archive SHA-256 did not match the pinned release.")
subprocess.run(["tar", "-xJf", str(archive), "-C", sys.argv[2]], check=True)
PY
```

Do not continue after a failed verification command. The dependency archive supplies `vcpkg/installed/maa-arm64-osx` beside the pinned vcpkg source. Complete source coverage and reproducible builds for its native dependencies remain separate distribution work.

## Rebuild the three recognition libraries

For the recorded modified-library experiment, append this inert export to `source/MaaFramework/API/MaaFramework.cpp` inside the private source tree. It changes no existing input, capture or recognition function:

```cpp
// Synthetic loader probe for the private replacement experiment only.
extern "C" MAA_FRAMEWORK_API const char* AfkGrinderReplacementProbe()
{
    return "afk-grinder-sdk-replacement-v1";
}
```

Retain the original SDK version because the Python binding and application check compatibility with 5.14.3. The source patch and replacement hashes identify this experiment separately; it is not an unmodified upstream binary.

```sh
cmake -S "$SDK_SOURCE" -B "$SDK_BUILD" \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_OSX_ARCHITECTURES=arm64 \
  -DCMAKE_OSX_DEPLOYMENT_TARGET=13.0 \
  -DCMAKE_INSTALL_PREFIX="$SDK_ROOT/install-arm64" \
  -DMAA_HASH_VERSION=5.14.3 \
  -DENABLE_CCACHE=OFF \
  -DWITH_ADB_CONTROLLER=OFF \
  -DWITH_WIN32_CONTROLLER=OFF \
  -DWITH_MACOS_CONTROLLER=OFF \
  -DWITH_ANDROID_NATIVE_CONTROLLER=OFF \
  -DWITH_PLAYCOVER_CONTROLLER=OFF \
  -DWITH_GAMEPAD_CONTROLLER=OFF \
  -DWITH_LINUX_CONTROLLER=OFF \
  -DWITH_RECORD_CONTROLLER=OFF \
  -DWITH_REPLAY_CONTROLLER=OFF \
  -DWITH_DBG_CONTROLLER=OFF \
  -DWITH_CUSTOM_CONTROLLER=ON \
  -DWITH_MAA_AGENT=OFF \
  -DWITH_NODEJS_BINDING=OFF \
  -DWITH_QUICKJS_BINDING=OFF \
  -DBUILD_PICLI=OFF \
  -DBUILD_SAMPLE=OFF \
  -DBUILD_PIPELINE_TESTING=OFF \
  -DBUILD_DLOPEN_TESTING=OFF \
  -DBUILD_NODE_TEST=OFF \
  -DBUILD_MACOS_TEST=OFF \
  -DBUILD_LINUX_TEST=OFF
cmake --build "$SDK_BUILD" --target MaaFramework --parallel 2
```

This produces `libMaaFramework.dylib`, `libMaaUtils.dylib` and `libMaaCustomControlUnit.dylib` under `build-arm64/bin`. A deployment target flag alone does not establish runtime compatibility with that OS version.

## Replace libraries in a separate private app

First build a private SDK-bearing app using the locked build/recognition environment described in [README.md](../README.md#run-from-source). Synthetic OCR additionally requires explicitly fetched, verified private models through `tools/fetch_ocr_models.py`; see [DEPENDENCIES.md](DEPENDENCIES.md#local-replay-and-private-ocr-assets). Default downloads contain no SDK and cannot serve as replacement-test bundles.

```sh
python tools/build.py --with-recognition --with-popup-models
```

Use a separate copy. Close any previous test copy before modifying it. Do not overwrite the app used for live calibration, install this experimental copy, or grant it input/capture permissions.

```sh
SDK_COPY="$SDK_ROOT/replacement/AFKGrinder.app"
python3 - "$SDK_COPY" <<'PY'
from pathlib import Path
import shutil
import sys
target = Path(sys.argv[1])
if target.exists() or target.is_symlink():
    raise SystemExit("Replacement destination already exists; choose a new private copy.")
target.parent.mkdir()
shutil.copytree("dist/AFKGrinder.app", target, symlinks=True)
PY
```

The observed Mac layout uses physical files at `Contents/Frameworks/maa/bin/` and internal aliases under `Contents/Resources/maa/bin/`. Inspect the actual bundle; do not assume a Windows-style `_internal` directory. Replace the three physical core files while retaining their names and ABI. Keep the original bundled FastDeploy, ONNX Runtime, OpenCV and Dawn dependencies.

For this exact build, the CMake outputs contain absolute development RPATHs. Remove them from the copied replacements, then sign the changed libraries and app locally:

```sh
python3 - "$SDK_COPY" "$SDK_BUILD" "$SDK_PREFIX" <<'PY'
from pathlib import Path
import shutil
import subprocess
import sys
from tools.macos_bundle import stamp_unsigned_bundle_version
from tools.sdk_bundle import validate_recognition_bundle

bundle, build, prefix = map(Path, sys.argv[1:])
root = bundle.resolve(strict=True)
for name in ("libMaaFramework.dylib", "libMaaUtils.dylib", "libMaaCustomControlUnit.dylib"):
    target = (bundle / "Contents/Resources/maa/bin" / name).resolve(strict=True)
    if target.relative_to(root).as_posix() != f"Contents/Frameworks/maa/bin/{name}":
        raise SystemExit("Replacement target is not the expected physical bundle library.")
    shutil.copyfile(build / "bin" / name, target)
    subprocess.run(["install_name_tool", "-delete_rpath", str(prefix / "vcpkg/installed/maa-arm64-osx/lib"), str(target)], check=True)
    if name == "libMaaFramework.dylib":
        subprocess.run(["install_name_tool", "-delete_rpath", str(build / "bin"), str(target)], check=True)
    subprocess.run(["codesign", "--force", "--sign", "-", str(target)], check=True)
validate_recognition_bundle(bundle, "darwin")
stamp_unsigned_bundle_version(bundle, "0.2.0")
PY
```

For each copied dylib, require `lipo -archs` to report arm64, inspect `otool -L`, and require `otool -l` RPATHs to contain only `@loader_path` and `@executable_path`. Verify the marker with `nm -gU`. `codesign --verify --deep --strict "$SDK_COPY"` must pass. Ad-hoc signing is a local test step; it provides no notarization, production trust or permission grant, and may change the executable's signature bytes.

Run the frozen synthetic checks:

```sh
"$SDK_COPY/Contents/MacOS/AFKGrinder" --sdk-check
"$SDK_COPY/Contents/MacOS/AFKGrinder" --ui-smoke
```

For loader-path evidence, invoke the frozen `--sdk-worker --sdk-report NEW_REPORT_PATH` directly with `DYLD_PRINT_LIBRARIES=1` after removing inherited `DYLD_*` overrides and `MAAFW_BINARY_PATH`. The outer `--sdk-check` captures its child's stderr; tracing only the outer process misses the SDK loads. Require all three replacement libraries and the four bundled dependencies to load from the private copy, with no development SDK path. Keep trace output local. The worker is synthetic, CPU-only, and disables native input and SDK image/log persistence. The UI smoke uses a fake backend and synthetic OCR; no Screen Recording or input permissions are needed.

## Recorded evidence and remaining work

October 20, 2026: real retrieval verified all four pinned archives and 15,176 source files. The manually assembled native build inputs were compared against those same archives; the only changed archived file was the documented probe source. CMake built all three libraries. A separate copy of private app source `bc35b6c` loaded the marker and reported native SDK 5.14.3, passed frozen SDK checks, synthetic OCR and 28 layout checks, and passed ad-hoc deep strict verification. Dynamic loader output identified all seven SDK libraries inside the copy. No game input, capture or recording ran; the live test app was not replaced.

The source fetcher and race fix received fresh OpenAI Terra-xhigh read-only review. An independent OpenAI Luna reader verified actual replacement hashes, internal aliases, arm64, RPATHs, marker export, signatures and current-app identity. Runtime OCR/loader results remain controller-produced evidence rather than an independent native rerun. Local receipts are `/private/tmp/afk-grinder-sdk-rebuild/SOURCE_PREPARATION_VERIFICATION.json` and `REPLACEMENT_VERIFICATION.json`; no binaries, archives or user screenshots are committed.

This proves one compatible private arm64 modification and retrieval/build route. It does not prove arbitrary ABI changes, complete dependency source access, Windows/Intel replacement, signed distribution, installation, gameplay or final license compliance. All SDK-bearing publication and release gates remain closed.
