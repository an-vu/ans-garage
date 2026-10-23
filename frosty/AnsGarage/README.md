# An's Garage for Frosty

C# x64 plugin for Frosty Editor 1.0.7 (v1.0.7_26.10.12) and NFS Unbound. It exports one vehicle for An's Garage for Blender (`blender/ans_garage`).

## Install

1. Build it with `build.ps1` (see below), or take the plugin ZIP from a release build.
2. Close Frosty. Copy `AnsGarage.dll` and `UnboundShaderDefaults.json` into Frosty's `Plugins` folder. Remove an older `UnboundBatchExport.dll` if present.
3. Keep Frosty's own `MeshSetPlugin.dll` and `TexturePlugin.dll`: the plugin reuses their exporters.

## Use

**Tools → An's Garage → Export vehicle...** → **Choose vehicle...** (search by in-game name) → **Export...** → choose an output folder. One run writes:

| Stage | Output |
|---|---|
| Assembly: blueprint, wheels, parts, presets, shared tires/brakes, in-game names, moving-part keyframes | `assembly.json` |
| Geometry: LOD0 binary FBX per mesh, meters, hierarchy kept | `parts/*.fbx`, `manifest.json` |
| Materials: source material graph, original DDS textures | `materials.json`, `textures/` |
| Shader default textures (shared by all vehicles; written once next to the car folders) | `../shader-defaults/` |

Import `manifest.json` in Blender with **File → Import → An's Garage vehicle (.json)**.

The vehicle list is read once (about 3.5 minutes) and cached in `%LOCALAPPDATA%\AnsGarage\vehicle-catalog.json`. **Refresh list** re-reads it.

**Tools → An's Garage → Add assembly to an existing export...** adds or refreshes assembly data in an older export folder.

**Tools → An's Garage → Export shared parts (tires, rims, plates)...** exports the parts every car can use, once, into one folder:
- tick what to export: Tires (Falken, Toyo), Rims (real brands), License plates, Plate frames, or all of them;
- each library gets its own subfolder (`AnsGarage_TireLibrary`, `AnsGarage_RimLibrary`, `AnsGarage_PlateLibrary`);
- plates and frames share one library: exporting only one of them keeps the other.

In Blender, set that folder once (the add-on's preferences, **Shared parts folder**); it finds each library by itself.

## Build

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1            # Frosty folder from settings.json
powershell -ExecutionPolicy Bypass -File .\build.ps1 -FrostyDir 'C:\Tools\FrostyEditor'
```

The Windows .NET Framework compiler (C# 5), x64, no NuGet. The output goes to `bin\`. The SDK-style `.csproj` is untested.

## Limits

- Runtime suspension is not reproduced; wheel placement uses the authored rest transforms. Tire, rim and brake sizes are applied in Blender with the game's shader formulas.
- Item restrictions and permutation offsets are recorded, not evaluated.
- Kit parts without a localized name keep only their category and brand logo key.

Data formats: `docs/assembly-data.md`, `docs/material-data.md`.
