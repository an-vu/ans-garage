# Phase 2 validation — 2026-10-20

## Tested

- Compiled 0.2.0 against the user's installed HarGabt Frosty v1.0.7_26.10.12 assemblies using the Windows x64 .NET Framework compiler.
- **4 Python manifest/path checks passed** using a writable workspace temporary directory.
- **43 C# checks passed**, including existing 30 geometry/reference tests and 13 material graph, unknown-property, missing-reference, DDS and filename checks. Full output: `test-results.txt`.
- Used the same plugin `MaterialRun` against actual locally installed NFS Unbound data through a read-only headless Frosty SDK harness. Loaded 254,876 EBX entries; processed the user's existing Murciélago manifest.
- **97 mesh assets**, **311 original slots**, **291 database rows**, **933 material variation assignments**. All assignments matched base slots by source object identity.
- Traversed **1,313 nodes**: 311 MeshMaterial, 933 MeshMaterialVariation, 22 ShaderGraph, 12 SurfaceShaderPreset, 35 TextureAsset.
- **35 unique DDS textures, zero extraction issues**. All are 2D; every DDS pixel/mip payload matches original source texture data byte for byte. Exact formats: BC1_UNORM 15, BC1_SRGB 11, BC3_SRGB 2, BC3_UNORM 2, BC5_UNORM 3, BC7_UNORM 2.
- Source material coverage includes body paint, glass, headlight/taillight parts, carbon and plastic. This confirms source-reference coverage, not rendered appearance. No rubber/tyre-labelled sections were found in this scope; rubber is unverified.
- Read `merci.blend` in Blender **5.2.2 LTS** without saving: **280 mesh objects, zero material slots**. The existing native exporter disables material creation.
- Re-exported the real rigid boot part and composite main car through the unchanged native FBX path. Fresh Blender imports match original FBXs in vertices, polygons, UV values, world matrices, parenting, skin weights, bone rest/pose matrices and material slots. Comparison normalizes only Blender-generated numeric mesh name suffixes and object ordering; repeated source glass names receive different suffixes on separate imports.

## Retained discrepancy

The full source-to-saved-Blender audit reports **1,164 passing checks and 1 failing polygon-count check**. Rear-fender section M_Opaque_PlasticRoughBlack_Max reports 1,192 source primitives versus 1,186 Blender polygons. A fresh import of the original pre-Phase-2 FBX also produces 1,186, establishing that this difference predates Phase 2. The exact cause has not been established; it is not silently waived.

All 97 section counts/mesh associations and material-slot references were inspected; source-to-Blender polygon totals differ only for that rear fender. This does not prove per-object material assignment in a future importer when section names repeat.

The separate materials delivery contains `validation.json`, `geometry-validation.json` and `texture-bindings.json` with detailed evidence. Validation scripts used for that dataset are in `tests/validation/`; they document local test paths and prerequisites and are not installation steps.

## Not tested / not implemented

- The new menu command and full combined geometry-plus-material UI run have not been clicked end to end in Frosty. The production material class was executed against real data; two native geometry exports were exercised separately.
- Did not freshly re-export all 97 FBXs, test other vehicles, modified projects, absent game keys/caches, every cancellation timing, or every failure/retry scenario.
- DDS cube/volume/2D-array paths and additional whitelisted pixel formats are experimental and untested with game assets. Cube arrays and swizzled textures are deliberately unsupported. PNG conversion is not implemented.
- No visual comparison against Frosty's rendered preview or in-game rendering; no Blender shader reconstruction, slot creation or texture-loading test in Blender.
- ShaderBlockDepot/compiled shader bindings, runtime-global textures, final override evaluation, packed-channel semantics and implicit UV associations are unresolved. The 35-texture total is for reachable EBX material references, not a claim to include every texture the game renderer might bind.
- Skinned meshes with explicit skeletons, animation, complete vehicle assembly transforms and physical-scale measurement remain outside this validation.
- Other editor releases and the .csproj/dotnet build route are untested.

The original game, recovery export and merci.blend were read without modification. Extracted output was written to a separate workspace directory. No plugin was installed into the user's running editor.

## Reproduce the unit tests

Run `build.ps1` then `tests/run-tests.ps1` with `-FrostyDir` pointing to the target installation. Live-data validation additionally requires the user's own game, generated SDK, cache and key; none are included in this package.

Harness note: an additional geometry rerun initially reused an existing test output folder and correctly refused to overwrite an FBX. A fresh test folder was used for the final successful two-mesh regression. The production batch command already creates unique run folders.
