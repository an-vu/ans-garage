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
