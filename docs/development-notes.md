# NFS Unbound → Blender: development notes, 0.7.0

This release makes the pipeline vehicle-agnostic and adds in-game names.

## 1. Exporter 0.5.0 (C#, `frosty/UnboundBatchExport/src`)

| Area | Implementation | Evidence |
|---|---|---|
| Vehicle list | `VehicleCatalog.Build()` (Names.cs): each `RaceVehicleItemData.RaceVehicle` bundle hash → the `RaceVehicleBlueprint` whose entity has that `VehicleBundleHash` | 200 vehicles, names verified for the Murciélago, M3 E46, i8, M3 GTR |
| Shared folders | `Batch.Blueprint` → `AssemblyRun.Blueprint`; ambiguous folders now list the candidates | `car_bmw_m3e46_2003` holds 3 blueprints |
| Names | `Names.ItemUi()`: `ItemUI` (`ItemUiMetaData`) Long/Medium/Short/Description/TypeName ids → `FsLocalizationPlugin.FsLocalizationStringDatabase` (created by reflection when the editor's database is absent) | `ID_STOCK_BUMPER` → "Stock", `ID_VC_BUMPERFRONT` → "Front Bumper" |
| Kit brand | `DescriptionId` `ID_VC_<KIT>_01` → `ID_VC_<KIT>_02`, or `ID_VC_<BRANDKEY>_02` from the brand texture | Liberty Walk, Rocket Bunny, CSL, M2 Motoring, Speedhunters, DTM Fiberwerkz Widebody |
| No name | `DisplayName` null; the brand texture key is kept (`apr`, `pandem`, `bigcountrylabs`, `carbon`) | Hash search of 20+ id spellings found no brand string id for these |
| Shader defaults | `Batch.ExportShaderDefaults()` exports the assets in `UnboundShaderDefaults.json` with the normal texture path | 53 assets; 2 tiny BC1 black textures fail Frosty's DDS payload check and stay unexported |
| Robustness | `MaterialRun.ReplaceFile()`: retried `File.Replace` | One BMW export failed on a transient lock before this |

The harness `tools/headless/ExportHarness.cs` (`tools/headless/export.ps1`) runs the same code headlessly. It loads a copy of the editor config, never the real one, and never prints keys.

## 2. Vehicle-agnostic shader profiles (`tools/shader-compiler/compile_all.py`, schema 3)

- **Scope:** every shader in the v293 vehicle shader database (225), keyed by the DJB2-xor hash of the lower-case asset name. This is the database's own key, verified for all 26 Murciélago shaders.
- **Parameters:** all symbolic except the static undamaged override `Ext_GlassDamage = 0`. The add-on specializes each material.
- **Textures:** every material-bindable texture stays a sample. The add-on folds samples whose decoded texels are uniform, plus runtime-only textures without a default or binding (zero; same rule as before).
- **Inputs:**
  - Interpolants are named by vertex-declaration element (`Elem<i>.<k>`); the add-on maps them to the section's usages.
  - Routing heuristics that need a role (`Pos` at element 0; a Half4 element as `Delta`) record it in `AssumedUsages`. The add-on rejects a section that disagrees.
- **Constant-stub vertex programs** (skinned layouts): element routing is impossible. For usage layouts seen in exports (`known-layouts.json` in the shader data folder, 20 layouts from the Murciélago and the M3 E46), usage-named entries use the unanimous routing of the program's other known layouts (0.6.1 rule). They replace the stub entries for matching sections.
- **External cbuffer:** in all 909 database programs where it is identifiable by size, it is `cb1`. This now breaks size ties, and a program without `cb1` reads no parameters.
- **Result:** 112 shaders profiled and 3 unresolved. The other 110 contain only forward 2-target programs (effects, decals); none of those is used by the Murciélago or the M3 E46. 12.3 MB of JSON, 1.2 MB gzip.

## 3. Add-on 0.7.0 changes (`unbound_profiles.py`, `unbound_surfaces.py`, `unbound_assembly.py`)

- **Profile lookup:** by shader hash. Entries match by section formats (`Formats`) or usage layout (`Layouts`); `element_inputs()` maps the inputs and checks the assumptions.
- **`Spec` additions:** input renaming, uniform-texture constants, and `substitute()`.
- **`prove_constants()`:** after specialization, the offline simplifier's randomized constant proof (three seeds, exact equality).
  - Inputs, view values and live parameters are branch-covering random leaves.
  - Every texture sample is an independent random value, so nothing that depends on texture contents is folded. The offline version modeled textures as functions of their coordinates, which could fold a constant-coordinate sample.
- **Per-instance vertex constants:** unknown ones stay symbolic. The slot is unsupported only if one still reaches an output.
- **Texture arrays:** slices are extracted from the exported raw resource in the add-on (mip-major size check, SHA-256 check) and packed into the .blend. Pre-extracted slices are no longer needed.
- **Names:** the assembly uses `VehicleName` and the item `UI` names; the set code is kept in `unbound_set_code` and added to the label only when two options share a name. Presets use their own name, else the brand all their items share, else the set code.

## 4. Validation

Results are summarized in `CHANGELOG.md`; run `tests/run_all.py` to reproduce them. Tests: `tests/test_existing_full.py` (copy of the delivered scene), `tests/test_vehicle.py` (fresh import of any export), `tests/test_node_compiler.py` (Cycles bake vs Python for every entry the export selects), `tests/test_fresh.py` (install ZIP, fail-closed defaults).

## 5. Open items

1. **Light-glass lenses that need engine constants:**
   - Murciélago orange indicator: `cb0[1].x`, effect 0.083 > 0.05.
   - M3 E46 `roboto/cs_lglass`: view exposure `cb2[44].w`, plus vertex-computed interpolants.
2. **License plate:** program permutations disagree; the selection key is unknown.
3. **Kit parts without a localized name:** shown as category + brand logo key + set code.
4. **Profiles for unseen skinned layouts:** usage-named entries exist only for layouts seen in exports. Exporting more vehicles and re-running `compile_all.py` extends them.
5. **Other games:** NFS Heat and Hot Pursuit Remastered need their own shader databases, programs and Frosty profiles. The exporter, names and compiler structure carry over; the profiles do not.
