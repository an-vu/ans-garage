# Vehicle assembly

`src/Assembly.cs` extends discovery through actual vehicle/item/blueprint relationships. `blender/unbound_assembly.py` adds an assembly to the existing FBX importer.

RaceVehicleBlueprint links rim customization components to RaceWheelComponentData through LinkConnections. MeshCustomizationTagWithFacing supplies front/rear and left/right flags. Four independent authored transforms are retained; symmetry is not assumed. Blender placement uses the imported FBX root conversion matrix.

Stock item selection matches RaceVehicleReference.VehicleBundleHash. CustomizableMeshInfo GUIDs resolve through BlueprintBundle pointers to customizable blueprints and mesh proxies. This recovered five previously absent shared brake/caliper/tire meshes for the Murciélago.

Default tire item names alone are insufficient: the tested default item refers to the Generic Regular 02 Small tire blueprint despite its own different name. The pointer chain is recorded.

Each wheel has Rest, Suspension, Steering and Rotation controls. Object copies share source mesh datablocks, preserve transforms/groups, and remap armature targets. Original imported objects remain in an excluded source collection. Body transforms are not reset or applied.

Collections use item types, location, source variant names and preset membership. Related submeshes stay under their actual mesh instance; license-plate submeshes stay with the rear bumper. Exact duplicate mesh/placement instances may be hidden; no geometry is deleted. Overlap alone does not prove two different meshes are duplicates.

The first source permutation is an explicit preview policy. Source template SubItems allow stock/body-kit selection. Full engine restrictions and offsets are retained raw, not evaluated. Arbitrary compatible customization combinations are therefore not certified.

## Experimental interpretation

- `Rotate` is interpreted as 180 degrees around source Y. This produced outward-facing rim badges in the Murciélago, but the engine implementation was not recovered.
- Tire width/diameter fitting uses TireConfig dimensions and TireMeshInfo reference dimensions. It changes object scale, not vertices. Inner-bead fit and engine tire deformation remain unknown.
- Rim/brake source dimensions are retained. Runtime rim resizing, caliper offsets, loaded suspension and animation simulation are not reconstructed.

Murciélago checks verify four exact rest centers, four tires, original body alignment, data preservation, variant switching and presets. Workbench preview renders were inspected for overall placement; they do not validate game-equivalent materials or suspension.

A second discovery-only run on the BMW M3 E46 found four wheels, 99 items and 363 mesh uses with no assembly issues. No BMW FBX export, Blender assembly or appearance validation was performed. Production algorithms contain no Murciélago-specific offsets or asset IDs.
