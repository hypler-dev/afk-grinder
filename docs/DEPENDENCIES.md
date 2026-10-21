# Dependency and distribution evidence

Authority: [intent.md](../intent.md). Accepted roadmap: [BUILD.md](../BUILD.md). Current acceptance and CI receipts: [plan.md](../plan.md). Checked October 20, 2026.

## Project license

Original AFK Grinder code and documentation use the unchanged MIT text in [LICENSE](../LICENSE). It permits free use, modification and redistribution, including commercial redistribution, with its required notice. Its warranty and liability disclaimers apply to the extent permitted by law. This does not relicense dependencies, game assets or imported routines, or establish permission under game rules. No third-party gameplay pack, screenshot dataset, infographic or macro has been adopted.

## Locked recognition SDK

| Component | Version/source | Terms and current use |
| --- | --- | --- |
| MaaFw / MaaFramework | 5.14.3; commit `8963191215ca49d6b037802acd07d20a4213160a` | LGPL-3.0; optional local Python/shared-library SDK |
| MaaUtils | `f8994a38ddc6858800dfea8a04e958a0adbfb184`; required MaaFramework submodule | LGPL-3.0; required native helper library |
| MaaDeps | v3.0.0; commit `d47e60dfabdbb7bf2a18b305404c889ea2a4bbc7` | Native recipes and notice inventory |
| MaaDeps vcpkg | `c5a15727ee70fddf0296f0d8aafc3f58916fefac` | Pinned component baseline; licenses vary |
| ONNX Runtime | 1.29.0 | MIT; local inference |
| OpenCV | 4.12.0, port revision 9 | Apache-2.0; artifact filename `libopencv_world4.4.12.0.dylib` |
| FastDeploy | recipe 1.0.7; source `e11935e4595360e7038573db1a7ab08dd0e096ec` | Apache-2.0 |
| Dawn | v20260817.213942 | BSD-style; transitive native dependency, not permission to enable GPU execution |
| ONNX | 1.22.0 | Apache-2.0; native dependency inventory |
| NumPy | 2.5.4 on current Python 3.12; 2.4.6 on Python 3.11 in uv.lock | BSD and bundled-component notices |
| StrEnum | 0.4.15 | MIT |
| MaaAgentBinary | 1.0.1; transitive upstream wheel requirement | Separate AGPL Android agents; never imported, executed or included in desktop artifacts |

Official SDK wheels exist for Windows x64 and Mac arm64/x64; Mac wheel tags indicate macOS 13+. These are package-availability facts, not verified minimum systems or measured hardware performance. ScreenCaptureKit has its separate API baseline. i5/8 GB and Apple Silicon remain test targets.

