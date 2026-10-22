# Changelog

Older Frosty plugin history: `frosty/AnsGarage/CHANGELOG.md`.

## 1.0.9

- **Exact tire fit:** tires are reshaped per vertex the way the game's tire shader does it, instead of scaling the whole tire.
  - The tread goes to the car's tire diameter, the bead to the rim and the sidewalls to the section width; the sidewall in between stretches. Before, the bead grew with the tire and could end up outside the rim lip (5 mm on the Murciélago's rear).
  - The game has three sidewall sizes per tire (small, medium, large) and picks one from the rim-to-tire diameter ratio. The car export now includes all three and the right one is placed (the Murciélago: small at the front, medium at the rear). Exports from before 1.0.9 hold only the small one and still import.
  - In Blender this is a **Wheel fit** geometry-nodes modifier on each tire. Its three offsets are the shader's (`g_wheelCustomizeParam` W.y, W.x + W.z, W.w), worked out from the car's tire configuration and the part sizes; the game capture will confirm the game's own values.
- **Library rims** are resized the same way: the barrel and lip to the factory rim's diameter, the back lip to its width, the hub and spokes following each rim's own vertex weights. Before, the whole rim was scaled.
- **Library tires** pick their sidewall size with their own thresholds (off-road tires use lower ones) and are fitted per vertex. Re-export the tire library to record the thresholds; older ones use the stock tire's.
- **Export options:** a **Moving parts** tick box (ticked by default). Untick it for a static model; **Add moving parts** in Blender still builds them later.
- **Export folder named after the car** (its in-game name, " (2)" etc. if it exists), instead of `Unbound_<date>_<id>`.
- **Faster import:** about twice as fast (the Murciélago: 76 s → 36 s). FBX files load into a staging scene through the FBX reader directly, mesh signatures use numpy, compiled shader checks and textures are cached. The rim library imports a brand the first time one of its rims is chosen.
- **Tests:** 12 at a time by default; `static` (static export); every vehicle test checks the scene keeps its frame rate and the stock tire fit (formula, size, sidewall choice); `tires` and `rims` check the library fit.

## 1.0.8

