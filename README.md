# Unbound Vehicle Batch Export 0.1.2 — experimental

A compiled C# x64 plugin for **HarGabt Frosty Editor 1.0.7, build v1.0.7_26.10.12**, targeting NFS Unbound. Includes source, repeatable build/test commands, and a Blender manifest importer.

**Status:** 0.1.2 fixes the temporary FBX filename mismatch discovered in the user's second run. 30 C# checks pass. A separate real native SDK export reproduces the old filename behavior and verifies the corrected filename. The user's 97 FBX files were recovered and structurally validated separately. **Blender import and fidelity to game geometry/transforms remain unverified.** See `TESTING.md`.

**Updating from 0.1.0/0.1.1:** close Frosty, replace `Plugins/UnboundBatchExport.dll` with the DLL in this package, then restart Frosty. Use the separately provided recovered Murcielago export for the completed run; no rescan is needed for those files. The full database scan still occurs on future exports; this hotfix does not change scan speed.

## Install

1. Extract HarGabt's [Frosty Editor v1.0.7_26.10.12 release](https://github.com/HarGabt/FrostyToolsuite/releases/tag/v1.0.7_26.10.12). Use Editor, not Mod Manager.
2. Close Frosty Editor. Copy **only** `plugin/UnboundBatchExport.dll` from this package to `<Frosty Editor>/Plugins/`.
3. Keep the release's `MeshSetPlugin.dll`, Frosty DLLs and `ThirdParty/libfbxsdk.dll` in their original locations. Do not replace them with files from another Frosty build. This package does not redistribute those dependencies.
4. Launch Frosty Editor and load NFS Unbound normally, allowing its SDK/cache initialization to finish.
5. Open **Tools → Unbound vehicle batch export...**. The plugin refuses other game profiles.

To uninstall, close Frosty and remove `Plugins/UnboundBatchExport.dll`. Exports remain on disk. If the menu is missing, check Frosty's plugin-load log and build compatibility. Rebuild against your installation if necessary; older 1.0.7 dated releases are not certified compatible.

## Export a vehicle

1. Locate the vehicle's folder in Frosty's Data Explorer. Enter its exact asset path prefix in the plugin dialog, using `/` separators. Use the path in your installation; the plugin deliberately does not hardcode a guessed vehicle directory. An exact mesh or database asset path also works.
2. Optionally enter the **exact skeleton asset path** appropriate for that vehicle's skinned meshes. Without a valid skeleton, skinned meshes are marked `skipped`; rigid/composite parts can still export. The plugin does not infer a skeleton or validate that a user-selected skeleton belongs to the vehicle.
3. Choose a short output parent path, such as `C:\Exports`. A unique run folder is created, so previous runs are not overwritten. Long Windows paths can still cause failures, which are reported.
4. Review `manifest.json`: inspect `Errors`, each mesh's `Status`/`Error`, and `Cancelled`. The completion dialog's error count does **not** include intentional skips. Zero exported meshes is not proof of success: check the scope and manifest.
5. Cancel stops between rows/meshes. A native FBX export already in progress must finish before cancellation takes effect.

Exports reflect the **current loaded project state**, including modifications. For vanilla assets, start from a clean project. The plugin does not modify assets or save a Frosty project.

## What it implements

- Scans EBX assets of type `MeshVariationDatabase` and assets named `MeshVariationDb_Win32`. Reads `Entries` directly because Frosty's normal variation cache loader returns early for Unbound.
- Selects rows when either the database path or referenced mesh path is inside the requested scope. Database scope therefore includes referenced meshes outside that folder. Also includes direct mesh assets inside the scope, even without a database row.
- Resolves external references using **FileGuid and ClassGuid**; it never substitutes the root for a missing nonempty class GUID. Empty class GUID uses the file root. Internal pointers resolve to their actual object and use the internal index for identity when no exported GUID exists.
- Exports shared geometry once per EBX file/object identity. Each manifest mesh retains all matching database rows, variation hashes and material/material-variation references. Hashes are recorded in hexadecimal and are not assumed to be unique across databases.
- Calls the installed `MeshSetPlugin.FBXExporter` directly: binary FBX 2014, **first mesh LOD (LOD0)**, meters, hierarchy retained, depth/shadow-only sections excluded. No per-mesh settings dialog; no changes to global export settings.
- Stores a validated binary-header FBX only after the native exporter returns. A header check detects missing/obviously invalid output; it does not prove FBX geometry is correct.
- Writes progress to an atomically replaced manifest after each mesh; failures do not stop the rest of the batch. Native process crashes cannot be caught reliably.

