"""Install as a legacy Blender add-on, or run from the Text Editor.

Imports the manifest's exported FBX files without recentering or applying transforms.
Variants are reference collections, not reconstructed material appearances.
"""
bl_info = {"name": "Unbound Batch Manifest", "author": "An Vu",
           "version": (0, 4, 0), "blender": (4, 0, 0), "category": "Import-Export"}

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


def assembly_module():
    import importlib.util
    module_path = Path(__file__).with_name("unbound_assembly.py")
    spec = importlib.util.spec_from_file_location("unbound_assembly", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def materials_module():
    import importlib.util
    module_path = Path(__file__).with_name("unbound_materials.py")
    spec = importlib.util.spec_from_file_location("unbound_materials", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def import_manifest(filepath, assemble=True, materials=True):
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
    imported_objects = []
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
            imported_objects.extend(added)
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
    if materials and path.with_name("materials.json").is_file():
        try:
            material_report = materials_module().reconstruct(path, imported_objects)
            failures.extend("Materials: " + x["Issue"] for x in material_report["Issues"]
                            if x.get("Severity") == "assignment_failed")
        except Exception as exc:
            failures.append("Materials: " + str(exc))
            report.write("\nMaterials: " + str(exc))
    if assemble and path.with_name("assembly.json").is_file() and not failures:
        try:
            assembly_module().assemble_existing(path)
        except Exception as exc:
            failures.append("Assembly: " + str(exc))
            report.write("\nAssembly: " + str(exc))
    return count, failures


def register():
    import bpy
    from bpy_extras.io_utils import ImportHelper
    from bpy.props import StringProperty, IntProperty

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

    class IMPORT_SCENE_OT_unbound_assembly(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.unbound_assembly"
        bl_label = "Assemble existing Unbound meshes"
        bl_options = {"REGISTER", "UNDO"}
        filename_ext = ".json"
        filter_glob: StringProperty(default="manifest.json", options={"HIDDEN"})
        def execute(self, context):
            try:
                assembly_module().assemble_existing(self.filepath)
                self.report({"INFO"}, "Assembly created. See Unbound Vehicle sidebar and assembly report.")
                return {"FINISHED"}
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

    class IMPORT_SCENE_OT_unbound_materials(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.unbound_materials"
        bl_label = "Restore Unbound material slots"
        bl_options = {"REGISTER", "UNDO"}
        filename_ext = ".json"
        filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
        def execute(self, context):
            try:
                result = materials_module().reconstruct(self.filepath)
                failed = sum(x.get("Severity") == "assignment_failed" for x in result["Issues"])
                self.report({"WARNING" if failed else "INFO"},
                            "%d objects assigned; %d failures. See material reconstruction report." % (len(result["Objects"]), failed))
                return {"FINISHED"}
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

    class OBJECT_OT_unbound_variant(bpy.types.Operator):
        bl_idname = "object.unbound_variant"
        bl_label = "Switch Unbound variant"
        bl_options = {"REGISTER", "UNDO"}
        root: StringProperty()
        group: StringProperty()
        option: StringProperty()
        preset: StringProperty()
        def execute(self, context):
            try:
                collection = bpy.data.collections[self.root]
                if self.preset:
                    assembly_module().apply_preset(collection, self.preset)
                else:
                    assembly_module().set_variant(collection, self.group, self.option)
                return {"FINISHED"}
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

    class OBJECT_OT_unbound_material_variant(bpy.types.Operator):
        bl_idname = "object.unbound_material_variant"
        bl_label = "Select source material database row"
        bl_options = {"REGISTER", "UNDO"}
        database_guid: StringProperty()
        row: IntProperty()
        def execute(self, context):
            try:
                obj = context.active_object
                if not obj or not obj.get("unbound_materials_path"):
                    raise ValueError("Select a mesh with restored Unbound material slots")
                materials_module().apply_material_variant(obj["unbound_materials_path"],
                    obj["unbound_mesh_id"], self.database_guid, self.row, context.selected_objects)
                self.report({"INFO"}, "Source material row selected on selected instances. Shader appearance remains unresolved.")
                return {"FINISHED"}
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

    class VIEW3D_PT_unbound_vehicle(bpy.types.Panel):
        bl_label = "Unbound Vehicle"
        bl_idname = "VIEW3D_PT_unbound_vehicle"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "Unbound"
        def draw(self, context):
            for root in context.scene.collection.children:
                if not root.get("unbound_assembly_path"):
                    continue
                box = self.layout.box()
                box.label(text=root.name)
                box.label(text="Authored rest pose")
                for preset in json.loads(root["unbound_presets_json"]):
                    label = "Stock" if preset == "Stock" else preset.rsplit("_template_", 1)[-1].replace("_", " ")
                    op = box.operator("object.unbound_variant", text="Preset: " + label)
                    op.root, op.preset = root.name, preset
                for group in root.children:
                    key = group.get("unbound_choice_group")
                    if not key:
                        continue
                    box.prop(group, '["show_variants"]', text=key)
                    if group["show_variants"]:
                        for variant in group.children:
                            if "unbound_option" not in variant:
                                continue
                            op = box.operator("object.unbound_variant", text=variant.name,
                                              depress=not variant.hide_viewport)
                            op.root, op.group, op.option = root.name, key, variant["unbound_option"]
                box.label(text="See Unbound assembly report for limits")
            obj = context.active_object
            if obj and obj.get("unbound_materials_path"):
                box = self.layout.box()
                box.label(text="Original material slots restored")
                box.label(text="Surface shader is unresolved")
                box.prop(obj, '["unbound_show_material_rows"]', text="Source material variants")
                if obj["unbound_show_material_rows"]:
                    for row in json.loads(obj["unbound_material_variants_json"]):
                        op = box.operator("object.unbound_material_variant",
                            text=row["Hash"] + " / " + row["DatabaseGuid"][:8] + ":" + str(row["Row"]))
                        op.database_guid, op.row = row["DatabaseGuid"], row["Row"]

    def menu(self, context):
        self.layout.operator(IMPORT_SCENE_OT_unbound_batch.bl_idname, text="Unbound batch manifest (.json)")
        self.layout.operator(IMPORT_SCENE_OT_unbound_assembly.bl_idname, text="Assemble existing Unbound meshes")
        self.layout.operator(IMPORT_SCENE_OT_unbound_materials.bl_idname, text="Restore Unbound material slots")

    global _registered_classes, _menu
    _registered_classes = [IMPORT_SCENE_OT_unbound_batch, IMPORT_SCENE_OT_unbound_assembly, IMPORT_SCENE_OT_unbound_materials,
                           OBJECT_OT_unbound_variant, OBJECT_OT_unbound_material_variant, VIEW3D_PT_unbound_vehicle]
    _menu = menu
    for cls in _registered_classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu)


def unregister():
    import bpy
    bpy.types.TOPBAR_MT_file_import.remove(_menu)
    for cls in reversed(_registered_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
