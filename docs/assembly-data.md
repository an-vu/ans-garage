# Vehicle assembly

`frosty/AnsGarage/src/Assembly.cs` writes `assembly.json` from the actual vehicle/item/blueprint relationships. `blender/ans_garage/unbound_assembly.py` assembles the imported FBX parts from it.

RaceVehicleBlueprint links rim customization components to RaceWheelComponentData through LinkConnections. MeshCustomizationTagWithFacing supplies front/rear and left/right flags. Four independent authored transforms are retained; symmetry is not assumed. Blender placement uses the imported FBX root conversion matrix.

Stock item selection matches RaceVehicleReference.VehicleBundleHash. CustomizableMeshInfo GUIDs resolve through BlueprintBundle pointers to customizable blueprints and mesh proxies. This recovered five previously absent shared brake/caliper/tire meshes for the Murciélago.

Default tire item names alone are insufficient: the tested default item refers to the Generic Regular 02 Small tire blueprint despite its own different name. The pointer chain is recorded.

Each wheel has Rest, Suspension, Steering and Rotation controls. Object copies share source mesh datablocks, preserve transforms/groups, and remap armature targets. Original imported objects remain in an excluded source collection. Body transforms are not reset or applied.

Collections use item types, location, source variant names and preset membership. Related submeshes stay under their actual mesh instance; license-plate submeshes stay with the rear bumper. Exact duplicate mesh/placement instances may be hidden; no geometry is deleted. Overlap alone does not prove two different meshes are duplicates.

The first source permutation is an explicit preview policy. Source template SubItems allow stock/body-kit selection. Full engine restrictions and offsets are retained raw, not evaluated. Arbitrary compatible customization combinations are therefore not certified.

## Stance

`assembly.json` "Stance" (Frosty `AssemblyRun.Stance`): the stock car item's `ControlArmTuningItemData` sub-item (`items/stanceitems/visualsuspensionsliders_<travel>`) and its tuning items, each `PerformanceModificationTuningItemData` → `TuningConfig` (`GenericTuningConfigData`) → `PerformanceTuning.PerformanceTuningData` (`RaceVehiclePerformanceTuningData`). A slider changes each attribute linearly from `ModificationMin` (slider minimum) to `ModificationMax` (maximum); attributes from several sliders add up.

`blender/ans_garage/unbound_stance.py` drives each wheel's Suspension empty: `ATM_XCarBodyYOffset` (body down = wheels up), `ATM_XCarWheelCamberTop/Bottom<axle>` (camber, tops in, read as radians), `ATM_XCarWheelXOffsetTop/Bottom<axle>` (out along the axle). Caster and `ATM_XCarMultiplier` aren't applied. Unchecked: camber units and sign, and the top/bottom pair (equal in every car checked).

## Moving parts

`blender/ans_garage/unbound_animation.py` reads the vehicle blueprint's animation graph from `assembly.json` (field names are Frosty field-name hashes; the module computes them from the names).

- **Doors, windows, hood, boot:**
  - `NamedAnimationPropertyEntityData` (`sharedvehiclerigpropertyinfo_ldooropen`, ...) `.Value` drives `TransformAnimationEntityData.T`.
  - The entity's six curves (degrees, metres; `CurveType_Basic_Linear` or `CurveType_Zero`) move the part about its `Origin`.
  - `.Transform` reaches the part through `AnimateComponentEntityData` and a link connection.
- **Active aero:**
  - `AnimationComponentData` drives `SequenceEntityData.ExternalTime` (the airbrake through a `MathEntityData`).
  - The sequence's `TransformPartPropertyTrackData` keys live in resources. The exporter writes them to `assembly.json` as `TrackData`: 6 floats per key (time, value, in-tangent x/y, out-tangent x/y; cubic Hermite).
  - Tracks reach a component's `Transform` (Murciélago vents) or `TransformOffset` (spoiler base and flap) through:
    - `TransformBlendEntityData.In2`, weighted by the spoiler component's `AnimationExtent`: stock item 1, aftermarket 0;
    - `TransformMultiplierEntityData` (wing in `In1`, airbrake in `In2`);
    - `RealmTransformCombinerEntityData.ClientTransform`;
    - a `TransformBlendEntityData` fed by two sequences (Ford GT: the wing-up sequence in `In1`, the airbrake sequence in `In2`), blended by its `BlendValue` = `ClampEntityData` of a `MathOpEntityData` Multiply of the airbrake output and a `FloatEntityData` (3). In Blender: Copy Transforms to the first pose, then to the second with that influence.
  - The animation component's two outputs are told apart by what they drive in the cars checked: `0x33ff5416` the wing sequence, `0xac7e87ed` the airbrake.
- **Pop-up headlights** (Diablo SV):
  - two sequences are played by light events (no `ExternalTime`) and feed a `TransformHubEntityData`, which passes on whichever played last;
  - the sequence that starts at rest opens the lights and becomes the slider; the other is its reverse;
  - the tracks reach the `LightsCustomizationComponentData` `TransformOffset` through the same blend and combiner as the wings.
- **Geometry:**
  - body parts follow bone `PART_<i>`, where `i` is the part's index in `RaceVehiclePhysicsComponentData.Parts`;
  - item meshes follow their component (via `BlueprintComponents`), including items on child components (door mirrors on a door).
- **One convention not stated by the data:** the Euler order (yaw Y, then pitch X, then roll Z). Only orders that apply roll last open the P1's dihedral doors upward; the remaining candidates differ by under 5 cm.
- **Not reproduced:** the speed logic that sets the wing's sequence time, `NormalisedRotationAnimationEntityData` (body roll) and `NormalisedTranslationAnimationEntityData` (exhaust shake).

## Experimental interpretation

- `Rotate` is interpreted as 180 degrees around source Y. This produced outward-facing rim badges in the Murciélago, but the engine implementation was not recovered.
- Tire fitting reproduces the tire vertex shader's formula per vertex (Wheel fit modifier, see `development-notes.md`). Its inputs come from TireConfig (diameter, section width), the factory rim item (diameter, width) and the TireMeshInfo reference dimensions, and match a frame capture of the game (Lotus Evija rear). The sidewall size follows the tire item's `SmallToMedRatio` / `MedToLargeRatio`.
- Factory rims keep their source dimensions; library rims are resized with the same formula. Brake discs and calipers are sized like the game's brake shader (rim diameter × `BrakeDiscRatio` / 0.4). Caliper offsets (`BrakeDiscXOffset`), loaded suspension and animation simulation are not reconstructed.

Production algorithms contain no vehicle-specific offsets or asset IDs. The test suite (`tests/run_all.py`) assembles ten cars and checks placement (every part option, shown one by one), part switching, presets and moving parts on each.
