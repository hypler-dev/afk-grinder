# Third-party notices

AFK Grinder's original application code and documentation use the MIT License in [LICENSE](LICENSE). Third-party software and assets retain their own copyrights, licenses, and attribution requirements. MIT does not relicense those components.

## Recognition engine

The selected SDK is MaaFw 5.14.3, upstream MaaXYZ/MaaFramework tag v5.14.3, source commit `8963191215ca49d6b037802acd07d20a4213160a`.

- Source: https://github.com/MaaXYZ/MaaFramework/tree/8963191215ca49d6b037802acd07d20a4213160a
- Upstream license: GNU Lesser General Public License version 3, with its incorporated GNU GPL version 3.
- The application uses the SDK through its public Python/shared-library interfaces. It does not modify the SDK or restrict users from replacing/rebuilding it with an interface-compatible modified version.
- The SDK's custom-controller and cancellation APIs are being validated. No upstream Android agents, macro scripts, game artwork, OCR training models, or example plugins are authorized as executable routines.
- Native dependency source, license texts, copyright notices, hashes, and replacement/rebuild instructions are being inventoried before SDK-bearing binary artifacts are published. Package availability alone does not close this distribution gate. [Dependency evidence](docs/DEPENDENCIES.md) and [the notice manifest](licenses/provenance.json) identify inspected artifacts and remaining work.
- Default downloadable test bundles exclude MaaFw and optional recognition dependencies. CI-only SDK diagnostic bundles are not uploaded. Installing the source extra also installs the upstream MaaAgentBinary requirement; the application does not import, execute or redistribute those separate AGPL Android agents.

## Other dependencies

Python, Tcl/Tk, PyObjC, NumPy, strenum, packaging, and the PyInstaller runtime keep their upstream terms. uv.lock and the build's `legal/build-runtime/build-dependencies.json` record resolved/installed versions. Retained upstream texts are in `licenses/`; each build also copies its actual Python runtime and installed baseline dependency notices. Inventory does not prove runtime inclusion. PyInstaller's build-tool license has a distribution exception; it does not change AFK Grinder's project license.

## Game content and imports

No third-party Adopt Me screenshots, infographic, macro, recognition dataset, or gameplay artwork has been adopted as a resource pack. Public availability is not a redistribution license. New assets require source, permission/license, attribution, hashes, and validation before inclusion.

## Warranty and liability

AFK Grinder is provided without warranty under LICENSE. Use is at the user's risk, including account restrictions, lost game progress, failed automation, or unintended input. The authors and contributors disclaim liability as stated in LICENSE and to the extent applicable law permits. No disclaimer promises absolute immunity or grants permission under Roblox or an experience's rules.
