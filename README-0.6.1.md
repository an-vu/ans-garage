# UnboundBlender 0.6.1: compiled source-shader materials

21 October 2026. Replaces 0.6.0. C# exporter 0.4.0 unchanged.

## Which file to use

| File | Use |
|---|---|
| `UnboundBlender-0.6.1.zip` | **Install this** in Blender (Preferences → Add-ons → Install from disk). Replaces 0.5.0 and 0.6.0. |
| `merci-materials-0.6.1.blend` | **Open this** to see the result. It is your `merci-tires-0.5.0.blend` with 0.6.1 materials built; textures are packed, so it opens anywhere. |
| `shader-defaults/` | Shared game textures that the vehicle shaders read (material swatch atlas, paint trim swatches, flake normals, grime masks). Needed for fresh imports. The same folder works for every vehicle. Game data: keep private. |
| `UnboundBlender-0.6.1-source.zip` | Source, research tools, tests and validation reports. Not an install package. |
| `validation/` | Reports and renders listed below. |

## Workflow

**Fresh export.** Copy `shader-defaults/` into the export folder, next to `manifest.json`. Then **File → Import → Unbound batch manifest (.json)**. Materials are built automatically before assembly.

**Existing scene.** Use **N → Unbound → Locate export manifest…** and pick the export's `materials.json`. If the shader-default textures are elsewhere, use **Locate shader default textures…** and pick `shader-defaults/textures.json`.

**Paint.** **N → Unbound → Vehicle paint** changes the paint color of every body-paint surface at once. It starts at the car's stock paint from the game data.

Part switching and presets work as before.

## What changed

0.5.0 connected one hand-made tire shader. 0.6.0 translates the game's own compiled pixel programs into Blender nodes. The research pipeline does the following:

1. Disassembles all 405 programs used by the Murciélago's 26 vehicle shaders, using the game's `dxcompiler.dll`.
2. Evaluates each program symbolically at the shader-database defaults and the static state (dry, clean, undamaged, time 0).
3. Proves which terms are constant and checks that the simplified formulas match the full program.
4. Stores the formulas (not the bytecode) in `shader_profiles.json`.

The add-on then does the following:

1. Matches each material to its shader.
2. Checks the material's own parameters and textures against the profile's assumptions.
3. Builds the nodes.

It fails closed with a stated reason when anything is unresolved.

Key findings behind the body materials:

- **Opaque parts** (plastics, metals, carbon) have no color texture of their own. They sample the shared `Swatches_D` (color) and `Swatches_M` (metal and smoothness) atlas through **TexCoord1**. They have a grime layer driven by vertex alpha and an albedo clamp done in HSV.
- **Car paint** takes its color from the runtime parameter `Ext_Carpaint_Diffuse` and its finish from `Ext_Carpaint_Material`. The vehicle data binds them by key to `PaintFacingColorParameter` and `PaintMaterialParameter`. The values come from `RaceVehicleItemData.DefaultPaint = (0.768, 0.399, 0.0035)` and `Material = (0, 0, 0)`. Vertex `Color0.r` switches trim areas to the `TrimSwatches_DA` cells. Paint writes a second clear-coat layer, which is mapped to Principled Coat.
- **Window glass** comes from the transmittance target computed before lighting, plus the program's Fresnel weight. The window tint comes from `RaceVehicleItemData.WindowsTint`.

## Results on the Murciélago

| Check | Result |
|---|---|
| Shaders with a resolved profile | 21 of 26 (calipers and caliper badges added) |
| Fresh import: visible surfaces of the assembled car built | **98 of 104** |
| Your scene: occupied slots built (all source and assembled objects) | 529 built, 59 unsupported, 0 errors (96 of 102 visible) |
| Formulas vs the game's full program (random inputs) | max difference ≤ 1.8e-5 |
| Blender nodes vs formulas (Cycles bake, 2,304 samples per shader) | ≤ 2.7e-4. Exceptions: 1–2 samples in paint, chassis and interior, traced to float32 rounding at a singular point of the grime curve |
| Geometry, UVs, colors, normals, material indices, transforms, collections, visibility | Unchanged (hash-checked) |
| Presets and all 67 individual part options; save and reopen | Pass |
| Fresh import from the install ZIP, and the missing-texture fail-closed case | 18/18 pass |
| Existing-scene validation | 19/19 pass |

Renders (neutral studio lighting, not game lighting): `validation/final-*.png`.

## New in 0.6.1

- **Rims, brake calipers and caliper badges** now use the stock wheel items' paint and material values (dark-grey rims, light-grey six-piston calipers), linked to the shaders by parameter key.
- **Front and rear wheels** get their own values: each wheel part's front/rear selector comes from the assembly's wheel facing. The programs blend the rear parameter toward the front parameter by that selector.
- **One shader program can route data differently per vertex layout**, so profiles are now compiled per program and vertex layout.
- **Alternative programs** for the same layout must agree once specialized with the car's real values. The rims and paint differ only by a 0.7/0.8 coat constant, which is reported. The license plate disagrees, so it is reported as unsupported.

## Not finished (still dark or approximate)

**Not built (visible on the car):**

- **Head-, tail- and indicator-light lenses** (`lightglass` ×4). The lens Fresnel uses an engine constant that isn't in the shader database.
- **License plate.** Two program variants disagree, and the selection key is unknown.

**Built, with limits:**

- **Emission** is omitted on interior screens, license plate and rim glow (needs engine exposure constants). Lights' own emissive shaders are built.
- **Not mapped:** ambient-occlusion terms from vertex colors; the paint's second-layer color; glass reflections from the game's lighting (a smooth Glossy lobe weighted by the program's Fresnel is used instead).
- **Interpretations, not verified against the game's deferred lighting:**
  - clear coat taken from the paint G-buffer
  - roughness = 1 − smoothness
  - IOR 1.5
  - glass target as transmittance
- **Static-state choices:**
  - time 0, dry, clean, undamaged
  - glass damage 0 (the shader default shows cracked side windows)
  - per-vertex atmospheric fade = 1
- **Paint permutation note:** two trim swatch cells give coat smoothness 0.8 or 0.7 depending on an unresolved permutation.
- **Orange-peel detail** (0.4% of the coat normal) is disabled on 19 paint objects whose tangent basis didn't match the source FBX.

**Not tested:**

- a second vehicle
- the interactive Frosty menu export
- pixel comparison against the game
- material database-row switching with the new profiles

The C# exporter doesn't export `shader-defaults` yet; copy the folder in manually.
