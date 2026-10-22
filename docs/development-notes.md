# Development notes

How the pipeline works and what is still open. Release history: `CHANGELOG.md`. Data formats: `material-data.md`, `assembly-data.md`.

## 1. Exporter (C#, `frosty/AnsGarage/src`)

| Area | Implementation |
|---|---|
| Vehicle list | `VehicleCatalog.Build()` (Names.cs): each `RaceVehicleItemData.RaceVehicle` bundle hash → the `RaceVehicleBlueprint` whose entity has that `VehicleBundleHash` (200 vehicles), cached in `%LOCALAPPDATA%\AnsGarage\vehicle-catalog.json`. |
| Shared folders | `Batch.Blueprint` → `AssemblyRun.Blueprint`; a folder holding several blueprints (the BMW M3 E46 folder has 3) needs the chosen blueprint. |
| Names | `Names.ItemUi()`: `ItemUI` string ids → `FsLocalizationPlugin.FsLocalizationStringDatabase` (created by reflection when the editor's database is absent). Kit brand: `ID_VC_<KIT>_02`, else `BrandTitle` from the game's localized text for the logo key. |
| Geometry, materials | `Batch` (Plugin.cs) writes LOD0 FBX per mesh and `MaterialRun` (Materials.cs) the material graph and DDS textures. A texture's raw payload is kept only for texture arrays, cube maps and formats the DDS writer doesn't support; every DDS is checked against the payload's SHA-256. |
| Shader defaults | `Batch.ExportShaderDefaults()` writes the assets in `UnboundShaderDefaults.json` once into a `shader-defaults` folder next to the car folders and skips them when it is complete. Two tiny black textures always fail the exact-payload check. |
| Assembly | `AssemblyRun` (Assembly.cs): blueprint graph, wheels, items, presets, components and `TrackData` (sequence keyframes for moving parts). |
| Libraries | `TireLibrary` (Tires.cs) and `PlateLibrary` (Plates.cs), exported once through `LibraryMenu`. |
| Version | `Core.Version` (Core.cs) is the only place the version is written. |

`tools/headless/ExportHarness.cs` (`tools/headless/export.ps1`) runs the same code without the Frosty window: export, assembly, defaults, tires, plates, catalog, scan (moving parts of every vehicle), and lookup modes. It loads a copy of the editor config, never the real one, and never prints keys.

## 2. Shader profiles (`tools/shader-compiler/compile_all.py`, schema 3)

- **Scope:** every shader in the v293 vehicle shader database (225), keyed by the DJB2-xor hash of the lower-case asset name.
- **Parameters:** all symbolic except the static undamaged override `Ext_GlassDamage = 0`; the add-on specializes each material.
- **Textures:** every material-bindable texture stays a sample. The add-on folds samples whose texels are uniform, plus runtime-only textures without a default or binding.
- **Inputs:** interpolants are named by vertex-declaration element (`Elem<i>.<k>`); routing assumptions are recorded in `AssumedUsages` and checked by the add-on.
- **Constant-stub vertex programs** (skinned layouts): usage-named entries exist for layouts in `known-layouts.json` (shader data folder). Exporting more vehicles and re-running `compile_all.py` extends them.
- **External cbuffer:** `cb1` wherever it is identifiable by size.
- **Result:** 115 shaders profiled; the rest contain only forward effect/decal programs. 1.3 MB gzip.

## 3. Add-on (`blender/ans_garage`)

- **Import** (`__init__.py`, modal, in slices): FBX → slot restore (`unbound_materials.py`) → surfaces (`unbound_surfaces.py` + `unbound_profiles.py`) → assembly (`unbound_assembly.py`) → moving parts (`unbound_animation.py`) → per-wheel surfaces.
- **Surfaces:** every slot is built from its compiled profile: specialization (`Spec`, `prove_constants`, `settle`), permutation choice (`choose_entry`), node emission (`NodeBuilder`). Unresolved inputs fail closed with a reason in the surface report.
- **Accepted runtime values, recorded on each material:**
  - engine constants with a measured effect ≤ 0.1 are set to 0;
  - glass permutations may differ by ≤ 0.12 in transmittance/reflectance;
  - `cb2[44].w` (camera exposure) is accepted when the specialized outputs don't change across 1e-5–100;
  - the LED license-plate permutation is a player customization: the printed plate is built.
- **Assembly:** item meshes are placed at their own customization component; geometry already in car space keeps its place.
- **Moving parts:** 0–1 sliders from the blueprint's animation graph; see `assembly-data.md`.
- **Libraries:** tires (`unbound_tires.py`) and license plates (`unbound_plates.py`, with typed plate text) swap textures and meshes through per-object overrides (`unbound_texture_overrides_json`, `unbound_parameter_overrides_json`).

## 4. Validation

`tests/run_all.py`: parallel, skips tests whose inputs are unchanged. `existing` (a 0.5-era scene upgraded in place), `fresh` (install ZIP), `nodes` (Cycles bake vs Python for every selected entry), `tires`, `plates`, and `vehicle:<name>` for eight cars covering every moving-part pattern found by the scan of all 200 vehicles.

## 5. Open items

1. **Light glass needing live values:** 7 surfaces.
   - P1 and Diablo SV lenses: `cb0[1].x` changes them by 0.11–0.21, over the 0.1 limit.
   - BMW M3 E46: one `cs_lglass` lens whose programs `04203732` (full) and `5ac42833` (reduced) differ by up to 0.47 in transmittance; the selection rule is unknown.
   - A frame capture of the running game would settle both.
2. **Other games:** NFS Heat needs its own shader database, programs and profiles (same Frosty route). Hot Pursuit Remastered is not Frostbite and would need a separate exporter.
