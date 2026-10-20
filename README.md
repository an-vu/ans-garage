# Unbound Vehicle Batch Export 0.2.0

C# x64 plugin for HarGabt Frosty Editor **1.0.7, v1.0.7_26.10.12**, targeting NFS Unbound.

Extends the working 0.1.2 geometry exporter with automatic original DDS extraction and a raw material/reference manifest. Includes compiled plugin, C# source, build script, tests and the existing geometry-only Blender helper. No game assets or Frosty dependencies are included in this plugin package.

## Install or update

1. Close Frosty Editor.
2. Copy `plugin/UnboundBatchExport.dll` into your editor's `Plugins` directory, replacing the previous version.
3. Keep the release's `MeshSetPlugin.dll`, `TexturePlugin.dll`, core assemblies and `ThirdParty` dependencies installed. This plugin uses those existing exporters.
4. Restart Frosty and load NFS Unbound. Let SDK/cache initialization finish.

Tested dependency build: HarGabt v1.0.7_26.10.12. Other builds are not certified. Remove this DLL while Frosty is closed to uninstall.

## Add materials to an existing export

Choose **Tools → Unbound materials for existing export...**, then select its `manifest.json`.

For this Murciélago, select `C:\Users\anvu1\Desktop\Murcielago-Recovered\manifest.json`. This reads the already recorded meshes and database rows without rerunning the broad discovery scan or FBX export. It writes `materials.json`, `materials.log` and `textures/` beside that manifest. Existing files at those material output paths are replaced on a rerun.

The separate `Murcielago-Materials` delivery already contains the completed extraction for that export. Copy its contents into `Murcielago-Recovered` to make its relative FBX and texture paths resolve together. It contains no replacement FBX or `.blend`.

## New vehicle export

Choose **Tools → Unbound vehicle batch export...**. Supply the asset folder prefix with `/` separators; the tested scope is:

`vehicles/player/car_lamborghini_murcielagosv_2010`

An exact database or mesh asset path also works. Skeleton path is optional for rigid/composite meshes; a skinned mesh needs its exact compatible skeleton asset path. The plugin does not guess it.

Choose a short output parent folder. A unique run folder is created. The existing geometry pass runs first, followed automatically by materials/textures. Inspect both `manifest.json` (geometry failures/skips) and `materials.json`/`materials.log` (material issues). Cancellation stops between operations; native exports cannot be interrupted safely.

Exports use the current Frosty project state, including modifications. Use a clean project for vanilla assets.

## Material extraction

- Resolves mesh material slots and `MeshVariationDb_Win32` assignment/override references by exact object identity.
- Captures shader and preset references, texture/vector/bool/conditional/array parameters and unknown public fields.
- Preserves base materials and variation layers separately, without guessing a final shader.
- Exports shared texture resources once, to `textures/<resource-id>/<original-name>.dds`.
- Retains full asset names, EBX/object/resource/chunk identifiers, mip metadata, flags and source payload hashes.
- Preserves packed channels unchanged. Also retains the original texture payload as `.texture-data.bin`; it is not a standalone image.
- Uses Frosty's `TextureExporter` and validates DDS headers. For 2D images the DDS payload must exactly match the source texture bytes.
- Reports unsupported formats/layouts, missing references and traversal limits. Raw payload is kept when it can be read.

Material status is `completed`, `completed_with_issues`, `cancelled` or `in_progress`. An empty log means no reported extraction issues; it does not mean every compiled shader feature was decoded.

DDS is implemented; PNG conversion is not. Actual Murciélago testing covers 2D BC1/BC3/BC5/BC7 textures. Other whitelisted formats and cube/volume/array layouts are experimental. Cube arrays and swizzled data are rejected rather than exported with a misleading DDS header.

## Geometry and Blender

The 0.1.2 FBX export routine is unchanged: binary FBX, first LOD, native hierarchy and transforms, no recentering or transform application. Non-rigid scale/shear/reflection transforms remain rejected to avoid upstream transform loss. Database variants reuse geometry and are not complete assembled vehicle configurations.

**Frosty's existing FBX path disables FBX materials.** Your `merci.blend` has 280 mesh objects and zero Blender material slots. Phase 2 preserves this geometry behavior and records original Frostbite slot indices in `materials.json`; it does not create Blender slots or shaders yet.

The existing `blender/import_unbound_batch.py` imports geometry through **File → Import → Unbound batch manifest (.json)**. It does not read `materials.json`. There is no need to rerun it on your existing scene to use this delivery.

Use `MeshId` and relative `Fbx` to join the two manifests. Section records retain source index, original node name, LOD parent and native FBX child ordinal. Names can repeat; Blender-generated `.001` suffixes are not stable identities. A future importer must preserve the native section association at import time rather than rely on Blender object ordering.

See `MATERIALS.md` for the schema and API findings; `TESTING.md` distinguishes verified results from limitations.

## Build and test

From this package directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 -FrostyDir 'C:\Tools\FrostyEditor'
powershell -ExecutionPolicy Bypass -File .\tests\run-tests.ps1 -FrostyDir 'C:\Tools\FrostyEditor'
```

Uses the Windows .NET Framework compiler, x64, C# 5-compatible source, no NuGet packages. Output: `plugin/UnboundBatchExport.dll`. These commands do not install the plugin.

The included `.csproj` is an alternative for an installed .NET SDK/Framework targeting pack; that build route was not tested.

Source: `src/Plugin.cs` is geometry/discovery and integration; `src/Materials.cs` is material graph/DDS export; `src/Core.cs` is shared validation. Original plugin source is MIT licensed. See `BUILD-INFO.json` for dependency fingerprints.
