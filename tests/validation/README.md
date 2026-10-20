# Live-data validation sources

These are development harnesses, not user-facing installation tools. They require the user's own game, generated SDK/key/cache, original manifest/FBXs and saved Blender scene. Do not distribute game keys or Frosty dependencies.

## Version 0.4 checks

Set `UNBOUND_VALIDATION_WORKSPACE` to a workspace containing `outputs/UnboundBatchExport`, `outputs/Murcielago-Assembly` and `work/full-batch-0.4`. The scripts write only their named workspace outputs. Preserve your original scene separately.

- `FullBatchHarness.cs`: actual production `Batch.Run` against live SDK data. Arguments: installed editor folder, compiled plugin folder, prepared scratch editor/cache folder, game folder, asset scope, NEW output directory. The progress-window fixture bypasses the GUI; this is not a menu-workflow test.
- `build_assembly_blend.py`: run in Blender with the original `merci.blend` loaded. Adds missing shared meshes and assembles; checks original data and body alignment; writes `merci-assembled.blend`.
- `restore_material_slots.py`: run with `merci-assembled.blend` loaded. Restores slots, validates attributes and selected-instance material-row switching; writes `merci-material-slots.blend`.
- `validate_fresh_pipeline.py`: compares all fresh native FBXs and DDS hashes, then imports/restores/assembles from scratch.
- `audit_fender.py`: compares the source rear-fender FBX polygon index sequences with the original Blender scene. Run with the original scene loaded.
- `validate_packaged_addon.py`: extracts the supplied Blender ZIP into workspace scratch, registers it and executes its full import operator in background Blender.
- `native-export-preservation.json`: source-method comparison with version 0.2.0.
- `release-validation.json`: compact verified results and report hashes.

Example:

```powershell
$env:UNBOUND_VALIDATION_WORKSPACE = 'C:\YourWorkspace'
& 'C:\Path\To\blender.exe' --background 'C:\Original\merci.blend' --python-exit-code 1 --python .\build_assembly_blend.py
```

The scripts contain the Murciélago test fixture and expected counts. These are validation fixtures, not per-vehicle production rules.

## Historical Phase 2 checks

The following older scripts retain dataset-specific paths. They are included for provenance and are superseded by the checks above:

- audit_blend.py: run Blender in background with the original blend loaded; writes a read-only scene audit JSON without saving the scene.
- compare_geometry.py: imports the original and freshly re-exported two FBXs into separate empty scenes and compares geometry, UVs, transforms and skin data. Repeated mesh-name suffixes are normalized.
- validate_materials.py: historical source-count audit, which fails on the six degenerate rear-fender triangles. `audit_fender.py` now explains that discrepancy exactly; it is no longer an unexplained failure.
- MaterialHarness.cs: advanced read-only game-data harness. Positional arguments: installed editor folder, compiled plugin folder, prepared scratch editor/cache folder, game folder, original manifest.json, material output folder, fresh geometry output folder, optional 'geometry-only'. Uses the user's existing generated SDK/key, never prints key contents. Do not distribute keys or game data.

The scratch folder must contain the matching release resources/Profiles/Caches/ThirdParty dependencies and a phase2-test-config.json containing {}. Geometry output must be a NEW directory. Compile with the same .NET Framework compiler against FrostyCore, FrostySdk, Newtonsoft.Json, UnboundBatchExport and the WPF assemblies used by build.ps1.

The historical material harness invokes the private geometry method by reflection. The new full-batch harness calls `Batch.Run` directly. Their progress-window fixtures are test-only; production uses the real Frosty task window. These scripts are supplied for auditability, not as a supported replacement for running the plugin in Frosty.
