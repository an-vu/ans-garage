# Material API findings and manifest

## Findings

Inspected the local HarGabt source and actual release assemblies, plus the generated NFS Unbound SDK and current game data. Reused `AssetManager.GetEbx`, `GetResAs<MeshSet>`, `GetResAs<Texture>` and `TexturePlugin.TextureExporter`.

`MeshAsset.Materials` holds material pointers. LOD0 `MeshSetSection.MaterialId` selects the original material slot. Renderable sections become FBX geometry children; the exporter disables FBX material creation. UV attributes remain in the existing native export.

Frosty's normal variation cache loader returns early for Unbound. This plugin reads the database entries directly. Actual Unbound row materials contain `Material`, `MaterialVariation`, `SurfaceShaderGuid` and `SurfaceShaderId`; shader parameters reside in the referenced material/variation objects. Each stored database row is rechecked against the mesh object identity and variation hash before use.

`SurfaceShaderInstanceDataStruct` carries Shader, SurfaceShaderName, TextureParameters, VectorParameters, BoolParameters, ConditionalParameters and VectorArrayParameters. `SurfaceShaderPreset.ShaderPreset` forms another layer. Frosty's render code recursively loads presets, applies named parameters case-insensitively and treats shader replacement differently from inheritance. This release preserves these source layers separately instead of claiming an evaluated final material.

The generated `TextureShaderParameter` has ParameterName and Value, with no per-binding UV index. MeshMaterial has additional fields such as DisplacementMapTexCoord; these are retained verbatim. The inspected ShaderGraph EBX exposes basic identifiers and metadata, not a complete readable shader implementation. ShaderBlockDepot/compiled shader behavior and engine-injected global textures are not decoded.

The native FBX exporter emits UVChannel layers in encounter order and flips V. Raw vertex usages/formats/offsets are recorded, including special non-TexCoord attributes. Do not infer that a named shader parameter necessarily selects UVChannel0.

## Schema 1

All file paths in `materials.json` are relative to the directory holding the original `manifest.json`.

| Field | Meaning |
| --- | --- |
| Meshes[].MeshId / Fbx / Asset / FileGuid / ClassGuid | Join to original mesh manifest, FBX and source object |
| Meshes[].Slots[].Index / Source.Node | Original zero-based slot and material node identity |
| Meshes[].Sections[] | LOD0 section index/name, MaterialSlot, renderable flag, primitive count, vertex/UV declarations and native FBX matching hints |
| Meshes[].Variants[] | Database identity, row, variation hash, raw row and resolved assignments |
| Variants[].Assignments[].Slots | Slots matched by exact material object identity, never by row position |
| Variants[].Assignments[].Override | Pointer to MeshMaterialVariation node; base data remains separate |
| Nodes[].Id / Type / Asset / Raw | Deduplicated source object graph, including material/shader/preset/texture nodes |
| Textures[].ResourceId / Aliases | Deduplicated texture resource and every encountered source identity |
| Textures[].Path / RawData | DDS and original source texture payload |
| Textures[].Format / Flags / ColorSpace | Original format/flags; sRGB only when explicitly signaled, otherwise unspecified |
| Textures[].Sha256 / RawSha256 / Validation | Output/source checksums and validation performed |
| Issues / materials.log | Unresolved references, unsupported data and capture errors |

Reference values include Kind, FileGuid, ClassGuid and Node when resolved. Internal references use their owning file plus object identity. Nodes are registered before traversal, so cycles/shared references do not duplicate the graph. Enums retain both name and numeric value; resource IDs are hex strings to avoid loss of unsigned 64-bit precision; CString/FileRef values retain type and Value.

Property read errors and collection/depth/node truncation are explicit. Limits: 20,000 nodes, depth 48, 100,000 collection items. This is reflected public source data, not a lossless EBX serialization.

For a texture binding, follow a slot's Source.Node to Nodes[].Raw.Shader.TextureParameters, then Value.Node to the TextureAsset node and its TextureResource to Textures[].ResourceId. Follow shader/preset pointers and variation layers as appropriate. Some parameters intentionally contain null pointers.

## Unknowns stay unknown

`Role`, `UVChannel`, semantic classifications and packed-channel meanings remain null/unspecified unless raw fields explicitly describe them. Names such as T_Diffuse, T_Normalmap, T_Emissive, T_Material and T_Damagemask are preserved, but no generic ORM packing or roughness/metallic/opacity conversion is assumed. Normal components and alpha channels are not modified. Non-sRGB format does not by itself establish a texture's intended Blender color-space setting.

Supported extraction is not equivalent to supported shader reconstruction: no game shader is reconstructed in this release. Full original source names remain in Aliases even when Windows filename sanitization is needed.

## Next steps

1. Validate packed-channel meanings and UV selection for specific shader families using compiled resources or controlled Frosty comparisons.
2. Design a Blender section-to-slot import hook that survives repeated source names. Do not assign by globally suffixed object names.
3. Add materials only for verified shader families, retaining unknown parameters and reporting approximations.
4. Trace shared wheel/tyre assets outside the current Murciélago export scope before claiming rubber coverage.
