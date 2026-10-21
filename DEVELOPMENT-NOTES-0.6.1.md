# NFS Unbound → Blender: development notes, 0.6.1

21 October 2026. Material pipeline of add-on 0.6.0 (exporter 0.4.0, assembly and slot restoration unchanged from 0.5.0).

## 1. Locations

| What | Path |
|---|---|
| Session workspace | `<workspace>\dev` |
| Add-on source (0.6.0) | `dev\addon060\unbound_batch` |
| Research tools and intermediate data | `dev\research` (contains game-derived data: `asm\*.asm`, `parsed.json`, `shader-defaults\`; do not distribute) |
| Validation workspace | `dev\validation` (`Murcielago-Export` = working copy of the export plus `shader-defaults`; `Murcielago-Export-bare` = without) |
| Deliverables | `dev\deliverables` |
| Extracted bytecode (405 programs) | `<work-root>\work\bytecodes` |
| Exported shader-default textures | `<work-root>\work\shader-defaults`, `...\paintnormalarray` |

Original user folders were only read, never written.

## 2. Pipeline

### Offline: research → `shader_profiles.json`

1. **`collect_programs.py`.** For every shader asset in `materials.json`, it takes all solutions from the parsed v293 DB (`parsed.json`): PS/VS bytecode GUIDs, constant records and vertex declarations.
2. **Probe extraction.** `probe.ps1 -Mode resdump` extracts the bytecodes. `disassemble_all.py` disassembles them with the game's `dxcompiler.dll`. Use `IDxcLibrary::CreateBlobWithEncodingFromPinned` (vtable 6), then `IDxcCompiler::Disassemble` (vtable 5). The tire PS output is byte-identical to the 0.5 disassembly.
3. **`dxil_eval.py`.** A symbolic partial evaluator for DXC listings. It handles phi and branch with path conditions, switch, local arrays (symbolic index → select chain), global constant arrays, and cbuffer substitution. Optional modes:
   - `ROWDOT` emits structured `dot3(vector, interpolant row)` for tangent frames.
   - `OPAQUE_LOOPS` makes loop-carried values opaque, which is used for forward glass.
4. **`analyze_ps.py`.** External cbuffer layout: one 16-byte register per external value, register = `Index − 1 − ValueStart`. It is validated against the cbuffer byte size. Bool externals (Type 1) are stored as integers.
5. **`build_profile.py` + `dag_tools.py`.**
   - Exact substitutions first. Uniform textures are folded to decoded texel values (for example Default_Black → 0). The runtime-only `scratches` 3D volume is 0 (undamaged). Derivatives are 0 (no specular AA). `STATIC_UNDAMAGED` overrides apply (`Ext_GlassDamage = 0`).
   - A randomized constant proof follows. Textures are modeled as deterministic functions of (slot, channel, coordinates), so rewritten samples stay comparable.
   - Verification compares the simplified graph with the full program using continuous random textures. Exact channel ties land on the game's own HSV `abs(hue)` discontinuity, so they are excluded.
6. **`profile_compiler.py`.**
   - Chooses G-buffer programs (≥4 targets) or dual-source forward programs (2 targets, glass).
   - Derives input semantics from every paired VS whose declaration matches a vehicle layout:
     - direct `loadInput` → `TexCoordN.u/v`, `Color0.rgba`
     - `Pos + deformation` → `ObjectPos`
     - `matrix·pos + instance translation` → `WorldPos`
     - instance translation → `ObjectOrigin`
     - frame columns → `WorldTangent/Bitangent/Normal`
     - VS polynomial of view constants → `ViewFade`
   - Detects tangent frames, extracts semantic outputs and serializes. Two variants with different interpolant layouts compiling to identical formulas (tire) confirmed the routing.
   - Permutation variants are compared numerically. A single bounded difference (≤0.1, one output) becomes a note. Anything larger becomes `Unresolved` (license plate).
   - Outputs used only for reporting, and emissive, are omitted when they need unresolved engine constants.

To regenerate (development Python):

```text
python -I research\profile_compiler.py <export>\materials.json research\profiles-all.json
copy research\profiles-all.json addon060\unbound_batch\shader_profiles.json
```

### G-buffer layout (decoded from the programs)

| Target | Contents |
|---|---|
| RT0.xy, RT0.w | Cube-face normal encoding. Face index in w: 0/1 = ±x, 2/3 = ±y, 4/5 = ±z. |
| RT0.z | `0.5 ± (0.001466 + 0.498·smoothness)`. The sign is the normal bit. |
| RT1.rgb | Base color |
| RT1.w | Specular/AO term from vertex color and normal (not mapped) |
| RT2.x | 0 for most shaders. 1 for gloss-coat paint; interpreted as coat weight. |
| RT2.y | Metalness |
| RT2.z | Diffuse AO (not mapped) |
| RT2.w | Shading ID (192/255, 196/255, 208/255) |
| RT3 | Emissive |
| RT4 (paint and rim only) | 12-bit coat normal, 8-bit coat smoothness, 8-bit sqrt-encoded second color |

### Add-on (`unbound_profiles.py`, called from `unbound_surfaces.profile_slot`)

The tire keeps the verified 0.5 profile. Every other occupied slot goes through these steps:

1. **`profile_for`.** Exact shader asset match.
2. **`parameter_values`.**
   - Uses material vector and bool parameters, else defaults or `StaticOverrides`.
   - Runtime values are matched by parameter **key**:
     - `PaintFacingColorParameter` → `RaceVehicleItemData.DefaultPaint`
     - `PaintMaterialParameter` → `.Material`
     - `WindowsTintParameter` → `.WindowsTint`
     - component defaults are the fallback
   - Runtime overrides material values; the bumper and fender body panels carry explicit grey paint vectors, so they demonstrate the rule.
   - A non-exposed parameter with a non-default value fails closed.
3. **`check_bindings`.** A folded texture (for example a livery bound to Default_Black) is re-verified from the actual image pixels. Slot sources are the material binding or the shader default asset.
4. **`Spec`.** Exact constant folding and dead-code removal. The live input is the paint RGB (a shared node group, "Unbound | Runtime Ext_Carpaint_Diffuse"). `frame((0,0,c),k)` = c·N.
5. **`NodeBuilder`.** Emits math nodes. Important exactness rules:
   - **Game V from Blender UV.** Game V = 1 − Blender V, and samples use Blender V = 1 − game V.
   - **Byte vertex colors.** These are sRGB-decoded by Blender. Recover them with the inverse transfer, then snap to k/255; without the snap, `floor(256·r)` trim selection flips.
   - **Pow pattern.** `exp2(k·log2 x)` → `POWER(x, k)`, because Blender's safe log turns `x = 0` into 1.
   - **Comparisons.** `icmp eq` → `COMPARE` with eps 0.5. `select` → Mix with factor ∈ {0, 1}.
   - **Texture arrays.** Layer = round(z), clamped, using slice images.
   - **Axes.** Frostbite ↔ Blender world axes come from the assembly collection's `fbx_to_blender_matrix`.
   - **Camera position.** Position + Incoming·ViewDistance.
   - **Tangent-frame products.** A Normal Map node with the per-mesh FBX basis signs (0.5 `tangent_basis`). If the basis is unverified, only the normal term is kept and a note is reported.
6. **Material.** A copy of the source material with the raw nodes framed, the compiled group, and a Principled BSDF. Forward glass is Transparent(transmittance) + Glossy(program Fresnel, roughness 0). Evidence for each material is in `unbound_surface_evidence_json`.

## 3. Evidence notes worth keeping

- **Streaming records and DXIL agree on UVs.** The shader's streaming records `[hash, 1, usage, tiles]` name the coordinate set of every default texture (usage 33/34/35/36 = TexCoord0–3). Their tiling factors (6, 8, 12, 3, 9, 1.5…) match the multipliers in the DXIL exactly.
- **Default-texture hashes.** 39 hashes were resolved with `probe hashes` (Frosty HashString). Opaque t1/t2 = `Vehicles/CommonTextures/Constants/Swatches_D/_M`. Paint t1 = `TrimSwatches_DA`. Paint t2/t3 = `paintnormalarray` (11 slices).
- **paintnormalarray layout.** The raw resource is mip-major: mip 1 of each slice matches the 2×2 box filter of its mip 0. Frosty's exported DDS for this array has an inconsistent payload size and was not used.
- **Paint selectors.**
  - `Color0.r ≥ 0.753` → `Ext_Carpaint_Diffuse`.
  - Otherwise trim cell `floor(256·r) mod 256` in the 16×16 `TrimSwatches_DA`.
  - Finish indices are `floor(16·Ext_Carpaint_Material.xyz)`; trims take them from the swatch alpha.
  - Stock `Material (0,0,0)` → gloss: metallic 0, base smoothness 1, coat weight 1, coat smoothness 1.
- **Glass.** Transmittance = `0.9·(1 − (0.992, 0.378, 0.161)·Color0.g·clamp((1−N·V)², 0.45, 0.9))·(1 − F)`. `Color0.a` selects one of four panel groups for `Ext_GlassDamage.xyzw`, which defaults to (0,1,1,1), i.e. cracked.
- **Light glass lens tints.** `C_ClearGlass`, `C_OrangeGlass` and `C_RedGlass` are named externals.

## 3a. Changes in 0.6.1

- **Profile schema 2.** `Profiles[shader].Entries[]`: one entry per distinct compiled result, listing `Programs` and `Layouts`.
  - The add-on picks entries by the section's vertex usages.
  - Several entries for one layout are specialized and compared numerically (`choose_entry`). A ≤0.1 difference confined to coat weight/smoothness is a note; anything else is unsupported.
- **Constant-stub vertex programs** (skinned layouts) fall back to the unanimous routing of the real vertex programs.
- **Vertex-constant pass-throughs** are named `VSConst:<name>.<c>`.
  - `g_facingParam.x` (rim) and `g_brakeAndCaliperCustomizeParam.y` (caliper) are 1 for front wheels, from `assembly.json` `Wheels[].Facing.Front`.
  - Polarity: the pixel programs compute `lerp(rear, front, clamp(v))`.
- **Runtime wheel values.** `(Front|Rear)(Rim|Caliper)(Primary|Secondary)(Color|Material)Parameter` keys take the default `RimsItemData`/`CalipersItemData` at that location (`Primary/SecondaryPaint|Material`).
- **Runtime exposure.** Every shader parameter whose key the vehicle binds at runtime (`ShaderParameterHandle` in `assembly.json`) is exposed when compiling.
- **Rebuild after assembly.** Fresh import runs the surface build again after assembly, because per-wheel inputs exist only on assembled parts.
- **Remembered export.** The located export root is stored on the scene (`unbound_export_root`) for later rebuilds.
- **In-game names (research, not in the add-on yet).**
  - Items carry `ItemUI` (`ItemUiMetaData`) with `MediumNameId`, `LongNameId`, `DescriptionId` and a brand texture.
  - `research/probe/LocProbe.cs` (`loc` mode) resolves them through Frosty's `FsLocalizationPlugin.FsLocalizationStringDatabase` headlessly. It needs `Config.Load` (a copy of the editor config) and `App.Logger`.
  - Example: `ID_VC_BUMPERFRONT` → "Front Bumper"; `ID_CAR_..._LONG_NAME` → "Lamborghini Murciélago LP 670-4 SV (2009)".

## 4. Open items (ordered by visible impact)

1. **Light glass ×4.**
   - Problem: `cb0[1].x` (an engine buffer outside the DB) scales the lit-lens F0 term; the `_low` and `normal` variants also have computed interpolants.
   - Next step: capture the engine constant, or show that the term is negligible with evidence.
4. **License plate.** Variants `ba416799` and `9d5c565c` (7 solutions each) disagree; find the permutation key.
5. **Engine constants for emissive.** `cb2[44].x/.w` (exposure or day/night) for interior, plate and rim glow; `cb2[0].y`.
6. **C# exporter.**
   - Export the shader-default textures, including `UT_defaultBlack_D` (only raw data was produced) and array slices.
   - Record shader DB and program hashes in `materials.json`.
7. **Further validation.**
   - Second vehicle.
   - Interactive Frosty menu export.
   - Material DB-row switching with compiled profiles.
   - Game-lighting comparison.

## 5. Validation commands (Blender 5.2.2)

```text
blender --background --factory-startup --python-exit-code 1 --python research\test_fresh_060.py -- <install zip> <scratch> <export with shader-defaults> <export without> <out>
blender --background --factory-startup <copy of merci-tires-0.5.0.blend> --python-exit-code 1 --python research\test_existing_full_060.py -- <addon parent> <materials.json> <out>
blender --background --factory-startup --python-exit-code 1 --python research\test_node_compiler.py -- <addon dir> <materials.json> <report.json>
```

Current results:

| Test | Result |
|---|---|
| Fresh import | 18/18 |
| Existing scene | 19/19 |
| Node compiler | 36 program/layout entries; each matches to ≤2.7e-4 except for 1–2 samples that sit on a float32 rounding threshold or singular point |
