# Changelog

Older Frosty plugin history: `frosty/AnsGarage/CHANGELOG.md`.

## 0.8.0 (in progress)

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
