# Changelog

Older Frosty plugin history: `frosty/AnsGarage/CHANGELOG.md`.

## 1.0.3

- **License plate library:** put a real plate on any car.
  - **Plates:** all 50 US states (plus classic Idaho), Washington DC, American Samoa, three Japanese plates, and NFS places (Lakeshore, Palm City, Rockport, Fortune Valley, Bayview, Olympic City, Palmont City, Fairhaven, Redview, Tri-City Bay, Canyon State, Sunshine Country, Merica City). No game logos, animated or themed plates.
  - **Export once in Frosty:** **Tools → An's Garage → Export license plate library...**
  - **In Blender:** use the sidebar's **License plate** section. **Choose plate…** searches the library (type "cal", "japan"...); **Stock** brings the car's own plate back. It applies to every plate on the car, in every bumper option.
- **Plate text:** **Plate text…** in the same section. Up to 7 letters, digits or spaces, drawn with the game's own embossed plate font.
  - The game packs the characters into `Ext_LicensePlateText1`/`2`: seven font cells, 0–9 then A–Z, 36 = empty.
  - Plates now default to blank. 1.0.2 showed "0000000", because the game fills the text in at runtime and its default is 0 in every cell.

## 1.0.2

- **License plates build on every car.** The plate shader comes in two versions that differ only in one texture: the printed plate font or an LED mask (`license_plate/licenseplate_ledmask_a`), a player customization. The printed plate is built, and the material records the LED version as skipped.
- **BMW-style light glass (`cs_lglass`) builds.** Its formula reads the camera exposure (`cb2[44].w`), which the renderer sets live. With the car's own material values no output changes for any exposure from 0.00001 to 100 (checked per material), so none is needed. The check is recorded on the material (`ViewConstantIndependence`); a material whose output did change would stay unbuilt.
- **Results:** Murciélago 104/104 visible surfaces built (was 103), BMW M3 E46 106/107 (was 100). The BMW's last lens has two shader versions that disagree in transmittance by up to 0.47, and nothing says which one the game uses, so it stays unbuilt.
- **Switching part options and presets is instant:** about 2 s → 0.01 s per click on the BMW M3 E46. Every switch used to rewrite the visibility of every object in the car (about 1,500), and each write made Blender re-evaluate the scene; now only changed values are written.
- **Tests:** `tests/run_all.py` runs tests in parallel (`--jobs`, default 4) and skips tests whose inputs are unchanged since they last passed. `full` forces all; `quick` runs nodes + Murciélago. The whole suite takes about 3 minutes instead of 40.

## 1.0.1

- **Item meshes are placed at their own customization component**, not only spoilers. The Diablo SV's pop-up headlights, modelled around their own origin, used to sit at the car's origin (0, 0, 0); they now sit in the nose. Geometry already in car space keeps its place, as before.
- **Pop-up headlights slider** (group *Lights*), from the game's opening sequence. The game plays an opening and a closing sequence on light events; the closing one is its reverse and is listed as skipped.
- **The file browsers for tires.json, manifest.json and textures.json show those files.** The exact-name filters hid them.
- **Sidebar:** the panel is titled **An's Garage 1.0.1**, and long text wraps to the sidebar's width instead of being cut off.
- **Kit brands read like brands:**
  - kit parts without an in-game name show "Spoiler · APR" instead of "Spoiler · apr logo";
  - the exporter finds the brand name in the game's own text: Alchemist, APR, BMW, Carbon, Chidori, Lamborghini, NexTech, Pandem;
  - Big Country Labs, missing from the game's text, is spelled by hand; any other brand the text lacks keeps its logo key, title-cased;
  - re-run the export's assembly step to get the names.
- **Frosty car picker:** a two-column table (car and folder), sortable by clicking a header; the full folder path shows on hover.

## 1.0.0

- **Moving parts:** each car gets a 0–1 slider per moving part in the An's Garage sidebar: 0 closed, 1 fully open, 0.5 halfway, keyframable like any property. **Close all** sets them back to 0.
  - **Active aero:** rear wings, their airbrake stage, and the Murciélago's shoulder air vents.
  - **Doors** (scissor, butterfly or conventional), **windows**, **hood** and **boot**.
- **The motion is the game's own:**
  - the hinge points, angles, travel and ease curves come from the vehicle blueprint's animation graph;
  - parts mounted on a moving part follow it, such as the Murciélago's door mirrors on its doors;
  - only the stock spoiler moves; aftermarket spoilers stay still, as in the game.
- **Not reproduced:** the game's speed logic (the wing rising above a set speed), body roll and exhaust shake.
- **Sliders at 0 leave the car exactly as imported.**
- **Cars imported with an earlier version:** use **Add moving parts** in the sidebar. Wings and vents also need the export re-run with An's Garage for Frosty 1.0.0, which writes their keyframes into `assembly.json` (`TrackData`).
- Results: Murciélago 7 sliders, P1 7, Chiron Sport 6, each moving its parts as in the game data.

## 0.9.0

- **Tire library:** swap a car's tires for Falken or Toyo tires at the car's own tire size, with a plain or brand-lettered sidewall.
  - Export the library once in Frosty: **Tools → An's Garage → Export tire library...**
  - Then choose the tires in the sidebar's Tires section. **Stock** brings the car's own tires back.
- **Light glass:** more headlight and taillight lenses build, including the Murciélago's orange taillight glass, which used to render as a black block.
  - A constant the game sets while running is taken as 0 when it changes the result by at most 0.1 (was 0.05).
  - Light-glass shader versions may differ by up to 0.12 in transmittance and reflectance.
  - Each material records the value it assumed and the difference it measured.
  - Lights render switched off (no glow).
- **A moved .blend file** finds its export textures again instead of failing on a broken relative path.

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
