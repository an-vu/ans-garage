# Changelog

Older Frosty plugin history: `frosty/AnsGarage/CHANGELOG.md`.

## 1.1.9

- **BMW M1: pop-up headlights.** Its two light sequences both keep the lights turned 2.5° (they undo the tilt of the lights' hinge), so neither started at the modelled pose, and the rule "the sequence that starts at rest opens the lights" found no opening one. The opening sequence is now the one the light switch's OnTrue starts (CompareBoolEntityData; the other is started by OnFalse); it also plays the game's PopUpHeadlights_Up sound. Checked on all 13 cars with such pairs (12 with pop-up headlights, and the Integra's antenna): the same sequence as before on the other 12.
- **Dirt, dust and wet stay on a computer without the add-on.** The sliders were settings of the add-on, so a car saved dirty opened clean wherever An's Garage for Blender wasn't installed (the drivers lost what they read). They are now custom properties of the scene: the car keeps its condition, and the sliders work from Scene Properties > Custom Properties. The sidebar is unchanged.
- Reimport cars to get both.
- **Tests:** the BMW M1 is the eleventh test car; with the add-on turned off, the scene's sliders still drive the car.

## 1.1.8

- **Window, headlight and taillight tint,** as in the game's garage: colour controls under Paint and livery, with **Stock tints**. The car's tint keys drive the shaders' `Ext_Glass_Color` (windows), `Ext_Headlight_Color` and `Ext_Taillight_Tint` (lenses), matched by the game's parameter keys; stock values are the car's own (window tint from its vehicle item, light tints from its customization defaults). Light tints show only where the car's lens shaders take them (not on the Evija, Integra or Chiron).
- **Ford GT: the wing rests tucked in,** as in the game. Its wing is modelled raised and its sequences start 16-23 cm lower; the rig took the modelled pose for slider 0, so the wing sat up at rest and flew higher when moved. Parts are now attached in their modelled pose, so slider 0 is the game's rest pose.
- **Moving parts on five more cars:** pop-up headlights on the '67 Camaro, '67 Cougar and '69 Charger, the Evija's rear wing, the Pagani Huayra BC's flaps (**Air vents**, **Airbrake**). Their sequences pass through a blend with a fixed full weight, which wasn't read before.
  - **Evija:** the wing's top blade sequence starts at the spoiler's own place in the car, so it carried that position twice (the blade floated 2 m off the car). It is taken out: the blade sits flush at rest and rises on its posts.
  - **Pagani:** the wing and airbrake sequences meet in a hub that passes on whichever changed last. In Blender the flaps take the airbrake's pose once its slider leaves 0, else the wing's.
- **All cars checked:** the moving parts were read from all 187 cars with assembly data. Only the Ford GT rests away from its modelled pose; none rest off the car.
- **Cars with a Cop Edition get their assembly data** (16 cars failed: the car and its Cop Edition share one bundle). See the Frosty changelog.
- Reimport cars to get the tints and moving parts.
- **Tests:** the window tint is live on every test car, light tints where the lenses take them; parts held away from their modelled pose at rest are moved there and stay on the car (under 30 cm).

## 1.1.7

- **Stance, as in the game's garage:** a **Stance** section per car with **Ride height**, **Front camber** and **Rear camber** (0-10, the game's slider steps) and **Stock**.
  - The values are the game's: each car's stock visual-suspension item (its ride-height travel: 7 mm on the Murciélago and Ford GT up to 75 mm on the BMW M3 E46), and the physics changes each slider makes, exported by An's Garage for Frosty into `assembly.json`.
  - Ride height is stock at 10 (the top): lowering moves the body down by the car's travel and, as in the game's data, adds camber (front 0.125, rear 0.1) and pushes the wheels out (front 17.5 mm, rear 12.5 mm). The camber sliders add up to 0.2 and 20 mm.
  - In Blender the wheels rise into the body (the car stays where it is) and lean in at the top, through drivers on each wheel's Suspension empty.
  - Unchecked, to confirm in a game session: camber read as radians (0.2 = 11.5°), its top/bottom pair (equal in every car checked) taken as one angle, and tops in. Caster is not shown (no visible change at rest).