- **The car's own wheel sets:** a **Wheels** choice in the car's parts. 31 of the 200 cars have more than one factory set (the Aventador S has four; the BMW M3 E46 has Stock, Custom and RZR). Body kits that come with their own wheels switch them too. The game names every set "Stock", so the others show their set code.
- **Rim library:** 122 aftermarket rims from 16 real brands: 3SDM, BBS, Cosmis, Fifteen52, HRE, Loma, Nismo, Rotiform, RTR, SSR, Vorsteiner, Vossen, Watanabe, Weds, Weld Racing (incl. Rekon) and Work.
  - Exported once in Frosty (**Tools → An's Garage → Export rim library…**, about 115 MB).
  - Chosen per car in the sidebar (**Rims → Choose rim…**, Stock = the car's own wheel set).
  - NFS-made wheels are left out: turbofans, LED and "ghost" wheels, drag and off-road wheels, the generic ones. Another car's factory wheels never come from the library, as in the game.
  - A library rim is scaled from its declared size to the car's factory rim on that axle (object scale; the game resizes rims in the wheel shader).
- **Rim colors**, live per car on factory and library rims: primary and secondary, front and rear, with **Stock rim colors**.
- Library parts placed on a car (rims) are built against that car: its wheel inputs, rim paint and shared shader default textures.
- Tire and rim libraries share one import and placement helper.
- **Tests:** `rims` (library, placement, sizing, rim colors, stock); every vehicle test checks each wheel set mounts on all four wheels.

## 1.0.7

- **Paint finishes**, per car in the sidebar's new **Paint** section: the paint colour, a **Finish** list and **Stock / Gloss / Satin / Matte**.
  - The game's paint shader knows 14 finish types (`Ext_Carpaint_Material.x`); types 3–13 each use a layer of the flake/carbon texture array.
  - Names come from each layer's texture and the stock cars that use the type: Metallic flake (69 cars), Brushed metal (the DeLorean), Forged carbon, Damascus, Honeycomb carbon, four carbon weaves, two fine flakes. The game keeps its own name table in code, so the descriptive names get checked in the game capture (1.0.9).
  - Gloss levels (`.z`) are measured from the shader: Gloss = full clear coat, Satin = softer coat, Matte = no coat.
  - **Stock** is the car's own value. There's no "factory colour" list: the game has none per car (every manufacturer swatch is empty).
- **Each car has its own paint:** paint colour and finish controls are per car. Before, a second car in the scene took the first car's paint.
- **Stock liveries:** the game's own designs for a car (AI racers, rivals, story, delivery and police cars).
  - Frosty's export dialog lists the car's liveries with a tick box each (all ticked); untick the ones you don't want.
  - **Tools → An's Garage → Add liveries to an existing export…** adds skipped ones later without exporting the car again.
  - Blender: a **Livery** picker per car (None = stock paint). A livery overrides the paint shader's livery textures on every paint slot.
  - Most liveries belong to a car template in the game (the AI racer's, rival's or story car's setup). **Use its paint and plate text** gives the car that paint, finish and plate text, e.g. Rival: Medusa is gold metallic with an M3DUSA plate.
  - Window glass also reads the livery in the game, but with one on it needs an unknown lighting constant (the same as the P1/Diablo lenses): windows keep their stock look, with the reason in their evidence.
- **Fixes:**
  - texture lookups are cached per car *and* per extra texture folder, so a whole-car rebuild can't give one part another part's plate or tire textures;
  - texture overrides merge, so a plate and a livery on the same part keep each other;
  - adding liveries later merges the texture index instead of replacing it.
- **Headless tool:** `liveries` (list or add a car's liveries) and `textures` (export named textures, for research).
- **Tests:** `paint` (two cars, separate paint, finishes) and `liveries` (apply, switch, none, windows stay stock, plate kept).

## 1.0.6

- **Dirt, dust and wet:** a car still imports clean and dry. **Add dirt, dust and wet** in the sidebar rebuilds its surfaces with three 0–1 sliders (**Remove** goes back).
  - The sliders drive the game's own formulas, which the game sets while driving.
  - The paint and body shaders have their own dirt and dust colours built in (dirt 0.0331, dust 0.139). The light lenses read the colour at runtime and get the same values, so lens and body match.
  - **Wet** follows the rising edge of the shaders' rain cycle: rain phase 0.6 + 0.1 × Wet, and 0 when dry.
  - The sliders can be keyframed: each one drives its node group through a driver, so keyframed values play back and render.
  - Surfaces that can't take the controls stay built clean, with the reason in their evidence. On the Murciélago that is 47 of 589:
    - 36 light-glass slots: every light-glass shader has a full program (dirt and dust tint the lens) and a reduced one (amount only). They agree when clean but not when dirty, and the data doesn't say which one the game draws;
    - 11 calipers: the dust mask is read at a per-wheel coordinate (`g_brakeAndCaliperCustomizeParam.y/.z`), and the engine sets `.z` at runtime.
- **Object-space normal:** the shader compiler recognises the normal the vertex program passes before the instance transform. The dirt and dust layers use it; 36 profiles changed, and the Murciélago builds 589 slots (was 585).
- **Faster material building:** Blender updates a whole node tree after every edit, so large formulas are now built in nested groups of at most 120 nodes. Renderers flatten groups, so the result is the same.
  - The node test went from 200 s to 158 s, with twice as many cases.
  - Enabling dirt on a whole car went from 113 s to about 40 s.
- **Node test:** now fails when Blender and the Python evaluation disagree beyond 1e-3 on more than 1% of samples. It also covers every shader again with the dirt, dust and wet controls live.

## 1.0.5

- **Exports are about 85% smaller:** the Murciélago went from 443 MB to 60 MB.
  - The shared shader default textures (about 240 MB, the same for every car) are written once into a `shader-defaults` folder next to the car folders and reused by every later export. The Blender add-on already looks there.
  - Textures are no longer stored twice: the raw payload is kept only for texture arrays, cube maps and formats the DDS writer can't hold. Every DDS is still checked against it.
  - Exports already on disk keep working.
- **Exports are faster:** a second car skips the shared textures (Integra Type-R: 44 s → 38 s).
- **Imports do less repeated work:**
  - the add-on's modules and the 1.3 MB shader profiles load once instead of on every build;
  - texture paths are resolved once instead of thousands of times;
  - the assembly step no longer parses the whole `materials.json`.
- **Stock tires use the compiled tire shader**, like every other material. The separate hand-written 0.5 tire material and `tire_shader_evidence.json` are gone.
- **Removed legacy parts:**
  - Blender: the **File → Import** entries "assemble imported meshes" and "restore material slots" (the import does both), the raw "Source material variants" row switcher, and pre-Blender-4 fallbacks.
  - Frosty: the undocumented **Refresh materials of existing export...** menu.
  - Tools: old command-line entry points of the shader compiler.
- **Less duplication:**
  - the version is written once per part (`bl_info`, `Core.Version`);
  - the tire and plate libraries share one folder/index helper and one export menu helper.
- **Docs** describe the current pipeline (`docs/development-notes.md`).

## 1.0.4

- **Moving parts on more cars**, found by scanning all 200 cars' blueprints:
  - **Rear doors and rear windows** have proper slider names (Audi S5 Sportback, Charger SRT8, Crown Victoria, Explorer);
  - the **Porsche Taycan's rear wing** moves (its stage logic comes through a spoiler prefab);
  - the **Integra Type-R's radio antenna** gets an **Antenna** slider (the game's tracks call it "arial").
- **Pop-up headlights work on all 12 cars that have them:** BMW M1, Camaro SS '67, Charger R/T '69, F40, Testarossa, NSX-R, Countach 25th, Diablo SV, MX-5 '96, RX-7 Spirit R, Cougar '67, 180SX. (On the '67 Camaro, '69 Charger and Cougar these are hidden headlight covers.)
- **Tests:** the Taycan, Integra Type-R and Audi S5 Sportback are in the default suite.
- **Headless exporter:** a `scan <out.json>` mode reads every vehicle's animation graph (about a minute for 200 cars).

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
