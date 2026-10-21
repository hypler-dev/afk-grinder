# Direct SDK native notice traceability

Authority: [intent.md](../intent.md), BUILD milestone 0. Current execution evidence: [plan.md](../plan.md). The [SDK distribution gate](DEPENDENCIES.md#sdk-bearing-distribution-gate) remains closed.

This developer-only audit connects the selected shared libraries in a private diagnostic bundle to explicit component identities, retained notice bytes and pinned source/build-recipe members. It is a traceability check, not a legal compliance verdict, complete transitive source inventory or authorization to publish SDK binaries.

## Evidence and limits

The reviewed mapping is [tools/sdk_native_provenance.json](../tools/sdk_native_provenance.json). Its reference is the exact source `c7e02e4cfd13698b37d15da104e8df750073d5ad` SDK inventories from [run 39531946057](https://github.com/hypler-dev/afk-grinder/actions/runs/39531946057). The same group identities match the preceding three-target run. This historical reference is reported separately from the current build commit, which must exactly match the supplied inventory. Later builds may reuse the mapping only while every declared group, alias, size and hash still matches.

| Target | Direct SDK content groups | Full logical paths, including aliases |
| --- | ---: | ---: |
| macos-arm64 | 7 | 24 |
| macos-x64 | 7 | 24 |
| windows-x64 | 11 | 11 |

Each entry lists its complete alias set, size and SHA-256. The auditor rejects missing, unknown or changed SDK groups rather than assigning components from filenames. Groups containing a `maa/bin` path and orphan Maa-named native aliases are within the audit domain. Other Python, WebView and OS runtime groups remain outside this report; their exclusion is counted, not treated as complete dependency coverage.

A component's `source_evidence` deliberately distinguishes:

- `pinned-source-archive`: the selected core has a source archive and a checked build member. Dependencies still need their own coverage.
- `recipe-only`: a checked recipe identifies upstream inputs; those recipe bytes are not the dependency's full corresponding source.
- `vendor-binary-source-unresolved`: vendor/package origin is known, but source correspondence or availability is unresolved.

The four source archives must match the existing fixed source manifest. Recipe members are read as bounded data from those verified archives, without extraction or execution. Notice bytes must match `licenses/provenance.json`, the retained source file and every required legal-file alias in the actual bundle inventory. The source, prerequisite and mapping JSON are preserved byte-for-byte on Windows/macOS checkouts through `.gitattributes`.

## Windows vendor/package origins

[SDK_WINDOWS_ORIGINS.json](SDK_WINDOWS_ORIGINS.json) records static byte comparisons for four Windows DLLs. Each matches the pinned Windows MaaDeps runtime and the selected original package member, including exact size and SHA-256. The three original packages also match SHA-512 values from the pinned MaaDeps/vcpkg recipes.

| Native file | Original artifact | Retained notices and unresolved limits |
| --- | --- | --- |
| `DirectML.dll` | [Microsoft.AI.DirectML 1.15.4](https://www.nuget.org/packages/Microsoft.AI.DirectML/1.15.4) | Microsoft DirectML terms; this binary is not relicensed under project MIT |
| `ViGEmClient.dll` | [vgamepad 0.1.0 source archive](https://pypi.org/project/vgamepad/0.1.0/) | Both vgamepad's notice and a pinned upstream ViGEmClient MIT notice; the exact revision that built the DLL is unresolved |
| `dxcompiler.dll` | [DXC v1.9.2602.24 binary release](https://github.com/microsoft/DirectXShaderCompiler/releases/tag/v1.9.2602.24) | Full source notice plus the binary archive's LLVM, MIT and Microsoft license files; mixed terms require review |
| `dxil.dll` | Same DXC archive | All four DXC notice files are retained; binary/source correspondence and redistribution review remain open |

The source DXC notice alone is not substituted for the binary archive's separate Microsoft terms. The ViGEmClient upstream notice revision `b66d02d57e32cc8595369c53418b843e958649b4` is a notice pin, not an assertion that it built this DLL. Its identity is recorded separately from the vgamepad wrapper's copyright. No vgamepad setup script, ViGEm driver installer, compiler or SDK code was executed during these comparisons.

These data do not prove source closure, license compatibility or redistribution approval. They also do not justify deleting a dependency merely because one runtime probe did not observe it.

## Produce the report

First build and inventory a private SDK diagnostic bundle using the existing procedure. Prepare source data in a new destination, then audit:

```sh
python -m tools.fetch_sdk_sources --destination build/sdk-traceability-sources
python -m tools.sdk_native_provenance \
  --inventory build-evidence/sdk-inventory.json \
  --sources build/sdk-traceability-sources \
  --label macos-arm64 \
  --commit "$(git rev-parse HEAD)" \
  --output build-evidence/sdk-native-provenance.json
```

Use the inventory's actual target label and exact source commit. Output must be new. The auditor performs no network access, app launch, SDK load, screen capture, input or permission change. Source preparation is a separate fixed-URL data fetch; it does not run downloaded source.

A passing report means the declared mapping and supplied evidence agree. It always records `sdk_publication_gate: "closed"`, `source_coverage_complete: false` and `vendor_archives_verified: false`. The separate vendor-origin receipt records the manual static package comparisons; the auditor does not refetch those vendor archives. The report's fixed scope excludes a legal conclusion and complete transitive source coverage.

CI prepares the fixed source archives, runs the auditor after private SDK inventory, and uploads `SDK-traceability-TARGET-COMMIT` containing only JSON. It then rebuilds the SDK-free downloadable app. This guide and the vendor-origin receipt accompany the bundled notices under `legal/docs`; the mapping, source and build-prerequisite manifests are included under `legal/tools`. A successful report never changes `tools/package_build.py` or enables SDK-bearing publication.

Complete corresponding dependency source, embedded-component notice coverage, mixed vendor terms, signed/clean-machine replacement and final distribution review remain open. Native calibration and Adopt Me acceptance are separate gates.
