# Live-data validation sources

These are the actual development harnesses, not user-facing installation tools. Python scripts retain dataset-specific local paths. They require the original manifest/FBXs, the supplied materials overlay and the user's saved Blender scene. Adapt those paths before use on another machine.

- audit_blend.py: run Blender in background with the original blend loaded; writes a read-only scene audit JSON without saving the scene.
- compare_geometry.py: imports the original and freshly re-exported two FBXs into separate empty scenes and compares geometry, UVs, transforms and skin data. Repeated mesh-name suffixes are normalized.
- validate_materials.py: validates the output graph against the scene audit and DDS files. It intentionally fails on the documented pre-existing rear-fender polygon-count discrepancy.
- MaterialHarness.cs: advanced read-only game-data harness. Positional arguments: installed editor folder, compiled plugin folder, prepared scratch editor/cache folder, game folder, original manifest.json, material output folder, fresh geometry output folder, optional 'geometry-only'. Uses the user's existing generated SDK/key, never prints key contents. Do not distribute keys or game data.

The scratch folder must contain the matching release resources/Profiles/Caches/ThirdParty dependencies and a phase2-test-config.json containing {}. Geometry output must be a NEW directory. Compile with the same .NET Framework compiler against FrostyCore, FrostySdk, Newtonsoft.Json, UnboundBatchExport and the WPF assemblies used by build.ps1.

The harness invokes the private geometry method by reflection for regression testing. Its uninitialized progress-window fixture is test-only; production uses the real Frosty task window. These scripts are supplied for auditability, not as a supported replacement for running the plugin in Frosty.
