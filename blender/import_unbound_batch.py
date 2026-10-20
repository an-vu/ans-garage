"""Install as a legacy Blender add-on, or run from the Text Editor.

Imports the manifest's exported FBX files without recentering or applying transforms.
Variants are reference collections, not reconstructed material appearances.
"""
bl_info = {"name": "Unbound Batch Manifest", "author": "An Vu",
           "version": (0, 1, 0), "blender": (3, 6, 0), "category": "Import-Export"}

import json
from pathlib import Path


def exported_records(manifest):
    if manifest.get("Schema") != 1:
        raise ValueError("Unsupported manifest schema")
    seen = set()
    for mesh in manifest.get("Meshes", []):
        if mesh.get("Status") != "exported":
            continue
        if not mesh.get("Id") or mesh["Id"] in seen:
            raise ValueError("Missing or duplicate mesh identity")
        seen.add(mesh["Id"])
        yield mesh


def safe_fbx(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or path.suffix.lower() != ".fbx":
        raise ValueError("FBX path must remain inside the export folder")
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def import_manifest(filepath):
    import bpy
    path = Path(filepath).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8-sig"))
    records = list(exported_records(manifest))
    # Validate all paths before changing the scene.
    files = {m["Id"]: safe_fbx(path.parent, m["Fbx"]) for m in records}

    def collection(name, parent):
        result = bpy.data.collections.new(name)
        parent.children.link(result)
        return result

    root = collection("Unbound | " + manifest.get("Scope", "batch"), bpy.context.scene.collection)
    root["manifest"] = str(path)
    root["transform_policy"] = manifest.get("TransformPolicy", "")
    parts = collection("Parts", root)
    variants = collection("Variant references (no material reconstruction)", root)
    variants.hide_viewport = True
    variants.hide_render = True
    variant_collections = {}
    failures = []
    count = 0
    for mesh in records:
        before = set(bpy.data.objects)
        try:
            status = bpy.ops.import_scene.fbx(
                filepath=str(files[mesh["Id"]]), global_scale=1.0,
                use_manual_orientation=False, bake_space_transform=False,
                use_anim=False, automatic_bone_orientation=False,
                ignore_leaf_bones=False, use_prepost_rot=True)
            if "FINISHED" not in status:
                raise RuntimeError("Blender FBX importer did not finish")
            added = set(bpy.data.objects) - before
            if not added:
                raise RuntimeError("FBX produced no objects")
            part = collection(mesh["Asset"].split("/")[-1] + " | " + mesh["Id"][:12], parts)
            part["asset"] = mesh["Asset"]
            part["file_guid"] = mesh["FileGuid"]
            part["class_guid"] = mesh["ClassGuid"]
            part["raw_composite_transforms_json"] = json.dumps(mesh.get("CompositeTransforms", []))
            for obj in added:
                # Collection linking does not change parent, matrix_basis or matrix_world.
                part.objects.link(obj)
                for old in list(obj.users_collection):
                    if old != part:
                        old.objects.unlink(obj)
                obj["unbound_mesh_id"] = mesh["Id"]
            for variant in mesh.get("Variants", []):
                key = (variant["DatabaseGuid"], variant["Hash"])
                if key not in variant_collections:
                    vc = collection(variant["Hash"] + " | " + variant["DatabaseGuid"][:8], variants)
                    vc["database"] = variant["Database"]
                    vc["variation_hash"] = variant["Hash"]
                    variant_collections[key] = vc
                vc = variant_collections[key]
                if part.name not in vc.children:
                    vc.children.link(part)
            part["variant_records_json"] = json.dumps(mesh.get("Variants", []))
            count += 1
        except Exception as exc:
            for obj in set(bpy.data.objects) - before:
                bpy.data.objects.remove(obj, do_unlink=True)
            failures.append(mesh["Asset"] + ": " + str(exc))
    report = bpy.data.texts.new("Unbound import report")
    report.write("Imported %d/%d meshes\n" % (count, len(records)) + "\n".join(failures))
    return count, failures


def register():
    import bpy
    from bpy_extras.io_utils import ImportHelper
    from bpy.props import StringProperty

    class IMPORT_SCENE_OT_unbound_batch(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.unbound_batch"
        bl_label = "Unbound batch manifest"
        bl_options = {"REGISTER", "UNDO"}
        filename_ext = ".json"
        filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

        def execute(self, context):
            try:
                count, failures = import_manifest(self.filepath)
                self.report({"WARNING" if failures else "INFO"},
                            "%d imported; %d failures. See Unbound import report." % (count, len(failures)))
                return {"FINISHED"}
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

    def menu(self, context):
        self.layout.operator(IMPORT_SCENE_OT_unbound_batch.bl_idname, text="Unbound batch manifest (.json)")

    global _registered_class, _menu
    _registered_class, _menu = IMPORT_SCENE_OT_unbound_batch, menu
    bpy.utils.register_class(_registered_class)
    bpy.types.TOPBAR_MT_file_import.append(_menu)


def unregister():
    import bpy
    bpy.types.TOPBAR_MT_file_import.remove(_menu)
    bpy.utils.unregister_class(_registered_class)


if __name__ == "__main__":
    register()
