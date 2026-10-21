# Changelog

Older Frosty plugin history: `frosty/AnsGarage/CHANGELOG.md`.

## 0.8.1

- **Blender stays usable while a car imports:**
  - the import runs in short steps, so the viewport keeps drawing and parts appear as they come in;
  - a progress bar in the status bar shows the stage, percent, elapsed time and a Cancel button (Esc also cancels);
  - the An's Garage sidebar tab shows the same with the vehicle name.
- **Undo is blocked until the import finishes**, because the scene is still being built.
- **Spoilers on cars with a spoiler mount** (Countach LPI 800-4, Chiron Sport, P1 and similar) are placed at the mount's position. Before, they sat inside the car at its origin, so the Countach's stock active spoiler looked missing. Geometry that is already in car space keeps its place.
- **Scripts and background mode** still import in one go.
- **Frosty plugin:** no changes; the version is kept in step at 0.8.1.

## 0.8.0

- **Faster import in Blender:**
  - Murciélago: about 5.5 min → **55 s**; BMW M3 E46: about 25 min → **1 min 47 s**. The built materials are unchanged.
  - Each texture is checked for a single flat colour once, and the answer is stored on the image. It used to be re-read for every slot: about 5,500 full pixel reads for 150 images.
  - Simplified shader formulas are shared between materials whose inputs are identical.
  - Progress shows as a percentage on the mouse cursor and as stage lines in the system console (Window → Toggle System Console).
- **Faster export in Frosty:** BMW M3 E46 export 153 s → **73 s** (identical output). Progress files are rewritten at most every 10 seconds instead of after every part, and `manifest.json` now records the seconds spent in each export stage (`Timings`).
- **New names:**
  - **An's Garage for Frosty** (was UnboundBatchExport): **Tools → An's Garage → Export vehicle...**; `AnsGarage.dll`.
  - **An's Garage for Blender** (was Unbound Batch Manifest): **File → Import → An's Garage vehicle (.json)**; sidebar tab **An's Garage**.
- **One shared version** for both parts from 0.8.0 on.
- **Upgrading:** remove the old `UnboundBatchExport.dll` from Frosty's `Plugins` folder, and uninstall the old "Unbound Batch Manifest" add-on. Existing .blend files keep working: their stored data is unchanged.

## Blender add-on 0.7.0 (with Frosty plugin 0.5.1)

- **Any vehicle:** shader profiles cover the whole vehicle shader database (112 shaders), keyed by the game's shader hash. Each one is specialized to the car's own materials and mesh layout.
- **In-game names** for the car, part categories, options and kit brands. Kit parts without a localized name show category + brand logo key + set code.
- Texture arrays (paint flakes) are decoded from raw export data. Uniform textures are folded at build time.
- Parts with repeated identical faces now match their material slots (Blender removes those faces on import).
- Results: Murciélago 102/104 visible surfaces built; BMW M3 E46 100/107.

## 0.6.1

- Rims, brake calipers and caliper badges use the stock wheel items' values; front and rear wheels each get their own.

## 0.6.0

- Car paint, opaque body, chassis, glass and lights from compiled source shaders.

## 0.5.0

- Static tire material.
