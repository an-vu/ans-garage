# 1.0.5

- Vehicle exports write the shared shader default textures once into `shader-defaults` next to the car folders and skip them when it is complete. A car's own folder drops from about 450 MB to about 70 MB.
- A texture's raw payload (`.texture-data.bin`) is written only for texture arrays, cube maps and unsupported formats; every DDS is still checked against the payload's SHA-256.
- Removed **Refresh materials of existing export...** (undocumented; re-export instead).
- `Core.Version` is the single version string; the tire and plate library menus share `LibraryMenu`.

# 1.0.4

- No changes; version kept in step with An's Garage for Blender 1.0.4. (The headless exporter gained a `scan` mode; it is a tool, not part of the plugin.)

# 1.0.3

- **Tools → An's Garage → Export license plate library...** exports the real plate backgrounds once into `AnsGarage_PlateLibrary` (`plates.json` + `textures/`): US states and territories, Japanese plates and NFS places.
  - Labels are written by hand, because plates have no localized names.
  - Two game item keys are misspelled (`neewjersey`, `olimpiccity`); their textures are spelled correctly and are what the library uses.
- Headless exporter: `plates <out dir>` mode.

# 1.0.2

- No changes; version kept in step with An's Garage for Blender 1.0.2.

# 1.0.1

- **Choose vehicle...** shows a two-column table, Car and Folder (the folder's own name; the full path on hover). Click a header to sort.
- `assembly.json` item `UI` gains `BrandTitle` and `BrandTitleSource` for kit parts without a localized name. They hold the brand name found in the game's localized text for the logo key: an equal string, else the leading words of localized names (APR from "APR GT250"). Keys without a match get none.

# 1.0.0 — moving parts

- `assembly.json` gains `TrackData`: the keyframes of the vehicle's sequence tracks (active wings, airbrakes, vents) as plain numbers, 6 per key (time, value, in-tangent x/y, out-tangent x/y). An's Garage for Blender 1.0.0 turns them, together with the blueprint's door, window, hood and boot curves (already in `assembly.json`), into 0–1 sliders.
- Older exports: re-run the export (or **Add assembly to existing export...**) to get `TrackData`.

# 0.9.0 — tire library

- **Tools → An's Garage → Export tire library...** exports the Falken and Toyo tires once (both sizes and plain or brand lettering), for the Blender add-on's Tires section.

# 0.8.1

- No changes; version kept in step with An's Garage for Blender 0.8.1.

# 0.8.0 — renamed to An's Garage for Frosty

- `AnsGarage.dll`, menu **Tools → An's Garage**; version shared with An's Garage for Blender. Remove the old `UnboundBatchExport.dll` from Frosty's `Plugins` folder.
- The vehicle list cache moved to `%LOCALAPPDATA%\AnsGarage\` (read once more after upgrading).
- About twice as fast: `manifest.json` and `materials.json` are rewritten at most every 10 seconds instead of after every part (BMW M3 E46: 153 s → 73 s, identical output).
- `manifest.json` records the seconds spent in each stage (`Timings`).

# 0.5.1 — dialog fixes

- The export dialog and vehicle picker use auto-sizing layouts, so text and buttons are not clipped at Windows display scaling above 100%.
- **Choose vehicle...** no longer freezes Frosty: it reads the game data in the background with progress (about 3.5 minutes the first time) and caches the list in `%LOCALAPPDATA%\UnboundBatchExport\vehicle-catalog.json`; later opens are instant. **Refresh list** re-reads it.
- Export data is unchanged from 0.5.0 (files now record `PluginVersion` 0.5.1).

# 0.5.0 — any vehicle, in-game names, shader default textures

- **Choose vehicle...** button: lists every NFS Unbound vehicle by its in-game name (200 entries), matched to its blueprint folder through the vehicle bundle hash. When one folder holds several vehicles (for example the BMW M3 E46 and the M3 GTR Legends Edition), the chosen vehicle's blueprint is used for assembly.
- **In-game names** in `assembly.json`, read from each item's `ItemUI` metadata and resolved through Frosty's NFS localization plugin:
  - `VehicleName` (long, medium and short), for example "Lamborghini Murciélago LP 670-4 SV (2009)";
  - per item and preset `UI`: `Category` ("Front Bumper"), `DisplayName` ("Stock", "Liberty Walk", "CSL"), `BrandName`, the brand logo key and every raw string id;
  - `DisplayName` is left empty when the localization has neither an item name nor a kit-brand string; ids are never guessed.
- **Shader default textures**: after the material pass, the shared textures that vehicle shaders sample by default are exported to `shader-defaults/` with a `textures.json` index. The list ships next to the DLL (`UnboundShaderDefaults.json`, 53 assets) and is generated from the Blender add-on's compiled shader profiles.
- Atomic JSON/DDS replacement now retries briefly when an indexer or antivirus holds the previous file (an export failed on this before).
- Geometry, texture and material export routines are unchanged.

# 0.4.0 — source slots, UV provenance and assembly

- Extends the existing native FBX export; its geometry export method is unchanged.
- Adds vehicle/item/blueprint relationship extraction, authored wheel centers, shared tire/brake discovery and Blender assembly controls.
- Adds readable part/variant collections and source presets while retaining original mesh datablocks and attributes.
- Restores original material arrays and section-derived face indices using verified native FBX geometry identities.
- Resolves presets and material database rows by source identity; supports explicit material-row selection on selected Blender instances.
- Records exact native FBX UV-layer encounter order, including auxiliary layers. Texture sampling UVs remain unknown where source evidence is absent.
- Preserves named packed tire channel semantics, source color-space evidence, raw values and missing/unsupported diagnostics.
- Adds seven inactive Principled templates and DDS inspection nodes. No finished surface appearance is claimed.
- Filters unrelated material databases using SDK dependency tables with a fallback for unknown tables.
- Explains the rear-fender count difference: six repeated-index zero-area FBX triangles removed by Blender, no nondegenerate surface loss.
- Includes fresh full-batch and Blender regression results. Full Frosty GUI export remains unverified; see `TESTING.md`.

# 0.2.0 — textures and source materials

- Adds automatic material pass after geometry and a materials-only command for existing manifests.
- Captures material/shader/preset/variation graph, raw parameters, LOD0 section-slot mapping and vertex declarations.
- Exports deduplicated original DDS textures through Frosty's native functionality; preserves source payloads and hashes.
- Records unsupported data and unresolved semantics without guessing packed channels or UV selection.
- Leaves the 0.1.2 geometry export routine and Blender geometry importer unchanged.
- Validated actual Murciélago references/textures, 43 C# checks and two real geometry regression exports. See TESTING.md for incomplete tests and the pre-existing rear-fender polygon discrepancy.

# 0.1.2

- Keep `.fbx` as the final extension of the temporary file so the native SDK does not append an unexpected extension.
- Add two filename regression assertions and a standalone native SDK filename smoke test.
- Recover the user's existing 97 FBX files separately, without changing FBX bytes or the original export directory.

# 0.1.1

- Fix mesh resource lookup: Frosty's boxed `ResourceRef` is unboxed and converted through the SDK's UInt64 operator instead of `Convert.ToUInt64(object)`.
- Add six resource-reference regression assertions using the actual Frosty SDK, including high-bit unsigned IDs and the reflection path used during export.
- Record plugin version in each manifest.
- Validated assembly/API/helper tests against the user's installed HarGabt release. Live export retry remains pending.

# 0.1.0

Initial experimental release. User runtime test found 97 meshes, but all failed at resource conversion before FBX export. Superseded by 0.1.1.
