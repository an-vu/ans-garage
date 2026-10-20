# Material reconstruction: evidence and limits

Version 0.4.0 adds `blender/unbound_materials.py` and extends the existing importer. Original raw extraction remains in `src/Materials.cs`.

## Slot and face assignment

Frosty's native FBX exporter disables FBX materials. It emits each renderable LOD0 section as separate geometry. Its `MaterialId` refers to the original `mesh.Materials` array. Every surviving face in that section therefore receives that slot index, without inventing face-level classification.

The importer uses Blender's bundled FBX parser, verifies section order, original node names and LOD parent, then matches objects by a digest of local vertex coordinates and face vertex-index sequences. Repeated-index degenerate polygons are excluded from the matching digest and logged exactly. Blender `.001` suffixes are not primary identity. Ambiguous matches fail explicitly.

Each geometry datablock receives the original slot array. Object-linked materials permit different variations on shared geometry. Existing non-Unbound user assignments are refused. `SubMaterialIndex` vertex attributes are preserved, but not interpreted as Blender face indices: their shader-internal meaning is unresolved.

Root variation rows use hash `00000000`. Multiple databases are accepted only when resolved shader and parameters agree. Conflicting rows retain the base material and log a diagnostic. Explicit non-root selection uses database GUID + row + exact base material object identity.

Preset expansion, replacement-shader parameter clearing and case-insensitive overwrite order follow Frosty's `FrostyPlugin/Viewport/RenderMesh.cs`, `MeshMaterialCollection`. The graph and all original rows remain in `materials.json`.

## UV provenance

Frosty's `Plugins/MeshSetPlugin/Fbx/FBXExporter.cs` walks vertex streams, then declaration elements. It assigns `UVChannelN` in encounter order, not by `TexCoordN` suffix. Radiosity and auxiliary two-component attributes consume UV ordinals too. The `DisplacementMapTexCoord` vertex usage is ignored by that exporter.

New `Sections[].FbxUvBindings` records mapping and conversion. Legacy manifests reconstruct it from captured vertex declarations. Regular UVs retain Frosty's `(U, 1-V)` conversion; auxiliary layers follow their native conversion. No UV data is rewritten.

Texture bindings separately record `SourceUvUsage`, `BlenderLayer`, evidence and status. `MeshMaterial.DisplacementMapTexCoord` can provide an explicit displacement association. The tested Murciélago shader texture parameters provide no such selectors. **All current sampled texture associations remain unknown.** A single available UV layer, familiar texture name or numeric UV-scale parameter is insufficient evidence to choose a channel.

## Packed textures

These are exact source `TextureShaderParameter.ParameterName` values in the tire shader:

| Parameter | Meaning stated by the name | Still unknown |
|---|---|---|
| `RGB_Color_A_Smoothness` | RGB color; alpha smoothness | UV/transform, color transfer if unflagged, blending, game's roughness conversion |
| `RG_Normal_A_AO` | RG normal components; alpha AO | Blue channel, Z reconstruction, sign convention, UV, shader combination |
| `RG_NormalBlur_A_AOBlur` | RG blurred normal components; alpha blurred AO | Blue channel, decoding, motion/blur interpolation, UV |
| `T_Material` and unnamed packing | Unknown | All channel meanings |

Original DDS payload and raw bytes remain unchanged. Unknown channels stay null. Images use `CHANNEL_PACKED` alpha for inspection. Source sRGB is used only where flags/format identify it. Unknown-transfer images are displayed as raw Non-Color data; this is an inspection setting, not a claim that source color space is linear.

## Principled support

Seven reusable node groups expose Principled inputs for Car Paint, Glass, Rubber, Metal, Plastic, Carbon Fiber and Lights. No material-family constants are invented. Exact shader identities identify some families, including tires; a general opaque shader does not reliably distinguish plastic, carbon or metal.

Each material retains source identity, shader/preset/override state, raw typed parameters, texture nodes and diagnostics. Packed tire channel separation is labeled from explicit parameter names. There is no default UV0 connection or guessed roughness/metalness swizzle.

**No delivered Murciélago material has a connected surface output.** These groups are reusable infrastructure and source inspection, not completed BSDF reconstruction. Scalar/color nodes stay raw and disconnected when composition/color interpretation is unverified.

## Compiled shader investigation

The graph contains 26 `ShaderGraph` and 12 preset nodes. ShaderGraph EBX records contain names/IDs and `MaxSubMaterialCount`, not expressions or sampling instructions.

A live inventory found nine `IShaderDatabase` resources and no matching `ShaderBlockDepot` resources. The vehicle shader database is 3,334,634 bytes; its first-block field at offset 16 is 2. The inspected `FrostyCmd/ShaderDbDump.cs` processes only render-path value 3 (its legacy DX11 enum). That utility was not adapted or treated as a valid Unbound decoder. Inventory/header evidence accompanies the validation artifacts.

Frosty's viewport shaders and generic parameter fallbacks are editor previews; they do not prove the retail game's channel or UV semantics.

## Next steps

1. Validate an Unbound shader-database/cache reader and associate surface-shader IDs with compiled permutations.
2. Recover vertex-input/sampling expressions and texture swizzles for the tire shader first.
3. Verify the decoded channels, then bind explicit UV Map nodes and supported Principled inputs.
4. Validate paint/glass/light runtime inputs and composition before enabling their outputs.
5. Extend shader rules to more vehicles, keyed to shader identity/layout rather than vehicle names.