- Re-export cars (or **Add assembly to an existing export**) to get their stance.
- **Tests:** every vehicle test checks the stance: stock leaves the wheels in place, the lowest ride height lifts them by the car's travel and moves them out, front camber 10 leans the fronts in by 0.2 rad.


- **Moving parts listed front to back,** like the body parts (they were grouped by kind: aero, doors, windows, hood and boot). Each slider is placed by where its geometry sits on the car (item meshes, and the body vertices its bone moves), and a left/right pair stays together, left first. Murciélago: Hood, Left door, Right door, Left window, Right window, Air vents, Boot. The order is set when the moving parts are built, so reimport a car to get it.
- **Ford GT: rear wing and airbrake move,** as in the game. Its wing and flap blend between two sequences (wing up, and the airbrake pose) by clamp(3 × airbrake), which the moving parts didn't support ("Transform blend with a non-identity In1"). Now: **Rear wing** raises the wing on its struts, **Airbrake** tilts it up; in Blender a Copy Transforms constraint does the blend, driven by the same clamp. The wing and airbrake are told apart by the animation output that drives them (the same outputs as the P1's and Chiron's). The blend's exact interpolation in the game is unchecked (Blender's: position and rotation interpolated).
- **Tests:** every vehicle test checks the order; the Ford GT is the tenth test car.

## 1.1.5

- **Sidebar text uses the full width:** lines wrapped well before the edge (e.g. a two-word second line with plenty of room left). The wrap now uses the width Blender really gives a label (measured: the panel's width less 40 px at any sub-panel level), plus room only for an icon, a box or the ✕ beside a note.

## 1.1.4

- **Exports into a folder with accented letters work** (e.g. "Lamborghini Murciélago LP 670-4 SV (2009)", the car's own name). Frosty's FBX writer can't open such paths and wrote no meshes at all, so Blender had nothing to import. Each FBX is now written to a plain temporary folder first and moved into place. Re-export cars whose export failed.
- **Shader textures are a shared part.** The textures every car's shaders read (240 MB: swatches, grime, flakes…) were written next to each car folder, so cars exported to different places each carried a copy, and a car folder moved on its own lost them.
  - They now come from **Export shared parts...** (new first checkbox, **Shader textures**) into the shared parts folder (`AnsGarage_ShaderTextures`), where Blender finds them with the other shared parts; the preferences list them too.
  - **Export vehicle** no longer writes them, and **Find moved shared textures…** is gone.
  - Export shared parts once with Shader textures ticked and set that folder in Blender. A car without them imports, but its materials that need them aren't built, and its notes say why.
- The Frosty menu item is now just **Export shared parts...**.

## 1.1.3

- **Sidebar dropdowns fixed:** body parts and presets showed only "-", and Finish, Material, Color shift and Gloss opened a second search window after picking. Every dropdown is now a Blender menu that knows which car (and part) its row is for and runs the choice directly.
- **One report per car:** "An's Garage report: <car>" in the Text Editor replaces the import, material slot, surface and assembly reports. It is written to be read: Import, Materials (slots built, the rest grouped by reason, after every build pass), Assembly (issues, source parts no option uses), Moving parts, License plate, and how the car was built. The car's notes point to it.
- The notes on how the car was built are up to date (tire, rim and brake sizes follow the game's shaders, checked against the frame capture).
- "Set folder…" fits the Tires, Rims and Plate rows.
- **Tests:** the part, preset and paint menus are drawn and run on every test car; the import leaves exactly one report text.

## 1.1.2

Re-export the shared parts in Frosty (**Tools > An's Garage > Export shared parts...**) for the
plate frames and the new plates, and set that folder once in Blender.

### Fixes
- **Parts stay where they belong when you switch options.** On the Aventador S, spoiler set A sat under the middle of the car and its air vents were 1.8 m off.
  - Cause: Blender only updates the position of parts it shows. When the import built the moving parts, it read hidden options at their old position (the car's origin) and pinned them there.
  - Positions are now worked out from each part's own transforms. The vehicle test shows every part option of every test car one by one and checks that each part sits where the assembly placed it.
- **License plate text in each plate's own colour,** as in the game: the plate shader reads the text colour from the plate texture's top-left texel (frame capture: Lakeshore = dark red #7B0429). It was lime green on every plate.
  - Cause, in the shader compiler: its constant prover gave unknown textures the same stand-in value on every check, so a texture read at fixed coordinates looked constant and was folded away. Stand-in textures now differ per check; the plate shader and two others keep their fixed-coordinate reads.
- **The plate the game shows, not the model's placeholder.** A new import gets what the game puts on the car as sold: the plate, frame and text of its vehicle item (`RaceVehicleItemData` sub-items).
  - On all 10 cars checked: **Lakeshore**, **no frame** (no frame item, so the default no-frame textures) and the text **NFS**.
  - Before, the plate showed the model's own textures: a California-style plate, light grey in its top-left corner (so near-white text by the game's rule), with a Speedhunters frame. The game replaces both.
  - **Stock** in the plate and frame pickers means the game's plate and frame. Without the shared parts folder the placeholder stays, and the car's notes say so.
- The sidebar stopped drawing below the dirt controls with dirt/dust/wet on or with two cars in the scene, so parts, paint, wheels and plates couldn't be changed (three places).

### License plates and wheels
- **Plate frames** (picker under License plate): None, Simple; Illest (Fatlace), Mean Streets, Shirts Tucked In, German Automotive; Most Wanted, Underground. They override the plate shader's frame textures (`Ext_T_Frame_Diffuse`, `Ext_T_Frame_Normalmap`), as the game's frame items do.
- **Two more plates:** Simple (the plain plate) and Palifornia (the Palace Edition plate). The vehicle-exclusive plates (BMW i8, Corvette Grand Sport, Polestar 1) are Palm City, already in the library.
- **Plate frame for new imports:** an add-on preference (Stock, Simple or None).
- **Front and rear rims separately,** as the game's Front Rims / Rear Rims; the brakes follow each axle.

### Shared parts
- **One folder for everything every car can use.** Frosty's **Export shared parts...** exports tires, rims, plates and frames, all or one at a time, into one folder (a subfolder per library).
- In Blender, set it once: the add-on preferences' **Shared parts folder**, or **Set shared parts folder…** in a car's Wheels or License plate section. The add-on finds each library by its index file; the preferences show what was found (Tires, Rims, License plates, Plate frames, with counts).
- This replaces the three **Locate … library** buttons and the per-library folder settings.

### Sidebar
- **Blender's own sub-panels:** each car is a sub-panel named after it (the in-game name that fits: long, medium or short). Inside, like the game's garage: **Preset**, **Body parts** (front to back), **Paint and livery**, **Wheels**, **License plate**, **Moving parts**, **Materials**, **Dirt, dust and wet**. Open or closed is kept per car and saved with the file.
- Every choice is a "Name | value" row like Blender's own properties: dropdowns for the preset, each body part, factory rims, tires, finish, material, colour shift and gloss; search fields for livery, rims, plate and frame.
- **Import car…** at the top, under a short welcome line.
- **Moving parts:** **Open all** next to **Close all**.
- **Materials** (per car): the header says how many visible surfaces are built; opened, it shows the selected part's material and whether it's built. It reads the car itself, not a report text (one fresh Diablo import showed no materials box; not reproduced).
- **Dirt, dust and wet:** on and off with the checkbox in its header; it applies to every car in the scene.
- **Notes:** everything the add-on has to tell about a car sits together at the end of its section, each with an **✕** to hide it (it comes back if what it says changes): surfaces not built, assembly issues and source parts no option uses, no shared parts folder, no liveries exported. This replaces the "Limits" line and the selected-object box.
- **Tools** (folded, at the bottom): Build missing materials, Find moved car folder…, Find moved shared textures…, Refresh dirt on unhidden parts; each explained in its hover text.
- Wrapped text is measured with Blender's font at its real interface scale, so it uses the full width without running past the edge.
- Needs Blender 4.1 or later (sub-panels).

### Dirt, dust and wet
- **Faster, without freezing Blender:** turning them on or off rebuilds only the visible parts (Diablo: 116 slots instead of 923, 28 s -> 17 s), in slices with a progress bar like the import. A hidden part option catches up when it is shown (part, preset and tire switches); **Refresh dirt on unhidden parts** for parts shown by hand.

### Tests
- Every part option of every test car is checked for placement; the part and preset dropdowns are checked on every car.
- The plate test checks the game's plate, frame and text at import and finds the shared libraries in one folder.
- The sidebar is drawn with every section open, with the dirt controls on and with two cars; the rim test covers front-only and rear-only rims.

## 1.1.1

- **Caliper badges take dirt and dust,** as in the game. The badge's pixel program reads one value its vertex program computes; it is the surface normal's component along the axle (the spin doesn't change it), verified numerically against a vertex program the compiler already reads (identical to 2e-16), and now recorded in the compiler (`VERIFIED_OUTPUTS`). On the Murciélago 1 of 589 surfaces stays clean under dirt: the badge of a spare caliper that isn't on a wheel (hidden).
- 1.1.0's notes corrected: the surfaces that stayed clean were the caliper badges (brand logos), not calipers.

## 1.1.0

Built from a frame capture of the game itself (NVIDIA Nsight Graphics, the Lotus Evija in the garage): the values the
game's shaders actually receive, where the shader data alone left them open.

- **Every surface builds on all nine test cars.** The last light-glass pieces (McLaren P1 3, Diablo SV 3, BMW M3 E46 1, Integra 2, Taycan 2) and the 22 window slots that couldn't take a livery now build:
  - the game draws its light lenses with the **full** program of each full/reduced pair (state bit 9 clear). The shader compiler records the bit; the add-on picks the full one;
  - the glass shaders' engine constant (`cb0[1].x`, metal reflection strength) is **1.0** in the game.
- **Dirt and dust on lenses and calipers:** the 36 Murciélago lenses that stayed clean now take dirt and dust colour (full program). Calipers and discs get the game's per-wheel flags (front/rear, left/right), so the calipers that stayed clean take dirt now. Still clean (reason recorded): the 5 caliper badges (the brand logos on the calipers; one input their vertex program computes isn't reproduced yet). On the Murciélago 5 of 589 surfaces stay clean, down from 47; 77 others have no dirt, dust or wet in their game shaders (lamp bulbs and reflectors, small detail parts, brake discs, tiled interior).
- **Brake size:** discs and calipers are scaled like the game does it: rim diameter × the rim's BrakeDiscRatio ÷ 0.4 m, about the wheel centre (a **Brake size** modifier). Before, they kept their modelled size. A library rim brings its own ratio; Stock puts the car's back.
- **Paint finishes with the game's names:** the 13 materials of the game's paint menu (Non-Metallic, Chrome, Metallic, Fine Metalflake, Brushed Metal, Black Carbon, Carbon, Chequered Carbon, Broad Carbon, Forged Carbon, Damascus, Large Metalflake, Honey-Comb Carbon), with the game's exact values.
  - New **Color shift** (Single, Near, Opposite, Spectrum, Iridescent) and the game's Gloss / Satin / Matte values.
  - **Finish** now lists the game's 13 preset finishes (Gloss, Metallic, Chrome, Satin Metallic, Carbon, Matte Carbon, Forged Carbon, Chameleon Flake, Color Shift, Iridescent, Color Shift Carbon, Damascus, Honey-Comb Carbon); **Material** and **Color shift** set each part as in the game's PRO tab.
- **Tire width as the game does it:** a tire widens by the rim's width minus the tire mesh's width, one sidewall only (the tire shader branches on a per-wheel flag; rims use the two-sided formula). 1.0.9 used half the section-width difference on each side. Tread, bead, sidewall size and factory rims were already exact.
- **Frosty:** the rim library index records each rim's BrakeDiscRatio (re-export the rim library; older ones keep the brakes' size on a library rim).
- **Tests:** the Lotus Evija joins the vehicle tests; checks that the Wheel fit and brake size reproduce the captured values; every vehicle test checks the brake size; rim test checks the brakes follow the rim; paint test checks the preset finishes decode like the game's menu.

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
