# Unbound Vehicle Batch Export 0.4.0

C# x64 plugin for HarGabt Frosty Editor **1.0.7, v1.0.7_26.10.12**, plus a Blender 4.0+ add-on. Tested in Blender 5.2.2 LTS.

Extends the existing geometry exporter with authored assembly data, shared tires/brakes, original DDS extraction, source material slots, face assignments and UV provenance. **This is not a finished vehicle surface-shader reconstruction.** Unknown sampling and shader behavior remain unresolved; the supplied Principled templates are inactive.

The package contains the DLL, C#/Python source, build scripts and tests. It contains no game assets, game keys or Frosty dependencies. The separate Murciélago scene/output folder contains the local validation results.

## Install

1. Close Frosty. Copy `plugin/UnboundBatchExport.dll` into its `Plugins` directory, replacing the previous DLL.
2. Keep Frosty's original `MeshSetPlugin.dll`, `TexturePlugin.dll`, core assemblies and `ThirdParty` files. The plugin reuses their exporters.
3. Restart Frosty and load NFS Unbound. Use a clean project for vanilla data; modified project assets are otherwise respected.
4. In Blender, disable the older single-file Unbound add-on. Install **UnboundBlender-0.4.0.zip** using Preferences → Add-ons → Install from Disk, then enable **Unbound Batch Manifest**.

Do not install just `import_unbound_batch.py`: this release also needs `unbound_assembly.py` and `unbound_materials.py`. Alternatively, keep all three files together and run `import_unbound_batch.py` in Blender's Text Editor for that session.

## New export

Choose **Tools → Unbound vehicle batch export...**. Enter a specific asset folder using `/`, for example:

`vehicles/player/car_lamborghini_murcielagosv_2010`

Leave the skeleton path empty for this tested rigid/composite vehicle. Skinned meshes still require an explicit compatible skeleton; none is guessed. Choose an output parent folder. A unique run folder is created.

The batch discovers meshes/material database rows, captures assembly references, exports LOD0 FBX and original DDS textures, and writes `manifest.json`, `assembly.json`, `materials.json` and logs. Shared resources are deduplicated. Cached EBX import tables avoid decoding unrelated material databases; unknown dependency tables retain the original scan path.

In Blender, choose **File → Import → Unbound batch manifest (.json)** and select `manifest.json`. With companion files present, the importer restores source slots, records UV mappings and builds the assembly. Use **3D View → N sidebar → Unbound** for body-part presets/variants. Material-row controls affect selected instances and preserve shared geometry.

## Existing exports and scenes

- **Tools → Unbound assembly for existing export...** extends a manifest with referenced shared meshes, assembly metadata and refreshed material/texture data. Work on a copy to preserve the previous manifest.
- **Tools → Unbound materials for existing export...** refreshes material/texture outputs; existing FBX is not rewritten.
- **File → Import → Assemble existing Unbound meshes** uses `assembly.json` with already imported meshes. Import the updated manifest first if shared tire/brake geometry is absent.
- **File → Import → Restore Unbound material slots** reads `materials.json` and native FBX files to verify object/section identity. Existing `unbound_mesh_id` properties are required. Pre-existing user material slots not created by this add-on are preserved and reported.

The supplied `merci-material-slots.blend` is a separate assembled copy of the baseline, with material assignments restored and referenced DDS images packed for inspection. **It will not show finished paint, glass or rubber shading.** Surface outputs are deliberately disconnected; inspect geometry in Solid mode and source data in the Shader Editor. The original desktop `merci.blend` was not overwritten.

## Support and limits

- Original FBX geometry, transforms, hierarchy, UVs, normals, colors, attributes, armatures and groups are retained. No destructive merge or simplification.
- Original material-slot order and uniform face assignment within each source section are restored.
- Root database overrides use material object identity; nested presets and case-insensitive parameter overrides are supported. Explicit material variants use database GUID and row.
- Source vertex-usage → Blender UV-layer mapping includes auxiliary UV attributes. **Texture sampling UVs remain unknown for the tested Murciélago bindings.**
- Original DDS and packed channels are preserved. Named tire channel meanings are recorded where shader parameter names explicitly state them.
- Seven reusable Principled groups exist for paint, glass, rubber, metal, plastic, carbon and lights. They have no invented family constants and are **templates, not validated game shaders**.
- General `T_Material` packing, normal decoding/handedness, layered paint, glass/refraction, carbon weave and runtime light/dirt/wetness behavior are unresolved.
- Four wheel rest centers use authored transforms. The interpretation of `Rotate` and tire dimensional fitting are experimental. Runtime suspension, rim sizing and tire deformation are not reproduced.
- Item membership and source presets are supported; arbitrary customization restriction/offset evaluation is incomplete.
- The complete GUI menu → finished-export workflow has not been verified. Successful backend and Blender checks are documented in `TESTING.md`.
- Other vehicles use the same algorithms; all-vehicle compatibility has not been proven.

See `MATERIAL-RECONSTRUCTION.md`, `ASSEMBLY.md`, `MATERIALS.md` and `TESTING.md` for evidence and limitations.

## Build and test

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 -FrostyDir 'C:\Tools\FrostyEditor'
powershell -ExecutionPolicy Bypass -File .\tests\run-tests.ps1 -FrostyDir 'C:\Tools\FrostyEditor'
python -m unittest discover -s tests -p 'test_*.py' -v
```

The tested build uses the Windows .NET Framework compiler, x64, C# 5-compatible source, without NuGet. The optional SDK-style `.csproj` build route is untested. Dependency/source fingerprints are in `BUILD-INFO.json`.