Sources: [pinned MaaFramework](https://github.com/MaaXYZ/MaaFramework/tree/8963191215ca49d6b037802acd07d20a4213160a), [MaaFw 5.14.3](https://pypi.org/project/MaaFw/5.14.3/), [pinned MaaDeps](https://github.com/MaaXYZ/MaaDeps/tree/d47e60dfabdbb7bf2a18b305404c889ea2a4bbc7), [MaaDeps release](https://github.com/MaaXYZ/MaaDeps/releases/tag/v3.0.0).

Inspected arm64 MaaFw wheel SHA-256: `1f7be844dd1b0dbdf8b361cb836cfc6b2611603bce40899a4bcb762b4bf49e9c`. Inspected `MaaDeps-arm64-osx.tar.xz` SHA-256: `407f07b5a98d91e66331058dd1ed50f2d95d93a4e9a1df4615c2b73ef1b5db67`. Both match official metadata. The MaaDeps archive supplied 89 retained notice files. [licenses/provenance.json](../licenses/provenance.json) records source paths and hashes; it inventories notices, not final runtime inclusion.

The pinned MaaFramework Git tree identifies [`source/MaaUtils`](https://github.com/MaaXYZ/MaaUtils/tree/f8994a38ddc6858800dfea8a04e958a0adbfb184) at the revision above; its tree has no nested submodules, but its CMake file requires separately supplied MaaDeps. The pinned MaaDeps tree identifies the [`microsoft/vcpkg`](https://github.com/microsoft/vcpkg/tree/c5a15727ee70fddf0296f0d8aafc3f58916fefac) submodule at the recorded baseline. MaaUtils' upstream LGPL text was fetched from its exact revision and byte-compared with retained `licenses/MaaFramework-LGPL-3.0.md`: both have SHA-256 `446e755fae55ff034bbb21be44670b5f116c2b2667947e7036f2bfe6632539a8`.

[SDK_REBUILD.md](SDK_REBUILD.md) documents the fixed four-archive source preparer, three pinned MaaDeps v3.0.0 binary prerequisites, safe extraction, and native-host-only replacement verifier. All three raw dependency archives pass size/SHA verification and safe inspection; the local 351-test source suite passes without skips; and the replacement-only synthetic worker rejects the installed unmodified SDK without its marker. All three jobs in [run 39516584326](https://github.com/hypler-dev/afk-grinder/actions/runs/39516584326) passed actual native source builds and compatible three-core replacement in private frozen copies, followed by SDK-free packaging. Their JSON receipts retain source/dependency pins, original and replacement hashes, the synthetic marker and read-only lifecycle result; both Mac receipts record seven internal SDK load paths and ad-hoc strict signature checks. Windows does not attest every transitive DLL load path. Complete dependency-source coverage, signed/clean-machine replacement and final distribution review remain open. This evidence does not remove the SDK publication block.

The current replacement verifier adds an original in-memory template match and a Windows self-loader snapshot with an explicit loaded/unobserved DLL partition. All three jobs passed [run 39531946057](https://github.com/hypler-dev/afk-grinder/actions/runs/39531946057) for corrected source `c7e02e4cfd13698b37d15da104e8df750073d5ad`. Receipt schema 2 retains only bundle-relative SDK paths and current file hashes. Windows observed eight eligible DLLs and explicitly lists three unobserved; both Macs retain seven internal paths. This strengthens the bounded synthetic experiment; it does not establish every lazy import or complete corresponding dependency source. Exact source and target-OS execution evidence remain in [plan.md](../plan.md). The historical run above predates these additions.

## Existing application and build runtime

The locked baseline includes PyObjC core/Cocoa/ApplicationServices/CoreText/Quartz/ScreenCaptureKit/CoreMedia 12.2.2 on Mac, PyInstaller 6.22.3 and hooks 2026.8, altgraph 0.17.5, packaging 26.3, setuptools 84.2.0, macholib 1.16.4 on Mac, and pefile/pywin32-ctypes on Windows. Exact versions and platform markers remain in uv.lock. PyInstaller's notice includes its distribution exception.

PyObjC's MIT license comes from official v12.2.2 commit `38cdf73fc049ef2d176973eff4ac8d5c76b0a34b`. Core and the six framework notices are byte-identical. ScreenCaptureKit/CoreMedia wheel metadata identifies MIT but contains no separate license file; their pinned upstream `pyobjc-framework-ScreenCaptureKit/License.txt` and `pyobjc-framework-CoreMedia/License.txt` were independently fetched and match the retained `licenses/PyObjC-12.2.2.txt` SHA-256 `0ca04b07928d4872b9d9bb22187ca0426dd8bfab08f26eada0999a71dc81aaff`. The common notice ships with the application. Its notice mentions libffi separately; that release's setup links external `-lffi` rather than containing a libffi-src tree. OS-provided libraries remain separate from copied libraries.

Source retains upstream Python, Tk, PyObjC, PyInstaller and recognition notices. Builds also copy their actual Python runtime license and installed baseline dependency notices into `legal/build-runtime` inside the application. The generated inventory describes installed build dependencies, not proof every package is bundled. SDK notices in source do not mean SDK binaries are in downloadable artifacts.

## Local replay and private OCR assets

Pillow 13.0.0 is pinned for reduced-resolution WebP/JPEG encoding. Its MIT-CMU notice, including bundled component notices, is retained in `licenses/Pillow-13.0.0.txt` with a hash in the notice inventory. The actual installed notice also ships through the build legal collector. Recording defaults off; compression does not authorize capture or input.

Private popup tests use English PaddleOCR model files from MaaCommonAssets commit `dabcd4681ac990dc4361de26416d986abd80e4aa`: the v3 English detector with v4 English recognizer and dictionary, as documented by upstream. Exact file sizes and SHA-256 values are pinned in `recognition/ocr_models.py`. The explicit developer fetch tool uses fixed HTTPS URLs and verifies every asset. The application performs no model downloads. Repository licensing is not treated as blanket approval for redistributing every model weight. Models remain ignored local data; `--with-popup-models` requires a private SDK build, and neither models nor SDK-bearing bundles enter default downloads. Their upstream weight/source/notice distribution review remains open.

## Local WebView launcher dependencies

The launcher pins pywebview 6.2.1 (BSD-3-Clause), Bottle 0.13.4 (MIT), proxy-tools 0.1.0 and typing_extensions 4.16.0 (Python Software Foundation license terms in the retained file). Mac adds PyObjC WebKit, Security and UniformTypeIdentifiers 12.2.2. The latter two framework wheels omit a separate notice; their official license files at the existing pinned PyObjC commit are byte-identical to `licenses/PyObjC-12.2.2.txt`. The WebKit wheel carries the same notice.

Windows resolves pythonnet 3.2.1 (MIT), clr_loader 0.3.1 (MIT), cffi 2.1.1 (MIT-0) and pycparser 3.11 (BSD-3-Clause). The legal collector retains their actual installed wheel license texts and metadata-declared license files, including pythonnet's AUTHORS.md. A fake-distribution regression verifies that declared AUTHORS is retained without copying unrelated files. The official Windows cffi wheel contains only its MIT-0 project license; its build statically includes the source archive's bundled `libffi_x86_x64` C files and `win64.obj`. Their MIT-style source-header notices are retained separately in `licenses/CFFI-2.1.1-Windows-libffi-notices.txt`, with original source-file hashes and archive provenance. The header's `libffi 2.00-beta` banner is not treated as verified upstream release identity. Package metadata alone does not prove every transitive native component's inclusion.

`proxy_tools-0.1.0.tar.gz` from official PyPI has SHA-256 `ccb3751f529c047e2d8a58440d86b205303cf0fe8146f784d1cbcd94f0a28010`. Its source header explicitly says BSD despite MIT setup metadata; it includes no license file. The retained upstream BSD notice is pinned to [commit ccd35a5](https://github.com/jtushman/proxy_tools/blob/ccd35a569b95bec271a59890780c7821756c548a/LICENSE.txt). This records the discrepancy rather than treating the metadata as a replacement copyright notice.

The pywebview wheel includes Microsoft WebView2 SDK 1.0.3856.49. Core/WinForms DLLs and all three architecture loader DLLs were byte-compared with the [official NuGet package](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.3856.49); every Microsoft DLL matched. Its BSD-style LICENSE and NOTICE are retained with hashes in `licenses/provenance.json`. The other two WebBrowserInterop DLLs are pywebview's legacy interop implementation, not Microsoft package files. The application forces the Edge Chromium adapter on Windows and never selects the legacy renderer. The separate browser runtime remains an OS prerequisite, with no bundled bootstrapper or automatic installation. See [Microsoft distribution guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution).

The launcher uses local `file://` assets, no HTTP server, remote page, font, telemetry or cloud model. Native navigation cancellation and a CSP protect the entry point. An additional exact method-name allowlist precedes pinned pywebview's dotted attribute resolver; limiting generated public API names alone would not enforce the boundary. This pinned adapter requires native source/frozen smoke checks; current evidence and any pending reruns are recorded in plan.md.

## SDK-bearing distribution gate

Default downloadable test bundles exclude MaaFw, MaaAgentBinary, NumPy and StrEnum. CI separately builds/checks an SDK diagnostic bundle, then overwrites it with the SDK-free prototype before packaging. `tools/package_build.py` rejects SDK-bearing output. Project/upstream notices accompany artifacts.

PyInstaller may retain MaaFw distribution metadata because the diagnostic checks its installed version. Metadata/license text alone contains no SDK implementation or native library and does not enable recognition. The diagnostic checks that the `maa` module is present before reporting SDK readiness; the packaging gate rejects its code/native libraries rather than harmless metadata.

Before distributing SDK-bearing applications:

1. Inventory actual shared libraries and notices on Windows x64 and both Macs; exclude unused Android agents, examples and plugins.
2. Include LGPL/GPL texts, prominent MaaFramework attribution and applicable component copyright/notice texts.
3. Provide complete corresponding MaaFramework source, pinned submodule/build/dependency recipes and equivalent source access appropriate to the distribution, with a verified retrieval/build procedure. An upstream link alone is not recorded as completed evidence.
4. Keep interface-compatible SDK replacement possible. Document the actual library paths and local rebuild/replacement procedure; impose no conflicting restriction on modification or reverse engineering for debugging changes. Validate frozen loader/signature behavior before claiming replacement works in downloadable Mac bundles.
5. Review final source/artifact contents and record evidence before removing the packaging block.

Source development and private diagnostic builds can proceed while this gate remains open. This inventory does not certify complete compliance, game compatibility, performance minima or production-release readiness.

`python -m tools.inventory_build --label TARGET --commit COMMIT --output build-evidence/sdk-inventory.json --require-sdk` reads an existing private diagnostic bundle without importing or executing its SDK. Its `sdk-inventory.v2` JSON records embedded modules, native files (including extensionless framework executables), internal path aliases, executable hashes and legal-file hashes. Paths are bundle-relative. A supplied target label and commit are provenance inputs, not independent operating-system or clean-source verification. Local output from a dirty checkout is diagnostic evidence only; exact-revision CI receipts establish the source association.

CI records this JSON before rebuilding the SDK-free download. The separate JSON artifact contains no SDK binaries or screen images. Successful inventory does not close corresponding-source, replacement, attribution or final artifact-review gates, and does not authorize removal of the SDK publication block.
