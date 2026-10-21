"""Install as a legacy Blender add-on, or run from the Text Editor.

Imports the manifest's exported FBX files without recentering or applying transforms.
Source slots are restored, then surfaces are built from compiled source-shader profiles
(static state) before vehicle assembly. Shaders without a resolved profile stay unconnected and are reported.
"""
bl_info = {"name": "Unbound Batch Manifest", "author": "An Vu",
           "version": (0, 6, 1), "blender": (4, 0, 0), "category": "Import-Export"}

import json
import re
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


def surfaces_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("unbound_surfaces", Path(__file__).with_name("unbound_surfaces.py"))
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
            surface_report = surfaces_module().apply_supported_surfaces(imported_objects, path)
            report.write("\nSupported surfaces: %d built; %d issues; %d unsupported slots. See Unbound surface report." %
                         (len(surface_report["Built"]), len(surface_report["Issues"]), len(surface_report["Unsupported"])))
            report.write("\nBy shader: " + json.dumps(surface_report["Summary"]["BuiltByShader"]) +
                         "\nUnsupported by shader: " + json.dumps(surface_report["Summary"]["UnsupportedByShader"]))
        except Exception as exc:
            failures.append("Materials: " + str(exc))
            report.write("\nMaterials: " + str(exc))
    if assemble and path.with_name("assembly.json").is_file() and not failures:
        try:
            assembly_module().assemble_existing(path)
        except Exception as exc:
            failures.append("Assembly: " + str(exc))
            report.write("\nAssembly: " + str(exc))
        else:
            if materials and path.with_name("materials.json").is_file():
                # Per-wheel inputs (front/rear selectors) exist only on assembled wheel parts.
                surface_report = surfaces_module().apply_supported_surfaces(None, path)
                report.write("\nAfter assembly: %d more slots built (per-wheel inputs); %d issues." %
                             (len(surface_report["Built"]), len(surface_report["Issues"])))
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
                surfaces_module().apply_supported_surfaces(export_path=self.filepath)
                failed = sum(x.get("Severity") == "assignment_failed" for x in result["Issues"])
                self.report({"WARNING" if failed else "INFO"},
                            "%d objects assigned; %d failures. See material reconstruction report." % (len(result["Objects"]), failed))
                return {"FINISHED"}
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

    class OBJECT_OT_unbound_surfaces(bpy.types.Operator):
        bl_idname = "object.unbound_surfaces"
        bl_label = "Build supported materials"
        bl_description = ("Build surfaces from compiled source-shader profiles (static state); "
                          "keep unsupported shaders unconnected and preserve existing node edits")
        bl_options = {"REGISTER", "UNDO"}
        def execute(self, context):
            result = surfaces_module().apply_supported_surfaces()
            self.report({"WARNING" if result["Issues"] else "INFO"},
                "%d slots built, %d already built, %d unsupported, %d issues. See Unbound surface report." %
                tuple(len(result[k]) for k in ("Built", "AlreadyBuilt", "Unsupported", "Issues")))
            return {"FINISHED"}

    class IMPORT_SCENE_OT_unbound_surface_sources(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.unbound_surface_sources"
        bl_label = "Locate export manifest"
        bl_description = "Choose manifest.json or materials.json in a moved export folder, then build supported materials"
        bl_options = {"REGISTER", "UNDO"}
        filename_ext = ".json"
        filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
        def execute(self, context):
            result = surfaces_module().apply_supported_surfaces(export_path=self.filepath)
            self.report({"WARNING" if result["Issues"] else "INFO"},
                "%d slots built; %d issues. See Unbound surface report." %
                (len(result["Built"]), len(result["Issues"])))
            return {"FINISHED"}

    class IMPORT_SCENE_OT_unbound_shader_defaults(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.unbound_shader_defaults"
        bl_label = "Locate shader default textures"
        bl_description = ("Choose textures.json of an exported shader-defaults folder (shared vehicle textures such as "
                          "material swatches), then build supported materials")
        bl_options = {"REGISTER", "UNDO"}
        filename_ext = ".json"
        filter_glob: StringProperty(default="textures.json", options={"HIDDEN"})
        def execute(self, context):
            folder = Path(self.filepath).resolve().parent
            if not (folder / "textures.json").is_file():
                self.report({"ERROR"}, "Select the textures.json inside a shader-defaults folder")
                return {"CANCELLED"}
            context.scene["unbound_shader_defaults_path"] = str(folder)
            result = surfaces_module().apply_supported_surfaces()
            self.report({"WARNING" if result["Issues"] else "INFO"},
                "%d slots built; %d issues. See Unbound surface report." % (len(result["Built"]), len(result["Issues"])))
            return {"FINISHED"}

    class OBJECT_OT_unbound_variant(bpy.types.Operator):
        bl_idname = "object.unbound_variant"
        bl_label = "Switch Unbound variant"
        bl_options = {"REGISTER", "UNDO"}
        # UI operator invocations normally reuse last-used properties. In 0.4.1
        # a previous preset="Stock" survived a subsequent single-part click and
        # silently reapplied Stock. These are explicit button arguments.
        root: StringProperty(options={"SKIP_SAVE"})
        group: StringProperty(options={"SKIP_SAVE"})
        option: StringProperty(options={"SKIP_SAVE"})
        preset: StringProperty(options={"SKIP_SAVE"})  # Legacy scripting API.
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

    class OBJECT_OT_unbound_preset(bpy.types.Operator):
        bl_idname = "object.unbound_preset"
        bl_label = "Apply Unbound vehicle preset"
        bl_description = "Reset all part categories to this source preset"
        bl_options = {"REGISTER", "UNDO"}
        root: StringProperty(options={"SKIP_SAVE"})
        preset: StringProperty(options={"SKIP_SAVE"})
        def execute(self, context):
            try:
                assembly_module().apply_preset(bpy.data.collections[self.root], self.preset)
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
                surfaces_module().apply_supported_surfaces(context.selected_objects)
                self.report({"INFO"}, "Source row selected. Supported surfaces rebuilt; see Unbound surface report.")
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
            def label(value):
                value = value.rsplit("_template_", 1)[-1].replace("_", " ")
                return re.sub(r"\bSet([A-Za-z]+)\b", lambda m: "Set " + m.group(1).upper(), value)
            surfaces = self.layout.box()
            surfaces.label(text="Materials 0.6.1: compiled source shaders")
            surfaces.operator("object.unbound_surfaces")
            surfaces.operator("import_scene.unbound_surface_sources", text="Locate export manifest…")
            surfaces.operator("import_scene.unbound_shader_defaults", text="Locate shader default textures…")
            summary = None
            name = context.scene.get("unbound_surface_report")
            if name and name in bpy.data.texts:
                try:
                    summary = json.loads(bpy.data.texts[name].as_string()).get("Summary")
                except ValueError:
                    summary = None
            if summary:
                surfaces.label(text="Built %d slots; %d unsupported; %d issues" %
                               (summary["BuiltSlots"], summary["UnsupportedSlots"], summary["IssueSlots"]))
                if summary["UnsupportedSlots"] or summary["IssueSlots"]:
                    surfaces.label(text="Not a complete car: see Unbound surface report", icon="ERROR")
            paint = bpy.data.node_groups.get("Unbound | Runtime Ext_Carpaint_Diffuse")
            rgb = next((n for n in paint.nodes if n.type == "RGB"), None) if paint else None
            if rgb:
                surfaces.prop(rgb.outputs[0], "default_value", text="Vehicle paint")
            for root in context.scene.collection.children:
                if not root.get("unbound_assembly_path"):
                    continue
                box = self.layout.box()
                box.label(text=root.name)
                current = assembly_module().current_preset(root)
                box.label(text="Current: " + label(current))
                for preset in json.loads(root["unbound_presets_json"]):
                    op = box.operator("object.unbound_preset", text="Apply preset: " + label(preset),
                                      depress=current == preset)
                    op.root, op.preset = root.name, preset
                box.label(text="Then choose individual parts below.")
                for group in root.children:
                    key = group.get("unbound_choice_group")
                    if not key:
                        continue
                    selected = [v for v in group.children if "unbound_option" in v and not v.hide_viewport]
                    selected_label = label(selected[0].name.split(" | ", 1)[-1]) if len(selected) == 1 else "Custom"
                    box.prop(group, '["show_variants"]', text=key + ": " + selected_label,
                             icon="TRIA_DOWN" if group["show_variants"] else "TRIA_RIGHT", emboss=False)
                    if group["show_variants"]:
                        for variant in group.children:
                            if "unbound_option" not in variant:
                                continue
                            text = "None (hide this part)" if variant["unbound_option"] == "none" else label(variant.name.split(" | ", 1)[-1])
                            op = box.operator("object.unbound_variant", text=text,
                                              depress=not variant.hide_viewport)
                            op.root, op.group, op.option = root.name, key, variant["unbound_option"]
                            op.preset = ""  # Explicit even when replacing an already-loaded older add-on.
                box.label(text="See Unbound assembly report for limits")
            obj = context.active_object
            if obj and obj.get("unbound_materials_path"):
                box = self.layout.box()
                box.label(text="Original material slots restored")
                material = obj.active_material
                built = material and material.get("unbound_surface_profile")
                box.label(text=str(material.get("unbound_status", ""))[:64] if built else "Surface shader is unresolved")
                box.prop(obj, '["unbound_show_material_rows"]', text="Source material variants",
                         icon="TRIA_DOWN" if obj["unbound_show_material_rows"] else "TRIA_RIGHT", emboss=False)
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
                           OBJECT_OT_unbound_surfaces, IMPORT_SCENE_OT_unbound_surface_sources,
                           IMPORT_SCENE_OT_unbound_shader_defaults,
                           OBJECT_OT_unbound_variant, OBJECT_OT_unbound_preset,
                           OBJECT_OT_unbound_material_variant, VIEW3D_PT_unbound_vehicle]
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