## Transform preservation: exact scope and limitations

The plugin does not recenter vertices, normalize sizes, apply object transforms or flatten the exported hierarchy. It delegates axis conversion and FBX scene construction to Frosty's installed exporter. Meter units are explicitly declared; Blender handles the FBX axis/unit metadata at import. Physical scale has not been measured against a real vehicle.

Composite `PartTransforms` are retained as raw 12-number arrays: **right XYZ, up XYZ, forward XYZ, translation XYZ**. The native exporter skins composite parts at identity and then moves their part bones, so the Blender helper must not apply those raw transforms again.

The inspected exporter writes composite and skeleton translation/rotation but omits scale. To avoid silent damage, this plugin rejects non-rigid composite or skeleton matrices (non-unit scale, reflection, shear, NaN/Infinity; orthonormal tolerance 1e-5). The manifest retains the offending transforms and reports the failure; **these meshes do not receive an FBX**. Skeleton local and procedural poses are also retained and checked when an explicit skeleton is supplied.

**Complete vehicle assembly placement is not reconstructed.** A variation database is a mesh/material reference catalog, not a vehicle blueprint. Entity transforms, sockets, instanced wheel locations, assembly relationships and configuration choices may live elsewhere. Mesh-local export cannot recover those missing placements. Frosty's existing skinned exporter performs its own Unbound rigging-offset lookup; that behavior is inherited and remains untested here. If it fails, the mesh is reported as failed.

There is no material/shader conversion, texture export, animation export, or automatic body-kit identification. Material-only variants intentionally reuse geometry and may look identical in Blender. Database variation groups must not be interpreted as complete assembled vehicle configurations.

## Blender

`blender/import_unbound_batch.py` is a conventional add-on targeting Blender 3.6+ (Blender execution has not been tested).

1. Install that `.py` file using Blender's add-on installation UI and enable **Unbound Batch Manifest**. Alternatively open the file in Blender's Text Editor and run it once.
2. Choose **File → Import → Unbound batch manifest (.json)** and select the export run's `manifest.json`.
3. The importer creates a new vehicle collection with **Parts** and hidden **Variant references** collections. Each part keeps its FBX hierarchy. Variant collections link the same part collection, avoiding duplicate geometry and transform application.
4. Inspect the **Unbound import report** text block for per-mesh failures. Check the Frosty manifest separately for meshes that never exported.

The helper disables automatic bone orientation, animation import and experimental space-transform baking. It does not assign `matrix_world`, clear parenting, apply scale, or change scene units. Raw matrices and database metadata are stored as custom properties for inspection. These collections organize exported assets; they do not assemble missing car placements or render original game materials.

## Build from source

Requires Windows x64 and the .NET Framework 4.8 runtime/compiler supplied with Windows, plus the target Frosty Editor release. The tested build uses the Framework compiler directly, with no NuGet packages or .NET SDK needed:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1 -FrostyDir 'C:\Tools\FrostyEditor'
```

Output: `plugin/UnboundBatchExport.dll`. Run from the extracted package folder. `build.ps1` does not install or launch the plugin.

For Visual Studio / an installed .NET SDK and .NET Framework 4.8 targeting pack, the included project is also available:

```powershell
dotnet build .\UnboundBatchExport.csproj -c Release -p:FrostyDir='C:\Tools\FrostyEditor'
```

That SDK-based command was **not run** in this environment; the direct compiler build above was run successfully.

## Source layout

| File | Purpose |
| --- | --- |
| `src/Plugin.cs` | Menu/dialog, database resolution, export pipeline and manifest |
| `src/Core.cs` | Scope, filesystem identities, transform checks and FBX header validation |
| `blender/import_unbound_batch.py` | Blender collection importer |
| `tests/Tests.cs` | Real SDK pointer-resolution and helper/API checks |
| `tests/test_importer.py` | Pure Python manifest/path checks; does not run Blender |
| `TESTING.md` | Observed results, untested areas and manual acceptance checklist |
| `BUILD-INFO.json` | Exact upstream release and dependency hashes |

All new source in this package is provided under the included MIT license. Frosty and its native dependencies remain separately distributed third-party software. No game assets are included.
