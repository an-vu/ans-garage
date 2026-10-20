# API evidence

The plugin calls upstream APIs; it does not embed upstream source or binaries.

- [HarGabt release v1.0.7_26.10.12](https://github.com/HarGabt/FrostyToolsuite/releases/tag/v1.0.7_26.10.12) — release assemblies used for compilation and tests.
- [FBXExporter.cs at release commit](https://github.com/HarGabt/FrostyToolsuite/blob/5fdef53c0e17cd8ed04a56a31bbd4f108b2854ba/Plugins/MeshSetPlugin/Fbx/FBXExporter.cs) — direct API signature, first-LOD behavior, composite and skeleton transforms, native binary export.
- [MeshVariationDb.cs at release commit](https://github.com/HarGabt/FrostyToolsuite/blob/5fdef53c0e17cd8ed04a56a31bbd4f108b2854ba/FrostyPlugin/Viewport/MeshVariationDb.cs) — Entries/Mesh/Materials fields and Unbound cache early return.
- [EbxReader.cs at release commit](https://github.com/HarGabt/FrostyToolsuite/blob/5fdef53c0e17cd8ed04a56a31bbd4f108b2854ba/FrostySdk/IO/EbxReader.cs) — GetObject GUID resolution.
- [MeshAssetDefinition.cs at release commit](https://github.com/HarGabt/FrostyToolsuite/blob/5fdef53c0e17cd8ed04a56a31bbd4f108b2854ba/Plugins/MeshSetPlugin/MeshAssetDefinition.cs) — mesh resource lookup and standard export invocation.

Inspected branch checkout: `d73a3c6799025aa183da447e5defcf2a38f0786c` (1.0.7). Release tag commit: `5fdef53c0e17cd8ed04a56a31bbd4f108b2854ba`. Critical exporter/reader/variation-cache files were also fetched from the release commit and compared.


Phase 2 additionally inspected these local upstream source files at the branch commit above, and checked API availability/data against the actual installed release:

- `FrostyPlugin/Viewport/RenderMesh.cs`: MeshMaterialCollection and shader/preset parameter layering.
- `Plugins/TexturePlugin/TextureExporter.cs`: DDS wrapper and native format conversion.
- `FrostySdk/Resources/Texture.cs`: dimensions, mip metadata, flags and source data.
- Generated `Profiles/NFSUnboundSDK.dll`: actual Unbound Material/Shader/Texture/variation row field definitions.

The generated SDK and game data were read locally; they are not redistributed.
