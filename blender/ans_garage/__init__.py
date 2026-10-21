"""An's Garage for Blender: imports vehicles exported by An's Garage for Frosty.

Imports the manifest's exported FBX files without recentering or applying transforms.
Source slots are restored, then surfaces are built from compiled source-shader profiles
(static state) before vehicle assembly. Shaders without a resolved profile stay unconnected and are reported.
"""
bl_info = {"name": "An's Garage for Blender", "author": "An Vu", "version": (1, 0, 0), "blender": (4, 0, 0),
           "location": "File > Import > An's Garage vehicle; 3D View > Sidebar > An's Garage",
           "description": "Import NFS Unbound vehicles exported with An's Garage for Frosty",
           "category": "Import-Export"}

import json
import re
import time
from pathlib import Path

# The import running in the background of the UI (one at a time): read by the sidebar panel.
RUN = {}


class ConsoleProgress:
    """Stage lines in the system console (Window > Toggle System Console) at each new stage and every 10%."""

    def __init__(self):
        self.stage, self.step = None, None

    def update(self, stage, pct, done, total):
        step = int(pct // 10)
        if stage != self.stage:
            self.stage = stage
            print("An's Garage: %s..." % stage, flush=True)
        elif step != self.step and total > 1:
            print("An's Garage: %s %d/%d (%d%%)" % (stage, done, total, pct), flush=True)
        self.step = step


def _scaled(steps, stage, start, end):
    """Re-yield (done, total) progress of a sub-step as (stage, percent, done, total) within start..end."""
    while True:
        try:
            done, total = next(steps)
        except StopIteration as stop:
            return stop.value
        yield stage, start + (end - start) * (done / total if total else 1.0), done, total


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


def tires_module():
    from . import unbound_tires
    return unbound_tires


def animation_module():
    from . import unbound_animation
    return unbound_animation


def add_moving_parts(root, report=None):
    """Sliders for the car's moving parts (doors, windows, hood, boot, active aero); problems go to the report."""
    try:
        result = animation_module().build(root)
        lines = ["Moving parts: %d sliders (%s)" % (len(result["Controls"]), ", ".join(c["Label"] for c in result["Controls"]))]
        lines += ["Moving parts: " + x for x in result["Issues"]]
    except Exception as exc:
        lines = ["Moving parts: " + str(exc)]
    if report is not None:
        report.write("\n" + "\n".join(lines))
    return lines


_TIRE_INDEX = {}


def tire_library(context):
    """Tire library folder: the add-on preference, else the scene's (set by Locate tire library)."""
    addon = context.preferences.addons.get(__name__)
    folder = getattr(getattr(addon, "preferences", None), "tire_library", "") if addon else ""
    return folder or context.scene.get("ans_garage_tire_library", "")


def tire_index(folder):
    if folder not in _TIRE_INDEX:
        try:
            _TIRE_INDEX[folder] = tires_module().load_index(folder)
        except (OSError, ValueError):
            _TIRE_INDEX[folder] = None
    return _TIRE_INDEX[folder]


def surfaces_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("unbound_surfaces", Path(__file__).with_name("unbound_surfaces.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def import_manifest(filepath, assemble=True, materials=True):
    """Import a whole vehicle now (blocking; used from scripts, tests and background mode)."""
    steps, console = import_steps(filepath, assemble, materials), ConsoleProgress()
    while True:
        try:
            console.update(*next(steps))
        except StopIteration as stop:
            print("An's Garage: done", flush=True)
            return stop.value


def vehicle_label(filepath):
    """In-game vehicle name from assembly.json when the export has one, else the export folder name."""
    path = Path(filepath)
    try:
        name = (json.loads(path.with_name("assembly.json").read_text(encoding="utf-8-sig")).get("VehicleName") or {}).get("Long")
    except (OSError, ValueError):
        name = None
    return name or path.parent.name


def import_steps(filepath, assemble=True, materials=True):
    """The vehicle import as a generator: yields (stage, percent, done, total) after each unit of work and returns
    (count, failures). The sidebar import runs it in short slices so Blender stays responsive."""
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
    for index, mesh in enumerate(records):
        yield "Importing parts", 20.0 * index / max(1, len(records)), index, len(records)
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
    report = bpy.data.texts.new("An's Garage import report")
    report.write("Imported %d/%d meshes\n" % (count, len(records)) + "\n".join(failures))
    if materials and path.with_name("materials.json").is_file():
        try:
            material_report = yield from _scaled(materials_module().reconstruct_steps(path, imported_objects),
                                                 "Restoring material slots", 20.0, 25.0)
            assignment = ["Materials: " + x["Issue"] for x in material_report["Issues"]
                          if x.get("Severity") == "assignment_failed"]
            failures.extend(assignment)
            if assignment:
                report.write("\n" + "\n".join(assignment))
            surface_report = yield from _scaled(surfaces_module().surface_steps(imported_objects, path),
                                                "Building materials", 25.0, 75.0)
            report.write("\nSupported surfaces: %d built; %d issues; %d unsupported slots. See An's Garage surface report." %
                         (len(surface_report["Built"]), len(surface_report["Issues"]), len(surface_report["Unsupported"])))
            report.write("\nBy shader: " + json.dumps(surface_report["Summary"]["BuiltByShader"]) +
                         "\nUnsupported by shader: " + json.dumps(surface_report["Summary"]["UnsupportedByShader"]))
        except Exception as exc:
            failures.append("Materials: " + str(exc))
            report.write("\nMaterials: " + str(exc))
    if assemble and path.with_name("assembly.json").is_file() and not failures:
        try:
            yield "Assembling the vehicle", 75.0, 0, 1
            root, _ = assembly_module().assemble_existing(path)
        except Exception as exc:
            failures.append("Assembly: " + str(exc))
            report.write("\nAssembly: " + str(exc))
        else:
            yield "Adding moving parts", 78.0, 0, 1
            add_moving_parts(root, report)
            if materials and path.with_name("materials.json").is_file():
                # Per-wheel inputs (front/rear selectors) exist only on assembled wheel parts.
                surface_report = yield from _scaled(surfaces_module().surface_steps(None, path),
                                                    "Building per-wheel materials", 80.0, 100.0)
                report.write("\nAfter assembly: %d more slots built (per-wheel inputs); %d issues." %
                             (len(surface_report["Built"]), len(surface_report["Issues"])))
    yield "Finishing", 100.0, 1, 1
    return count, failures


def draw_status(self, context):
    """Progress bar in Blender's status bar while an import runs (always visible, whatever the sidebar shows)."""
    if not RUN:
        return
    row = self.layout.row(align=True)
    row.label(text="An's Garage", icon="IMPORT")
    text = "%s  %d%%  %d:%02d" % (RUN["stage"], RUN["pct"], *divmod(int(time.time() - RUN["start"]), 60))
    bar = row.row(align=True)
    bar.ui_units_x = 18  # wide enough for the stage text
    if hasattr(bar, "progress"):
        bar.progress(factor=RUN["pct"] / 100.0, type="BAR", text=text)
    else:
        bar.label(text=text)
    row.operator("wm.ans_garage_cancel_import", text="", icon="CANCEL")


def register():
    import bpy
    from bpy_extras.io_utils import ImportHelper
    from bpy.props import StringProperty, IntProperty

    class IMPORT_SCENE_OT_ans_garage_vehicle(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.ans_garage_vehicle"
        bl_label = "An's Garage vehicle"
        bl_options = {"REGISTER", "UNDO"}
        filename_ext = ".json"
        filter_glob: StringProperty(default="*.json", options={"HIDDEN"})

        def execute(self, context):
            # Scripts and background runs import in one go; from the UI the import runs in slices (modal) so
            # Blender keeps drawing: progress bar in the An's Garage sidebar and the status bar.
            if bpy.app.background or not context.window:
                try:
                    count, failures = import_manifest(self.filepath)
                    self.report({"WARNING" if failures else "INFO"},
                                "%d imported; %d failures. See An's Garage import report." % (count, len(failures)))
                    return {"FINISHED"}
                except Exception as exc:
                    self.report({"ERROR"}, str(exc))
                    return {"CANCELLED"}
            if RUN:
                self.report({"ERROR"}, "An import is already running")
                return {"CANCELLED"}
            RUN.update(steps=import_steps(self.filepath), name=vehicle_label(self.filepath), stage="Starting",
                       pct=0.0, done=0, total=0, start=time.time(), cancel=False)
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.spaces.active.show_region_ui = True
                    for region in area.regions:
                        if region.type == "UI":
                            try:
                                region.active_panel_category = "An's Garage"
                            except (AttributeError, TypeError):
                                pass  # older Blender: the tab stays as it was
            self._timer = context.window_manager.event_timer_add(0.02, window=context.window)
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}

        def modal(self, context, event):
            if event.type in {"Z", "Y"} and (event.ctrl or event.oskey):
                return {"RUNNING_MODAL"}  # no undo/redo while the import is still changing the scene
            if event.type == "ESC" and event.value == "PRESS":
                RUN["cancel"] = True
            if event.type != "TIMER":
                return {"PASS_THROUGH"}
            result = None
            deadline = time.perf_counter() + 0.15
            try:
                while time.perf_counter() < deadline:
                    if RUN["cancel"]:
                        RUN["steps"].close()
                        result = ("cancelled", None)
                        break
                    RUN["stage"], RUN["pct"], RUN["done"], RUN["total"] = next(RUN["steps"])
            except StopIteration as stop:
                result = ("done", stop.value)
            except Exception as exc:
                result = ("error", exc)
            elapsed = time.time() - RUN["start"]
            if result is None:
                for area in context.screen.areas:
                    if area.type in {"VIEW_3D", "STATUSBAR"}:
                        area.tag_redraw()
                return {"PASS_THROUGH"}
            context.window_manager.event_timer_remove(self._timer)
            RUN.clear()
            for area in context.screen.areas:
                if area.type in {"VIEW_3D", "STATUSBAR"}:
                    area.tag_redraw()
            kind, value = result
            if kind == "done":
                count, failures = value
                self.report({"WARNING" if failures else "INFO"}, "%d parts imported in %d:%02d; %d failures. See An's "
                            "Garage import report." % (count, *divmod(int(elapsed), 60), len(failures)))
                return {"FINISHED"}
            if kind == "cancelled":
                self.report({"WARNING"}, "Import cancelled; the parts imported so far stay in the scene (not assembled)")
                return {"CANCELLED"}
            self.report({"ERROR"}, str(value))
            return {"CANCELLED"}

    class AnsGaragePreferences(bpy.types.AddonPreferences):
        bl_idname = __name__
        tire_library: StringProperty(name="Tire library folder", subtype="DIR_PATH",
                                     description="Folder made by Frosty: Tools > An's Garage > Export tire library...")

        def draw(self, context):
            self.layout.prop(self, "tire_library")
            self.layout.label(text="Export it once in Frosty: Tools > An's Garage > Export tire library...")

    class IMPORT_SCENE_OT_ans_garage_locate_tires(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.ans_garage_locate_tires"
        bl_label = "Locate tire library"
        filename_ext = ".json"
        filter_glob: StringProperty(default="tires.json", options={"HIDDEN"})

        def execute(self, context):
            folder = str(Path(self.filepath).parent)
            if tire_index(folder) is None:
                _TIRE_INDEX.pop(folder, None)
                self.report({"ERROR"}, "Not a tire library (tires.json from An's Garage for Frosty)")
                return {"CANCELLED"}
            context.scene["ans_garage_tire_library"] = folder
            addon = context.preferences.addons.get(__name__)
            if addon and getattr(addon, "preferences", None) is not None:
                addon.preferences.tire_library = folder
            return {"FINISHED"}

    class OBJECT_OT_ans_garage_tire(bpy.types.Operator):
        bl_idname = "object.ans_garage_tire"
        bl_label = "Choose tires"
        bl_options = {"REGISTER", "UNDO"}
        root: StringProperty()
        tire: StringProperty()
        lettering: StringProperty(default="Plain")

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            folder = tire_library(context)
            if root is None or (self.tire != "Stock" and not folder):
                self.report({"ERROR"}, "Locate the tire library first")
                return {"CANCELLED"}
            try:
                notes = tires_module().apply_tire(root, self.tire, self.lettering, folder)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            if notes:
                self.report({"WARNING"}, "; ".join(notes))
            return {"FINISHED"}

    class OBJECT_OT_ans_garage_moving_parts(bpy.types.Operator):
        bl_idname = "object.ans_garage_moving_parts"
        bl_label = "Add moving parts"
        bl_description = ("Add sliders for the doors, windows, hood, boot and active aero, from the game's animation data "
                          "(for cars imported before 1.0.0)")
        bl_options = {"REGISTER", "UNDO"}
        root: StringProperty(options={"SKIP_SAVE"})

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            if root is None:
                return {"CANCELLED"}
            lines = add_moving_parts(root, bpy.data.texts.get("An's Garage assembly report"))
            self.report({"INFO"}, lines[0] if lines else "Done")
            return {"FINISHED"}

    class OBJECT_OT_ans_garage_close_moving_parts(bpy.types.Operator):
        bl_idname = "object.ans_garage_close_moving_parts"
        bl_label = "Close all"
        bl_description = "Set every moving part slider of this car to 0"
        bl_options = {"REGISTER", "UNDO"}
        root: StringProperty(options={"SKIP_SAVE"})

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            obj, controls = animation_module().controls(root) if root else (None, [])
            for c in controls:
                obj[c["Key"]] = 0.0
            if obj is not None:
                obj.update_tag()
            return {"FINISHED"}

    class WM_OT_ans_garage_cancel_import(bpy.types.Operator):
        bl_idname = "wm.ans_garage_cancel_import"
        bl_label = "Cancel vehicle import"

        def execute(self, context):
            if RUN:
                RUN["cancel"] = True
            return {"FINISHED"}

    class IMPORT_SCENE_OT_ans_garage_assembly(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.ans_garage_assembly"
        bl_label = "Assemble imported vehicle meshes"
        bl_options = {"REGISTER", "UNDO"}
        filename_ext = ".json"
        filter_glob: StringProperty(default="manifest.json", options={"HIDDEN"})
        def execute(self, context):
            try:
                root, _ = assembly_module().assemble_existing(self.filepath)
                add_moving_parts(root, bpy.data.texts.get("An's Garage assembly report"))
                self.report({"INFO"}, "Assembly created. See the An's Garage sidebar and assembly report.")
                return {"FINISHED"}
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

    class IMPORT_SCENE_OT_ans_garage_material_slots(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.ans_garage_material_slots"
        bl_label = "Restore vehicle material slots"
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

    class OBJECT_OT_ans_garage_build_materials(bpy.types.Operator):
        bl_idname = "object.ans_garage_build_materials"
        bl_label = "Build supported materials"
        bl_description = ("Build surfaces from compiled source-shader profiles (static state); "
                          "keep unsupported shaders unconnected and preserve existing node edits")
        bl_options = {"REGISTER", "UNDO"}
        def execute(self, context):
            result = surfaces_module().apply_supported_surfaces()
            self.report({"WARNING" if result["Issues"] else "INFO"},
                "%d slots built, %d already built, %d unsupported, %d issues. See An's Garage surface report." %
                tuple(len(result[k]) for k in ("Built", "AlreadyBuilt", "Unsupported", "Issues")))
            return {"FINISHED"}

    class IMPORT_SCENE_OT_ans_garage_locate_export(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.ans_garage_locate_export"
        bl_label = "Locate export manifest"
        bl_description = "Choose manifest.json or materials.json in a moved export folder, then build supported materials"
        bl_options = {"REGISTER", "UNDO"}
        filename_ext = ".json"
        filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
        def execute(self, context):
            result = surfaces_module().apply_supported_surfaces(export_path=self.filepath)
            self.report({"WARNING" if result["Issues"] else "INFO"},
                "%d slots built; %d issues. See An's Garage surface report." %
                (len(result["Built"]), len(result["Issues"])))
            return {"FINISHED"}

    class IMPORT_SCENE_OT_ans_garage_locate_shader_defaults(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.ans_garage_locate_shader_defaults"
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
                "%d slots built; %d issues. See An's Garage surface report." % (len(result["Built"]), len(result["Issues"])))
            return {"FINISHED"}

    class OBJECT_OT_ans_garage_variant(bpy.types.Operator):
        bl_idname = "object.ans_garage_variant"
        bl_label = "Switch vehicle part"
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

    class OBJECT_OT_ans_garage_preset(bpy.types.Operator):
        bl_idname = "object.ans_garage_preset"
        bl_label = "Apply vehicle preset"
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

    class OBJECT_OT_ans_garage_material_row(bpy.types.Operator):
        bl_idname = "object.ans_garage_material_row"
        bl_label = "Select source material database row"
        bl_options = {"REGISTER", "UNDO"}
        database_guid: StringProperty()
        row: IntProperty()
        def execute(self, context):
            try:
                obj = context.active_object
                if not obj or not obj.get("unbound_materials_path"):
                    raise ValueError("Select a mesh with restored vehicle material slots")
                materials_module().apply_material_variant(obj["unbound_materials_path"],
                    obj["unbound_mesh_id"], self.database_guid, self.row, context.selected_objects)
                surfaces_module().apply_supported_surfaces(context.selected_objects)
                self.report({"INFO"}, "Source row selected. Supported surfaces rebuilt; see An's Garage surface report.")
                return {"FINISHED"}
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}

    class VIEW3D_PT_ans_garage_vehicle(bpy.types.Panel):
        bl_label = "Vehicle"
        bl_idname = "VIEW3D_PT_ans_garage_vehicle"
        bl_space_type = "VIEW_3D"
        bl_region_type = "UI"
        bl_category = "An's Garage"
        def draw(self, context):
            def label(value):
                value = value.rsplit("_template_", 1)[-1].replace("_", " ")
                return re.sub(r"\bSet([A-Za-z]+)\b", lambda m: "Set " + m.group(1).upper(), value)
            if RUN:
                run = self.layout.box()
                run.label(text="Importing " + RUN["name"], icon="IMPORT")
                text = "%d%%" % RUN["pct"]
                if hasattr(run, "progress"):
                    run.progress(factor=RUN["pct"] / 100.0, type="BAR", text=text)
                else:
                    run.label(text=text)
                run.label(text=RUN["stage"] + ("  %d / %d" % (RUN["done"], RUN["total"]) if RUN["total"] > 1 else ""))
                run.label(text="Elapsed %d:%02d" % divmod(int(time.time() - RUN["start"]), 60))
                run.label(text="Leave the scene alone until it finishes", icon="INFO")
                run.operator("wm.ans_garage_cancel_import", text="Cancel", icon="CANCEL")
            surfaces = self.layout.box()
            surfaces.label(text="Materials %d.%d.%d: compiled source shaders" % bl_info["version"])
            surfaces.operator("object.ans_garage_build_materials")
            surfaces.operator("import_scene.ans_garage_locate_export", text="Locate export manifest…")
            surfaces.operator("import_scene.ans_garage_locate_shader_defaults", text="Locate shader default textures…")
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
                    surfaces.label(text="Not a complete car: see An's Garage surface report", icon="ERROR")
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
                    op = box.operator("object.ans_garage_preset", text="Apply preset: " + label(preset),
                                      depress=current == preset)
                    op.root, op.preset = root.name, preset
                box.label(text="Then choose individual parts below.")
                for group in root.children:
                    key = group.get("unbound_choice_group")
                    if not key:
                        continue
                    selected = [v for v in group.children if "unbound_option" in v and not v.hide_viewport]
                    selected_label = (selected[0].get("unbound_label") or label(selected[0].name.split(" | ", 1)[-1])) \
                        if len(selected) == 1 else "Custom"
                    box.prop(group, '["show_variants"]', text=group.get("unbound_label", key) + ": " + selected_label,
                             icon="TRIA_DOWN" if group["show_variants"] else "TRIA_RIGHT", emboss=False)
                    if group["show_variants"]:
                        for variant in group.children:
                            if "unbound_option" not in variant:
                                continue
                            text = "None (hide this part)" if variant["unbound_option"] == "none" else \
                                (variant.get("unbound_label") or label(variant.name.split(" | ", 1)[-1]))
                            op = box.operator("object.ans_garage_variant", text=text,
                                              depress=not variant.hide_viewport)
                            op.root, op.group, op.option = root.name, key, variant["unbound_option"]
                            op.preset = ""  # Explicit even when replacing an already-loaded older add-on.
                current = json.loads(root.get("ans_garage_tire_json") or '{"Name": "Stock", "Lettering": "Plain"}')
                tires = box.box()
                tires.label(text="Tires: %s%s" % (current["Name"], ", brand lettering" if current["Name"] != "Stock"
                                                  and current["Lettering"] == "Brand" else ""), icon="MESH_TORUS")
                folder = tire_library(context)
                index = tire_index(folder) if folder else None
                if index is None:
                    tires.operator("import_scene.ans_garage_locate_tires", text="Locate tire library…")
                else:
                    grid = tires.grid_flow(columns=2, align=True)
                    for name in ["Stock"] + tires_module().tire_names(index):
                        op = grid.operator("object.ans_garage_tire", text=name if name != "Stock" else "Stock (car's own)",
                                           depress=current["Name"] == name)
                        op.root, op.tire, op.lettering = root.name, name, current["Lettering"]
                    if current["Name"] != "Stock":
                        row = tires.row(align=True)
                        for lettering, text in (("Plain", "Plain sidewall"), ("Brand", "Brand lettering")):
                            op = row.operator("object.ans_garage_tire", text=text, depress=current["Lettering"] == lettering)
                            op.root, op.tire, op.lettering = root.name, current["Name"], lettering
                moving = box.box()
                obj, controls = animation_module().controls(root)
                if obj is not None and controls:
                    row = moving.row()
                    row.label(text="Moving parts (0 closed, 1 open)", icon="ARMATURE_DATA")
                    row.operator("object.ans_garage_close_moving_parts", text="Close all").root = root.name
                    for group in animation_module().GROUPS:
                        rows = [c for c in controls if c["Group"] == group]
                        if not rows:
                            continue
                        moving.label(text=group)
                        col = moving.column(align=True)
                        for c in rows:
                            if c["Key"] in obj:
                                col.prop(obj, '["%s"]' % c["Key"], text=c["Label"], slider=True)
                elif root.get("ans_garage_moving_parts_json"):
                    moving.label(text="Moving parts: none in this car's data", icon="ARMATURE_DATA")
                else:
                    moving.operator("object.ans_garage_moving_parts", icon="ARMATURE_DATA").root = root.name
                box.label(text="See An's Garage assembly report for limits")
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
                        op = box.operator("object.ans_garage_material_row",
                            text=row["Hash"] + " / " + row["DatabaseGuid"][:8] + ":" + str(row["Row"]))
                        op.database_guid, op.row = row["DatabaseGuid"], row["Row"]

    def menu(self, context):
        self.layout.operator(IMPORT_SCENE_OT_ans_garage_vehicle.bl_idname, text="An's Garage vehicle (.json)")
        self.layout.operator(IMPORT_SCENE_OT_ans_garage_assembly.bl_idname, text="An's Garage: assemble imported meshes")
        self.layout.operator(IMPORT_SCENE_OT_ans_garage_material_slots.bl_idname, text="An's Garage: restore material slots")

    global _registered_classes, _menu
    _registered_classes = [AnsGaragePreferences, IMPORT_SCENE_OT_ans_garage_locate_tires, OBJECT_OT_ans_garage_tire,
                           OBJECT_OT_ans_garage_moving_parts, OBJECT_OT_ans_garage_close_moving_parts,
                           IMPORT_SCENE_OT_ans_garage_vehicle, WM_OT_ans_garage_cancel_import, IMPORT_SCENE_OT_ans_garage_assembly, IMPORT_SCENE_OT_ans_garage_material_slots,
                           OBJECT_OT_ans_garage_build_materials, IMPORT_SCENE_OT_ans_garage_locate_export,
                           IMPORT_SCENE_OT_ans_garage_locate_shader_defaults,
                           OBJECT_OT_ans_garage_variant, OBJECT_OT_ans_garage_preset,
                           OBJECT_OT_ans_garage_material_row, VIEW3D_PT_ans_garage_vehicle]
    _menu = menu
    for cls in _registered_classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(_menu)
    bpy.types.STATUSBAR_HT_header.prepend(draw_status)


def unregister():
    import bpy
    bpy.types.TOPBAR_MT_file_import.remove(_menu)
    bpy.types.STATUSBAR_HT_header.remove(draw_status)
    for cls in reversed(_registered_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
