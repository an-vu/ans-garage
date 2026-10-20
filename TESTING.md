# Test report — 2026-10-19

## Executed successfully

- Built x64 `UnboundBatchExport.dll` with Windows .NET Framework C# compiler against **actual downloaded HarGabt v1.0.7_26.10.12 release assemblies**, including FrostyCore, FrostySdk, FrostyControls and MeshSetPlugin. No SDK stubs were used.
- Loaded the resulting DLL's types and assembly registration attributes in a .NET Framework test process, and checked the installed FBX export method signature. This is **not** a Frosty UI plugin-load test.
- **22 C# assertions passed**: scope case/boundary/empty handling, filename handling, stable distinct identities, translated/rotated rigid matrices, rejection of scale/reflection/shear/NaN, internal pointers, external file + non-root class GUID, empty-class root fallback, explicit missing-file/class/null failures, invalid/valid FBX signature checks, assembly loading, exporter signature and attribute loading.
- **4 Python tests passed**: only exported records selected, duplicate IDs rejected, schema validation, and output-path containment/missing-file checks. Multiple assertions run within the path test.
- Inspected upstream source for the release's pointer access, variation-cache behavior and FBX export path. Release-tag exporter and EBX reader are text-equivalent to the inspected branch files (line-ending differences only); variation-cache source matches exactly.

The first Python run hit the execution sandbox's temporary-directory access restriction. Re-running with TEMP/TMP directed to the writable workspace passed. No Blender or game behavior was involved in that failure.

Raw successful command output is in `test-results.txt`. Dependency fingerprints are in `BUILD-INFO.json`.

## Not executed / not established

- Frosty Editor startup, menu visibility, dialog behavior, cancellation, or completion reporting inside the application.
- NFS Unbound SDK/cache initialization, database parsing with actual game files, vehicle selection completeness, or missing-reference behavior on real assets.
- Native FBX export, mesh chunks/vertex decoding, triangle counts, normals, UVs, skinning, composite pose, or LOD contents on real game meshes.
- Blender installation, add-on registration, FBX import, collection visibility, or transform/scale comparison.
- Original material appearance, textures, whole-car assembly placement, or body-kit correctness. These are not implemented by this package.
- Non-rigid transform export. Such transforms are deliberately rejected and documented, not corrected.
- Other dated HarGabt 1.0.7 releases, other Frosty forks, different game patches, huge batches, path-length edge cases in a real export, native crash recovery, or performance/memory behavior.
- Build using the provided SDK-style `.csproj`. Only `build.ps1` was executed.

## Reproduce automated checks

After building:

```powershell
powershell -ExecutionPolicy Bypass -File .\tests\run-tests.ps1 -FrostyDir 'C:\Tools\FrostyEditor'
python -B .\tests\test_importer.py
```

Python 3.9+ is needed for the standalone path helpers. The Blender add-on declares Blender 3.6+ but remains unverified in that application. Automated reference tests use small synthetic EBX objects with the **real Frosty SDK**; they do not contain game data. The FBX-header test uses a signature fixture, not a real exported mesh.

## Manual acceptance checklist before trusting a batch

1. Start the specified Frosty release with NFS Unbound and confirm the Tools menu item loads. Start with a clean project for original assets.
2. Select a small, known vehicle folder. Compare discovered mesh references and variation rows with the same database viewed in Frosty. Check that file/class GUIDs point to the expected object, including non-root objects where present.
3. Export one rigid part, one composite with a known translated/rotated part, and one skinned part with its known skeleton. Compare each against Frosty's manual FBX export using the same settings.
4. In Blender, verify only LOD0 renderable sections are present. Compare triangle/vertex counts, UVs, bounding-box dimensions, orientation and part alignment. Verify at least one known physical dimension to test meter units.
5. For composites, compare the raw manifest matrices and visible exported pose. Do not apply the matrices twice. For skinned parts, inspect bind pose, procedural bones and Unbound-specific offsets.
6. Confirm the helper leaves FBX parent relationships and object transforms unchanged while moving objects into collections. Confirm variant links reuse geometry and hidden variant-reference collections do not hide the main Parts view.
7. Exercise an unresolved reference, missing resource, missing skeleton and unsupported non-rigid transform. Confirm errors/skips remain in the manifest and unrelated valid meshes continue.
8. Cancel a multi-mesh run, confirm the current native export finishes, remaining records are marked cancelled, and the manifest opens. Run again and confirm a distinct output folder is created.

Passing these checks on one vehicle is not evidence that every Unbound vehicle, game patch or dated Frosty build is supported.
