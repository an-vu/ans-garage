# Version 0.4.0 validation — 2026-10-20

Tested against the user's installed HarGabt Frosty **1.0.7 v1.0.7_26.10.12**, generated Unbound SDK, local game data and Blender **5.2.2 LTS** (`d13f752e3b9c`). These results supersede the Phase 2 report. Production logic has no Murciélago asset IDs or wheel offsets.

## Verified

| Check | Result |
|---|---|
| Windows x64 .NET Framework build | Successful; exact dependencies/source fingerprints in `BUILD-INFO.json` |
| C# unit checks | **47 passed**, including existing geometry tests, material/reference handling and database dependency filtering |
| Python unit tests | **15 passed**, including preset/override rules, identity mismatches, ambiguous roots, UV encounter order and unknown channel handling |
| Actual production `Batch.Run`, through a headless Frosty SDK harness | **102 FBX exports, 78 unique DDS textures, zero reported export, material extraction or assembly issues** |
| Fresh FBX → automatic slots → assembly in Blender | **291 checks passed**, zero import failures |
| Existing `merci.blend` → assembly | **2,439 checks passed**, zero failures |
| Existing assembly → material slots and explicit material-row switching | **3,610 checks passed**, zero failures |
| Packaged add-on ZIP → Blender import operator | **12 checks passed**; imported all 102 FBXs, restored slots and assembled the vehicle |

The full export used `vehicles/player/car_lamborghini_murcielagosv_2010`, an empty skeleton path and a new output directory. The production native geometry export method is unchanged from 0.2.0; `tests/validation/native-export-preservation.json` records its source hash.

The database dependency filter considered 26,382 databases, skipped 26,285 with unrelated known import tables and decoded 97. It recovered the same **102 mesh identities and 552 database-row/variation tuples** as the earlier complete scan and assembly discovery. Empty dependency tables retain the original scan path.

Material extraction captured **317 original slots** and **1,867 graph nodes**: 317 MeshMaterial, 1,434 MeshMaterialVariation, 78 TextureAsset, 26 ShaderGraph and 12 SurfaceShaderPreset. The default resolved states reference 43 of the 78 textures; other textures belong to captured variations. Source metadata identifies 48 exported textures as sRGB and leaves 30 unspecified.

## Geometry and material assignment

All **593 mesh objects**, including the retained source library and assembly instances, received source slot identities and section-derived polygon indices. Different source variations can use object-linked materials while sharing geometry. The Blender operator for explicit database-row selection was exercised and checked not to change an unselected instance or face indices.

The material pass preserved vertex positions, topology, all other mesh attributes, UV layers, vertex colors, custom corner normals, vertex groups/weights, shared mesh datablocks, local transforms and parents. Attribute hashes intentionally exclude only `material_index`, which this feature restores. No UV coordinate values are rewritten.

Fresh FBXs were compared with the original 97 FBXs and five previously recovered shared meshes. Geometry, topology, UVs, colors, model properties and hierarchy connections match exactly after ignoring generated FBX object IDs. Native normal/tangent/binormal decoding varies slightly across runs: maximum component differences were approximately `1.19e-7`, `1.33e-6`, and `1.30e-6`, respectively. Only those vectors use a `1e-5` comparison tolerance. The material-pass preservation checks on an existing Blender scene remain exact.

All 78 fresh DDS file hashes match the earlier extracted textures. Blender loaded the textures referenced by resolved materials without decode errors. Referenced images in `merci-material-slots.blend` are packed for inspection.

## Rubber coverage and wheels

Four assembled tire objects, plus their retained source object, resolve to the actual `cs_pbr_tire_max_lookdev` shader. Channel names explicitly identify RGB color/alpha smoothness and RG normal/alpha AO; other channel meanings are not invented. This verifies tire material coverage, not a rendered rubber appearance or every possible rubber submaterial in generic opaque shaders.

Four authored rest centers, parent controls, source transforms and original body alignment passed assembly checks. Related sections stay in their mesh assemblies. Variant visibility and source presets were exercised. Workbench geometry previews were inspected for overall placement. The interpretation of `Rotate` and tire dimensional fitting remains experimental, as described in `ASSEMBLY.md`.

## Six rear-fender polygons: resolved

The `fendersr_seta_mesh` plastic section has 1,192 FBX triangles and 1,186 Blender polygons. Exactly six FBX triangles repeat a vertex index:

```
1027 1027 1028
1027 1028 1028
1028 1028 1029
1028 1029 1029
1029 1029 1027
1029 1027 1027
```

They are zero-area primitives. Blender discards them on import. Every remaining face-index sequence matches; the other three sections match completely. **No nondegenerate surface was lost.** The FBX remains unchanged. Exact indices and source polygon ordinals are in the separate output's `rear-fender-audit.json`.

## What is not verified or complete

- **Full Frosty GUI menu → completed export is not verified.** A scratch editor host loaded the plugin and actual assets, but its startup/modal state prevented a reliable automated menu run. The successful full batch used the production backend with a test-only progress-window fixture. This is not equivalent to clicking the menu end to end.
- Blender add-on registration and operators were tested in background Blender. Interactive Preferences installation, file-picker behavior and sidebar drawing were not visually verified.
- **No reconstructed material has a connected surface output.** The seven Principled groups are inactive templates. Paint/glass/light/carbon/metal/plastic/rubber appearance has not been validated against Frosty or the game.
- Source vertex-usage to FBX UV-layer mapping is implemented. The tested material data does not identify actual texture sampling UVs. No default UV0 fallback is connected.
- Compiled shader permutations, generic packed-channel meanings, normal decoding, paint composition, glass IOR/refraction, carbon weave, runtime/global textures and light/dirt/wetness behavior remain unresolved. Unknown values are retained.
- Rendered material validation, all-vehicle compatibility, modified projects, explicit skeletal animation, all failure/retry cases and cancellation timing are untested. A BMW M3 E46 discovery-only check found four wheel records without assembly issues; it was not exported or assembled in Blender.
- DDS cube/volume/array paths and additional formats remain experimental. PNG conversion is not implemented.
- Other Frosty releases, Blender versions and the optional `.csproj` build route are untested.

Blender emitted an inability to write a system thumbnail during the saved-scene check; scene saving and all validation checks completed. Native FBX import also emits `NoMappingInformation` material warnings because Frosty omits FBX materials; the subsequent material pass supplies slots from source metadata.

## Evidence and reproduction

The separate `Murcielago-Assembly` output contains `blender-validation.json`, `material-validation.json`, `fresh-pipeline-validation.json`, `material-reconstruction.json`, `rear-fender-audit.json`, manifests, original DDS files and saved scenes. `tests/validation/` contains development harnesses and a compact release summary. These live-data checks need the user's own game, SDK, key and cache, which are not distributed with the plugin.

Run `build.ps1`, `tests/run-tests.ps1`, and `python -m unittest discover -s tests -p 'test_*.py' -v` for the ordinary build/unit checks. See `tests/validation/README.md` for the live-data harness prerequisites.

The original desktop `merci.blend`, original export folder, game and installed Frosty plugin were not overwritten. Work was performed in separate workspace outputs.
