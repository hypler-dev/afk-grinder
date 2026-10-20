# Dependency and distribution evidence

Authority: [intent.md](../intent.md). Accepted roadmap: [BUILD.md](../BUILD.md). Current acceptance and CI receipts: [plan.md](../plan.md). Checked October 20, 2026.

## Project license

Original AFK Grinder code and documentation use the unchanged MIT text in [LICENSE](../LICENSE). It permits free use, modification and redistribution, including commercial redistribution, with its required notice. Its warranty and liability disclaimers apply to the extent permitted by law. This does not relicense dependencies, game assets or imported routines, or establish permission under game rules. No third-party gameplay pack, screenshot dataset, infographic or macro has been adopted.

## Locked recognition SDK

| Component | Version/source | Terms and current use |
| --- | --- | --- |
| MaaFw / MaaFramework | 5.14.3; commit `8963191215ca49d6b037802acd07d20a4213160a` | LGPL-3.0; optional local Python/shared-library SDK |
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

## Existing application and build runtime

The locked baseline includes PyObjC core/Cocoa/ApplicationServices/CoreText/Quartz/ScreenCaptureKit/CoreMedia 12.2.2 on Mac, PyInstaller 6.22.3 and hooks 2026.8, altgraph 0.17.5, packaging 26.3, setuptools 84.2.0, macholib 1.16.4 on Mac, and pefile/pywin32-ctypes on Windows. Exact versions and platform markers remain in uv.lock. PyInstaller's notice includes its distribution exception.

PyObjC's MIT license comes from official v12.2.2 commit `38cdf73fc049ef2d176973eff4ac8d5c76b0a34b`. Core and the six framework notices are byte-identical. ScreenCaptureKit/CoreMedia wheel metadata identifies MIT but contains no separate license file; their pinned upstream `pyobjc-framework-ScreenCaptureKit/License.txt` and `pyobjc-framework-CoreMedia/License.txt` were independently fetched and match the retained `licenses/PyObjC-12.2.2.txt` SHA-256 `0ca04b07928d4872b9d9bb22187ca0426dd8bfab08f26eada0999a71dc81aaff`. The common notice ships with the application. Its notice mentions libffi separately; that release's setup links external `-lffi` rather than containing a libffi-src tree. OS-provided libraries remain separate from copied libraries.

Source retains upstream Python, Tk, PyObjC, PyInstaller and recognition notices. Builds also copy their actual Python runtime license and installed baseline dependency notices into `legal/build-runtime` inside the application. The generated inventory describes installed build dependencies, not proof every package is bundled. SDK notices in source do not mean SDK binaries are in downloadable artifacts.

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
