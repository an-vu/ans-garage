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
| Shared parts | `TireLibrary` (Tires.cs), `RimLibrary` (Rims.cs) and `PlateLibrary` (Plates.cs, plates and frames), exported once through `SharedParts` (Tools > An's Garage > Export shared parts (tires, rims, plates)...): a checkbox per library, one folder, a subfolder each. Exporting only plates or only frames keeps the other half of `plates.json` and merges the texture list. |
| Rim library | `RimLibrary` (Rims.cs): shared `RimsItemData` whose meshes are in a real brand's folder under `vehicles/sharedcustomizedparts/wheels/`. |
| Liveries | `Liveries` (Liveries.cs): the car's `StaticLiveryTexturesAsset` (diffuse + material texture per livery), ticked in the export dialog or added later (`AddLiveriesMenu`); written to `<export>/liveries/liveries.json`. Labels come from the texture names without the car's own words; `Car` holds the paint, finish and plate text of the livery's `TemplateItemData`. |
| Version | `Core.Version` (Core.cs) is the only place the version is written. |

`tools/headless/ExportHarness.cs` (`tools/headless/export.ps1`) runs the same code without the Frosty window: export, assembly, defaults, tires, rims, plates (optionally only `plates` or `frames`), catalog, scan (moving parts of every vehicle), and lookup modes. It loads a copy of the editor config, never the real one, and never prints keys.

## 2. Shader profiles (`tools/shader-compiler/compile_all.py`, schema 3)

- **Scope:** every shader in the v293 vehicle shader database (225), keyed by the DJB2-xor hash of the lower-case asset name.
- **Parameters:** all symbolic except the static undamaged override `Ext_GlassDamage = 0`; the add-on specializes each material.
- **Textures:** every material-bindable texture stays a sample. The add-on folds samples whose texels are uniform, plus runtime-only textures without a default or binding.
- **Inputs:** interpolants are named by vertex-declaration element (`Elem<i>.<k>`); routing assumptions are recorded in `AssumedUsages` and checked by the add-on. `ObjectNormal` is the vector the vertex program turns into the world normal with the instance matrix (used by the dirt and dust layers).
- **Constant-stub vertex programs** (skinned layouts): usage-named entries exist for layouts in `known-layouts.json` (shader data folder). Exporting more vehicles and re-running `compile_all.py` extends them.
- **External cbuffer:** `cb1` wherever it is identifiable by size.
- **Result:** 115 shaders profiled; the rest contain only forward effect/decal programs. 1.3 MB gzip.

## 3. Add-on (`blender/ans_garage`)

- **Import** (`__init__.py`, modal, in slices): FBX → slot restore (`unbound_materials.py`) → surfaces (`unbound_surfaces.py` + `unbound_profiles.py`) → assembly (`unbound_assembly.py`) → moving parts (`unbound_animation.py`) → per-wheel surfaces.
- **Surfaces:** every slot is built from its compiled profile: specialization (`Spec`, `prove_constants`, `settle`), permutation choice (`choose_entry`), node emission (`NodeBuilder`). Unresolved inputs fail closed with a reason in the surface report.
- **Node trees:** Blender updates a whole tree after every edit, so `NodeBuilder` puts formulas into nested groups of at most `PART_NODE_LIMIT` (120) nodes and passes values between them through group sockets.
- **Dirt, dust and wet** (`CONDITIONS`, sidebar toggle): rebuilds the slots whose shader reads `Ext_DirtColor_Amt`, `Ext_DustColor_Amt` or `WaterCycle`, with those parameters live and driven by shared "Unbound | Runtime" groups.
  - The amounts are the sliders.
  - The colours are the paint shader's own constants (dirt 0.0331, dust 0.139).
  - The rain phase is 0.6 + 0.1 × Wet.
  - The numeric checks (engine constants, view constants, permutations) evaluate them only at slider values 0, 0.5 and 1.
  - A slot that can't be built with them live is built clean, and the reason is recorded.
- **Accepted runtime values, recorded on each material:**
  - engine constants with a measured effect ≤ 0.1 are set to 0;
  - glass permutations may differ by ≤ 0.12 in transmittance/reflectance;
  - `cb2[44].w` (camera exposure) is accepted when the specialized outputs don't change across 1e-5–100;
  - the LED license-plate permutation is a player customization: the printed plate is built.
- **Assembly:** item meshes are placed at their own customization component; geometry already in car space keeps its place.
- **Positions of hidden parts:** Blender only refreshes `matrix_world` for objects it evaluates, so a part in a hidden option still reads its old position. Every step that needs a world position uses `world_matrix` (`unbound_assembly.py`: parent chain × `matrix_parent_inverse` × `matrix_basis`) instead.
- **Moving parts:** 0–1 sliders from the blueprint's animation graph; see `assembly-data.md`.
- **Shared parts:** one folder (preference `shared_parts`, else the scene's); `shared_parts()` finds each library in it, or in a direct subfolder, by its index file (`tires.json`, `rims.json`, `plates.json`).
- **Libraries:** tires (`unbound_tires.py`) and license plates (`unbound_plates.py`, with typed plate text) swap textures and meshes through per-object overrides (`unbound_texture_overrides_json`, merged by `set_texture_overrides`, and `unbound_parameter_overrides_json`).
- **License plate stock:** the game's, from the car's `RaceVehicleItemData` sub-items (`game_stock`: background item `licenseplatebackground_<key>`, a `licenseplateframe_*` item if any, `DefaultLicensePlateText`); without a frame item, the library's `none` frame (the component's default no-frame textures). Applied at import when the plate library is set. The model's own plate textures are a placeholder the game replaces.
- **Sidebar:** `layout.panel` sub-panels (Blender 4.1+) keyed per car; "Name | value" rows (`field`); Dropdowns are `Menu` classes (`ANS_GARAGE_MT_*`) told their car and part group through `context_pointer_set` (`menu_field`); they run their operator with `EXEC_DEFAULT`. Messages go to the car's notes (`car_notes`), hidden per car in `ans_garage_hidden_notes`.
- **Report:** one readable text per import (`CarReport`, "An's Garage report: <car>", named in the car's `ans_garage_report`). The machine-readable surface report stays in memory (`unbound_surfaces.last_report()`, used by the tests).
- **Paint, per car** (`LIVE_FIELDS`): the paint colour and finish (`Ext_Carpaint_Material`) stay live in "Unbound | Runtime <parameter> | <car>" groups, keyed by the export folder; a profile group with live paint belongs to its car. Finish = `floor(16x)` (14 types, `FINISHES`), gloss = `floor(16z)` (`GLOSS_LEVELS`).
- **Wheels:** the car's own rim items are one choice group ("Rims", one option per set code); tires, brake discs and calipers stay the default. The rim library (`unbound_rims.py`) hides that group and places library rims on the rotation empties, fitted to the factory rim; placed parts carry `unbound_car_assembly`, so the surface builder uses the car's runtime values, wheel facing, controls and shader defaults. Rim colours (`RIM_COLOR_FIELDS`) are live per car.
- **Wheel fit** (`unbound_wheels.py`): the tire and rim vertex shaders move each vertex by `normalize(P.yz) * lerp(W.y, W.x + W.z, Color0.b)` and along the axle by `(0.5 - Color0.a) * 2 * W.w` when `g_facingParam.w` = 1 (rims) or `-Color0.a * W.w` when it is 0 (tires: one sidewall moves). W = `g_wheelCustomizeParam` (vertex constant buffer b1, row 0; b1 row 1 = `g_facingParam`, row 2.x = `g_rotation`, the spin angle), offsets from the modelled mesh; Color0 as raw bytes, so a byte colour attribute is encoded back from sRGB. A shared geometry-nodes group does the same per object; the offsets are stored in `unbound_wheel_fit` (`unbound_wheel_fit_tire` for the branch). Tires: W.y = (tire diameter − `OuterDiameter`)/2, W.x = (rim diameter − `InnerDiameter`)/2, W.z = 0, W.w = rim width − `Width`, the rim being the factory rim item; checked against a frame capture (Lotus Evija rear: 0.040105, 0.047770, 0, 0.091). Library rims: W.y = 0, W.x + W.z = the radius change, W.w = the width change (only the back lip has alpha 1). The sidewall size (`TireMeshInfos`, largest inner diameter = small sidewall) follows `SmallToMedRatio` / `MedToLargeRatio` against rim ÷ tire diameter. Factory rims are not resized: their blue channel is not a radius weight.
- **Brake size:** disc and caliper vertex shaders scale the whole mesh about the wheel centre by `g_brakeAndCaliperCustomizeParam.x` = rim diameter × `BrakeDiscRatio` / 0.4 (frame capture: 0.57221 × 0.77 / 0.4 = 1.1015), then spin it (`g_rotation`). A "Brake size" geometry-nodes modifier does the scale (`unbound_brake_scale`); a library rim brings its own ratio. `.y` / `.z` (and `g_facingParam.x` / `.y`) are the per-wheel front and side flags, +1 / −1 (`VS_CONSTANTS`; seen: rear-right = −1, −1).
- **Light glass permutations:** forward (glass) shaders come in full / reduced pairs differing only in `States[i][4]` bit 9. The game draws the full one (bit 9 clear) for its light lenses (frame capture: 67-sample program). `compile_all.py` records `StateBit9` per entry; `full_forward_program` keeps the full entries.
- **Verified vertex outputs** (`VERIFIED_OUTPUTS` in `profile_compiler.py`): outputs the pattern rules can't name, identified by evaluating the vertex program numerically against one the rules do read (caliper badge: the spin-rotated, normalized object normal; `.x` = `ObjectNormal.x`).
- **Engine constants** (`ENGINE_VALUES`): `cb0[1].x` (forward glass, b0 = function constants, row 1) = 1.0, read in the capture. Other engine constants are still set to 0 only when their measured effect is ≤ 0.1.
- **Paint finish** (`Ext_Carpaint_Material`): x = material / 15 (13 materials, `FINISHES`), y = colour shift / 15 (`COLOR_SHIFTS`), z = 0 / 0.075 / 0.15 (Gloss, Satin, Matte); the game's 13 presets are `FINISH_PRESETS`, exact captured values.
- **Liveries** (`unbound_liveries.py`): texture overrides of `Ext_T_Livery_Diffuse`/`Ext_T_Livery_Material` on every slot whose shader samples them. They are `OPTIONAL_OVERRIDES`: a slot that can't be built with them is built without, with `LiveryNotApplied` in its evidence.

## 4. Validation

`tests/run_all.py`: parallel, skips tests whose inputs are unchanged. `existing` (a 0.5-era scene upgraded in place), `fresh` (install ZIP), `nodes` (Cycles bake vs Python for every selected entry, clean and with dirt/dust/wet live; at most 1% of samples off by more than 1e-3), `tires`, `plates`, `conditions`, `paint`, `liveries`, `rims`, `static`, and `vehicle:<name>` for nine cars covering every moving-part pattern found by the scan of all 200 vehicles. Each vehicle test shows every part option and checks that its parts sit where the assembly placed them.

## 5. Open items

1. **Aventador S front caliper:** the "brembo" text shows twice. Unchecked whether the caliper texture prints it and the badge adds it again (possibly as in the game) or the badge is misplaced.
2. **Unchecked from one wheel of the capture:** the +1 values of the front/side brake flags (only rear-right = −1, −1 was seen); the rim's `BrakeDiscXOffset` (axial disc offset) isn't applied; which rim diameter the tire bead uses when the rim item and TireConfig `RimDiameter` differ.
3. **Dirt on caliper badges:** the skinned badge program `de1cb89d` reads bone buffers and isn't verified; a spare caliper that isn't on a wheel keeps its badge clean.
4. **macOS:** not yet tried on a Mac (no Windows-only APIs or paths found by a static scan).
5. **Other games:** NFS Heat needs its own shader database, programs and profiles (same Frosty route). Hot Pursuit Remastered is not Frostbite and would need a separate exporter.
