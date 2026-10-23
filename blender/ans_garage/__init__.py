"""An's Garage for Blender: imports vehicles exported by An's Garage for Frosty.

Imports the manifest's exported FBX files without recentering or applying transforms.
Source slots are restored, then surfaces are built from compiled source-shader profiles
(static state) before vehicle assembly. Shaders without a resolved profile stay unconnected and are reported.
"""
bl_info = {"name": "An's Garage for Blender", "author": "An Vu", "version": (1, 1, 1), "blender": (4, 0, 0),
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


# The add-on's modules, imported once (their caches, such as the loaded shader profiles, persist between imports).
def assembly_module():
    from . import unbound_assembly
    return unbound_assembly


def materials_module():
    from . import unbound_materials
    return unbound_materials


def tires_module():
    from . import unbound_tires
    return unbound_tires


def plates_module():
    from . import unbound_plates
    return unbound_plates


# Libraries exported once by An's Garage for Frosty (kind -> module that reads its index).
def rims_module():
    from . import unbound_rims
    return unbound_rims


LIBRARIES = {"tire": tires_module, "plate": plates_module, "rim": rims_module}
_LIBRARY_INDEX = {}
_PLATE_ITEMS = []  # Blender keeps only references to enum item strings: hold them here
_RIM_ITEMS = []


def library_folder(context, kind):
    """A library's folder: the add-on preference, else the scene's (set by Locate ... library)."""
    addon = context.preferences.addons.get(__name__)
    folder = getattr(getattr(addon, "preferences", None), kind + "_library", "") if addon else ""
    return folder or context.scene.get("ans_garage_%s_library" % kind, "")


def library_index(kind, folder, reload=False):
    """The library's index (tires.json, plates.json), read once per folder; None if it is not one."""
    if reload or (kind, folder) not in _LIBRARY_INDEX:
        try:
            _LIBRARY_INDEX[(kind, folder)] = LIBRARIES[kind]().load_index(folder)
        except (OSError, ValueError):
            _LIBRARY_INDEX[(kind, folder)] = None
    return _LIBRARY_INDEX[(kind, folder)]


def plate_library(context):
    return library_folder(context, "plate")


def plate_index(folder):
    return library_index("plate", folder)


def plate_label(index, key):
    if key == "Stock" or not index:
        return "Stock (car's own)" if key == "Stock" else key
    return next((p["Label"] for p in index["Plates"] if p["Key"] == key), key)


def liveries_module():
    from . import unbound_liveries
    return unbound_liveries


def car_scope(root):
    """Key of a car's runtime controls (paint colour and finish): its export folder name."""
    return Path(root["unbound_assembly_path"]).parent.name


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


def tire_library(context):
    return library_folder(context, "tire")


def tire_index(folder):
    return library_index("tire", folder)


def surfaces_module():
    from . import unbound_surfaces
    return unbound_surfaces


def import_library_parts(manifest):
    """Meshes of a library export (tires, rims) with their source material slots restored: the new objects."""
    import bpy
    before = set(bpy.data.objects)
    for _ in import_steps(manifest, assemble=False, materials=False):
        pass
    objects = [o for o in bpy.data.objects if o not in before]
    materials_module().reconstruct(manifest, objects)
    return objects


def library_collection(name, key, folder):
    """The hidden collection of a part library imported from `folder`: (collection, True when it must be filled now).
    A collection imported from another folder is replaced."""
    import bpy
    lib = bpy.data.collections.get(name)
    if lib is not None and lib.get(key) == str(folder):
        return lib, False
    if lib is not None:
        for o in list(lib.all_objects):
            bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.collections.remove(lib)
    lib = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(lib)
    lib[key] = str(folder)
    return lib, True


def finish_library(lib):
    """After filling a library collection: drop the emptied import collections and exclude the library from the view."""
    import bpy
    for col in [c for c in bpy.data.collections if c.name.startswith("Unbound | ") and not c.all_objects]:
        for parent in [p for p in bpy.data.collections if col.name in p.children] + [bpy.context.scene.collection]:
            if col.name in parent.children:
                parent.children.unlink(col)
    layer = bpy.context.view_layer.layer_collection.children.get(lib.name)
    if layer:
        layer.exclude = True


def place_copies(sources, collection, spin, local):
    """Copies of a library part's objects in `collection`, its roots on a wheel's rotation empty at `local`."""
    from mathutils import Matrix
    mapping = {}
    for s in sources:
        c = s.copy()
        collection.objects.link(c)
        mapping[s] = c
        c["unbound_assembled"] = True
    for s, c in mapping.items():
        if s.parent in mapping:
            c.parent = mapping[s.parent]
            c.matrix_parent_inverse = s.matrix_parent_inverse.copy()
            c.matrix_basis = s.matrix_basis.copy()
        else:
            c.parent = spin
            c.matrix_parent_inverse = Matrix.Identity(4)
            c.matrix_basis = local @ s.matrix_world
        for m in c.modifiers:
            if m.type == "ARMATURE" and m.object in mapping:
                m.object = mapping[m.object]
    return list(mapping.values())


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


FBX_OPTIONS = dict(global_scale=1.0, use_manual_orientation=False, bake_space_transform=False, use_anim=False,
                   automatic_bone_orientation=False, ignore_leaf_bones=False, use_prepost_rot=True)


def fbx_reader(staging):
    """Import one FBX file: (path) -> the new objects, linked to the scene's collection. Calls the FBX add-on's reader
    directly with the import operator's own defaults plus FBX_OPTIONS, skipping the operator wrapper (an undo step and
    scene update per file), into the empty `staging` scene (the reader deselects every object of its scene and sets
    the scene's frame rate for each file). A file the reader can't take there (skinned meshes need an active object
    for their armature) is read the usual way into the current scene; so is everything if that reader is missing."""
    import bpy
    try:
        from io_scene_fbx import import_fbx
        rna = bpy.ops.import_scene.fbx.get_rna_type()
        skip = {"rna_type", "filter_glob", "directory", "ui_tab", "filepath", "files"}
        options = {p.identifier: (tuple(p.default_array) if getattr(p, "is_array", False) else p.default)
                   for p in rna.properties if p.identifier not in skip and not p.is_readonly}
        options.update(FBX_OPTIONS)
    except Exception:
        import_fbx = None

    class Reports:
        def report(self, kind, message):
            if "ERROR" in kind:
                raise RuntimeError(message)

    def usual(path):
        before = set(bpy.data.objects)
        if "FINISHED" not in bpy.ops.import_scene.fbx(filepath=path, **FBX_OPTIONS):
            raise RuntimeError("Blender FBX importer did not finish")
        return list(set(bpy.data.objects) - before)

    def read(path):
        if import_fbx is None:
            return usual(path)
        try:
            with bpy.context.temp_override(scene=staging, view_layer=staging.view_layers[0]):
                if "FINISHED" not in import_fbx.load(Reports(), bpy.context, filepath=path, **options):
                    raise RuntimeError("Blender FBX importer did not finish")
            return list(staging.objects)
        except Exception:
            for obj in list(staging.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            return usual(path)
    return read


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
    # Blender's FBX importer starts and stops a thread pool for every file; for hundreds of small part files that costs
    # more than it saves (about 9 s on a 368-part car), so parts are read single-threaded. Restored afterwards.
    # Each file is read into an empty staging scene: the importer deselects every object of its scene and sets the
    # scene's frame rate for each file, which on the user's scene grows with every part already imported (and changed
    # its fps). The new objects are then exactly the staging scene's, moved into the car's collections.
    staging = bpy.data.scenes.new("An's Garage import (staging)")
    try:
        from io_scene_fbx import fbx_utils_threading as fbx_threads
    except ImportError:
        fbx_threads = None
    threaded = getattr(fbx_threads, "_MULTITHREADING_ENABLED", None)
    if fbx_threads is not None:
        fbx_threads._MULTITHREADING_ENABLED = False
    try:
        read_fbx = fbx_reader(staging)
        for index, mesh in enumerate(records):
            yield "Importing parts", 20.0 * index / max(1, len(records)), index, len(records)
            added = []
            try:
                added = read_fbx(str(files[mesh["Id"]]))
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
                for obj in added + list(staging.objects):
                    if obj.name in bpy.data.objects:
                        bpy.data.objects.remove(obj, do_unlink=True)
                failures.append(mesh["Asset"] + ": " + str(exc))
    finally:
        if fbx_threads is not None:
            fbx_threads._MULTITHREADING_ENABLED = threaded
        for obj in list(staging.objects):
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.scenes.remove(staging)
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
            if manifest.get("MovingParts", True):
                yield "Adding moving parts", 78.0, 0, 1
                add_moving_parts(root, report)
            else:
                root["ans_garage_static_export"] = True
                report.write("\nMoving parts: not built (exported as a static model; Add moving parts builds them)")
            if materials and path.with_name("materials.json").is_file():
                # Per-wheel inputs (front/rear selectors) exist only on assembled wheel parts.
                surface_report = yield from _scaled(surfaces_module().surface_steps(None, path),
                                                    "Building per-wheel materials", 80.0, 100.0)
                report.write("\nAfter assembly: %d more slots built (per-wheel inputs); %d issues." %
                             (len(surface_report["Built"]), len(surface_report["Issues"])))
    materials_module().FBX_TREES.clear()
    yield "Finishing", 100.0, 1, 1
    return count, failures


def wrapped(layout, context, text, icon="NONE"):
    """A label that wraps to the sidebar's width instead of being cut off with "..."."""
    import textwrap
    scale = context.preferences.system.ui_scale
    chars = max(12, int((context.region.width - 50 * scale) / (6.5 * scale)))
    col = layout.column(align=True)
    for i, line in enumerate(textwrap.wrap(text, chars) or [""]):
        col.label(text=line, icon=icon if i == 0 else ("BLANK1" if icon != "NONE" else "NONE"))


def draw_status(self, context):
    """Progress bar in Blender's status bar while an import runs (always visible, whatever the sidebar shows)."""
    if not RUN:
        return
    row = self.layout.row(align=True)
    row.label(text="An's Garage", icon="IMPORT")
    text = "%s  %d%%  %d:%02d" % (RUN["stage"], RUN["pct"], *divmod(int(time.time() - RUN["start"]), 60))
    bar = row.row(align=True)
    bar.ui_units_x = 18  # wide enough for the stage text
    bar.progress(factor=RUN["pct"] / 100.0, type="BAR", text=text)
    row.operator("wm.ans_garage_cancel_import", text="", icon="CANCEL")


def register():
    import bpy
    from bpy_extras.io_utils import ImportHelper
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty

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
        plate_library: StringProperty(name="License plate library folder", subtype="DIR_PATH",
                                      description="Folder made by Frosty: Tools > An's Garage > Export license plate library...")
        rim_library: StringProperty(name="Rim library folder", subtype="DIR_PATH",
                                    description="Folder made by Frosty: Tools > An's Garage > Export rim library...")

        def draw(self, context):
            self.layout.prop(self, "tire_library")
            self.layout.label(text="Export it once in Frosty: Tools > An's Garage > Export tire library...")
            self.layout.prop(self, "plate_library")
            self.layout.label(text="Export it once in Frosty: Tools > An's Garage > Export license plate library...")
            self.layout.prop(self, "rim_library")
            self.layout.label(text="Export it once in Frosty: Tools > An's Garage > Export rim library...")

    class LocateLibrary(ImportHelper):
        """Pick a library's index file; remembered in the scene and the add-on preferences."""
        filename_ext = ".json"
        kind = index_file = ""

        def execute(self, context):
            folder = str(Path(self.filepath).parent)
            if library_index(self.kind, folder, reload=True) is None:
                self.report({"ERROR"}, "Not a %s library (%s from An's Garage for Frosty)" % (self.kind, self.index_file))
                return {"CANCELLED"}
            context.scene["ans_garage_%s_library" % self.kind] = folder
            addon = context.preferences.addons.get(__name__)
            if addon and getattr(addon, "preferences", None) is not None:
                setattr(addon.preferences, self.kind + "_library", folder)
            return {"FINISHED"}

    class IMPORT_SCENE_OT_ans_garage_locate_tires(bpy.types.Operator, LocateLibrary):
        bl_idname = "import_scene.ans_garage_locate_tires"
        bl_label = "Locate tire library"
        filter_glob: StringProperty(default="*tires.json", options={"HIDDEN"})
        kind, index_file = "tire", "tires.json"

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

    class IMPORT_SCENE_OT_ans_garage_locate_plates(bpy.types.Operator, LocateLibrary):
        bl_idname = "import_scene.ans_garage_locate_plates"
        bl_label = "Locate license plate library"
        filter_glob: StringProperty(default="*plates.json", options={"HIDDEN"})
        kind, index_file = "plate", "plates.json"

    class IMPORT_SCENE_OT_ans_garage_locate_rims(bpy.types.Operator, LocateLibrary):
        bl_idname = "import_scene.ans_garage_locate_rims"
        bl_label = "Locate rim library"
        filter_glob: StringProperty(default="*rims.json", options={"HIDDEN"})
        kind, index_file = "rim", "rims.json"

    def rim_items(self, context):
        index = library_index("rim", library_folder(context, "rim")) if context else None
        items = [("Stock", "Stock (car's own wheels)", "The car's own factory wheel set")]
        for name in rims_module().rim_names(index) if index else []:
            brand = next(r["Brand"] for r in index["Rims"] if r["Name"] == name)
            items.append((name, name, brand))
        _RIM_ITEMS[:] = items
        return _RIM_ITEMS

    class OBJECT_OT_ans_garage_rim(bpy.types.Operator):
        bl_idname = "object.ans_garage_rim"
        bl_label = "Choose rims"
        bl_description = "Search the real-brand rim library (type to filter, e.g. bbs or work)"
        bl_options = {"REGISTER", "UNDO"}
        bl_property = "rim"
        root: StringProperty(options={"SKIP_SAVE"})
        rim: EnumProperty(items=rim_items, name="Rim")
        pick: BoolProperty(default=True, options={"SKIP_SAVE"})

        def invoke(self, context, event):
            if not self.pick:
                return self.execute(context)
            context.window_manager.invoke_search_popup(self)
            return {"RUNNING_MODAL"}

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            folder = library_folder(context, "rim")
            if root is None or (self.rim != "Stock" and not folder):
                self.report({"ERROR"}, "Locate the rim library first")
                return {"CANCELLED"}
            try:
                notes = rims_module().apply_rim(root, self.rim, folder)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            if notes:
                self.report({"WARNING"}, "; ".join(notes))
            return {"FINISHED"}

    class OBJECT_OT_ans_garage_rim_paint_stock(bpy.types.Operator):
        bl_idname = "object.ans_garage_rim_paint_stock"
        bl_label = "Stock rim colors"
        bl_description = "Put the car's own rim colors back"
        bl_options = {"REGISTER", "UNDO"}
        root: StringProperty(options={"SKIP_SAVE"})

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            if root is None:
                return {"CANCELLED"}
            rims_module().stock_rim_paint(root)
            return {"FINISHED"}

    def plate_items(self, context):
        index = plate_index(plate_library(context)) if context else None
        items = [("Stock", "Stock (car's own)", "The car's own license plate")]
        for p in (index or {}).get("Plates", []):
            items.append((p["Key"], p["Label"], p["Group"]))
        _PLATE_ITEMS[:] = items
        return _PLATE_ITEMS

    class OBJECT_OT_ans_garage_plate(bpy.types.Operator):
        bl_idname = "object.ans_garage_plate"
        bl_label = "Choose license plate"
        bl_description = "Search the license plate library (type to filter, e.g. cal or japan)"
        bl_options = {"REGISTER", "UNDO"}
        bl_property = "plate"
        root: StringProperty(options={"SKIP_SAVE"})
        plate: bpy.props.EnumProperty(items=plate_items, name="Plate")

        def invoke(self, context, event):
            context.window_manager.invoke_search_popup(self)
            return {"RUNNING_MODAL"}

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            folder = plate_library(context)
            if root is None or (self.plate != "Stock" and not folder):
                self.report({"ERROR"}, "Locate the license plate library first")
                return {"CANCELLED"}
            try:
                count = plates_module().apply_plate(root, self.plate, folder)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            self.report({"INFO"}, "%s on %d plates" % (plate_label(plate_index(folder), self.plate), count))
            return {"FINISHED"}

    class OBJECT_OT_ans_garage_plate_text(bpy.types.Operator):
        bl_idname = "object.ans_garage_plate_text"
        bl_label = "License plate text"
        bl_description = "Type the plate text: up to 7 letters, digits or spaces, drawn with the game's plate font"
        bl_options = {"REGISTER", "UNDO"}
        root: StringProperty(options={"SKIP_SAVE"})
        text: StringProperty(name="Text", maxlen=7, description="A-Z, 0-9 and spaces; empty for a blank plate")

        def invoke(self, context, event):
            root = bpy.data.collections.get(self.root)
            self.text = root.get("ans_garage_plate_text", "") if root else ""
            return context.window_manager.invoke_props_dialog(self)

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            if root is None:
                return {"CANCELLED"}
            try:
                plates_module().apply_text(root, self.text)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
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

    profiles = surfaces_module().profiles_module()
    finish_items = [("Stock", "Stock", "This car's own finish")] + [
        (name, name, "The game's preset finish") for name, _ in profiles.FINISH_PRESETS]
    material_items = [("Stock", "Stock", "This car's own material")] + [
        (str(t), label, "The game's paint material") for t, label in profiles.FINISHES]
    shift_items = [("Stock", "Stock", "This car's own colour shift")] + [
        (str(t), label, "The game's colour shift") for t, label in profiles.COLOR_SHIFTS]

    livery_choices = []

    def livery_items(self, context):
        root = bpy.data.collections.get(self.root) if self.root else None
        index = liveries_module().load_index(root) if root and root.get("unbound_assembly_path") else None
        items = [("None", "None (stock paint)", "The car's own paint without a livery")]
        for l in (index or {}).get("Liveries", []):
            items.append((l["Key"], l["Label"], l["Group"]))
        livery_choices[:] = items  # Blender keeps only the strings of a list that stays alive
        return livery_choices

    class OBJECT_OT_ans_garage_livery(bpy.types.Operator):
        bl_idname = "object.ans_garage_livery"
        bl_label = "Choose livery"
        bl_description = "The car's stock liveries exported with it (type to filter)"
        bl_options = {"REGISTER", "UNDO"}
        bl_property = "livery"
        root: StringProperty(options={"SKIP_SAVE"})
        livery: EnumProperty(items=livery_items, name="Livery")
        pick: BoolProperty(default=True, options={"SKIP_SAVE"})

        def invoke(self, context, event):
            if not self.pick:
                return self.execute(context)
            context.window_manager.invoke_search_popup(self)
            return {"RUNNING_MODAL"}

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            if root is None:
                return {"CANCELLED"}
            try:
                count = liveries_module().apply_livery(root, self.livery)
            except ValueError as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            self.report({"INFO"}, "%d paint slots rebuilt" % count)
            return {"FINISHED"}

    class OBJECT_OT_ans_garage_livery_car(bpy.types.Operator):
        bl_idname = "object.ans_garage_livery_car"
        bl_label = "Use the livery's paint"
        bl_description = ("Give the car the paint colour, finish and plate text that go with this livery in the game "
                          "(the AI racer's, rival's or story car's own setup)")
        bl_options = {"REGISTER", "UNDO"}
        root: StringProperty(options={"SKIP_SAVE"})

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            if root is None:
                return {"CANCELLED"}
            try:
                liveries_module().use_livery_car(root, root.get("ans_garage_livery", "None"))
            except ValueError as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            return {"FINISHED"}

    def finish_operator(idname, label, description, prop, items, keyword):
        """A search-popup operator that sets one part of the car's paint finish."""
        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            if root is None:
                return {"CANCELLED"}
            try:
                profiles.set_finish(car_scope(root), **{keyword: getattr(self, prop)})
            except ValueError as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            return {"FINISHED"}

        def invoke(self, context, event):
            context.window_manager.invoke_search_popup(self)
            return {"RUNNING_MODAL"}

        return type(idname.replace(".", "_OT_").upper(), (bpy.types.Operator,), {
            "bl_idname": idname, "bl_label": label, "bl_description": description, "bl_options": {"REGISTER", "UNDO"},
            "bl_property": prop, "__annotations__": {"root": StringProperty(options={"SKIP_SAVE"}),
                                                     prop: EnumProperty(items=items, name=label)},
            "invoke": invoke, "execute": execute})

    OBJECT_OT_ans_garage_finish = finish_operator(
        "object.ans_garage_finish", "Paint finish", "The game's preset finishes (type to filter); Stock is the car's own",
        "finish", finish_items, "preset")
    OBJECT_OT_ans_garage_material = finish_operator(
        "object.ans_garage_material", "Paint material", "The game's paint materials (type to filter); Stock is the car's own",
        "material", material_items, "finish")
    OBJECT_OT_ans_garage_color_shift = finish_operator(
        "object.ans_garage_color_shift", "Color shift", "The game's colour shift modes; Stock is the car's own",
        "shift", shift_items, "shift")

    class OBJECT_OT_ans_garage_gloss(bpy.types.Operator):
        bl_idname = "object.ans_garage_gloss"
        bl_label = "Paint gloss"
        bl_description = "Gloss, satin or matte clear coat, as in the game's garage; Stock is the car's own"
        bl_options = {"REGISTER", "UNDO"}
        root: StringProperty(options={"SKIP_SAVE"})
        gloss: StringProperty(options={"SKIP_SAVE"})

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            if root is None:
                return {"CANCELLED"}
            try:
                profiles.set_finish(car_scope(root), gloss=self.gloss)
            except ValueError as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            return {"FINISHED"}

    class OBJECT_OT_ans_garage_conditions(bpy.types.Operator):
        bl_idname = "object.ans_garage_conditions"
        bl_label = "Dirt, dust and wet"
        bl_description = ("Rebuild the surfaces that read the game's dirt, dust and wet values so the sliders can set them "
                          "(heavier shaders); remove them to go back to clean and dry")
        bl_options = {"REGISTER", "UNDO"}
        enable: BoolProperty(options={"SKIP_SAVE"})

        def execute(self, context):
            count, built, failed = surfaces_module().set_conditions(self.enable)
            self.report({"WARNING" if failed else "INFO"}, "%d of %d surfaces rebuilt%s" % (
                len(built), count, "; see the An's Garage surface report" if failed else ""))
            return {"FINISHED"}

    class WM_OT_ans_garage_cancel_import(bpy.types.Operator):
        bl_idname = "wm.ans_garage_cancel_import"
        bl_label = "Cancel vehicle import"

        def execute(self, context):
            if RUN:
                RUN["cancel"] = True
            return {"FINISHED"}

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
        filter_glob: StringProperty(default="*textures.json", options={"HIDDEN"})
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
        # Explicit button arguments (SKIP_SAVE): an operator otherwise reuses its last-used properties.
        root: StringProperty(options={"SKIP_SAVE"})
        group: StringProperty(options={"SKIP_SAVE"})
        option: StringProperty(options={"SKIP_SAVE"})
        def execute(self, context):
            try:
                assembly_module().set_variant(bpy.data.collections[self.root], self.group, self.option)
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

    class VIEW3D_PT_ans_garage_vehicle(bpy.types.Panel):
        bl_label = "An's Garage %d.%d.%d" % bl_info["version"]
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
                wrapped(run, context, "Importing " + RUN["name"], icon="IMPORT")
                text = "%d%%" % RUN["pct"]
                run.progress(factor=RUN["pct"] / 100.0, type="BAR", text=text)
                run.label(text=RUN["stage"] + ("  %d / %d" % (RUN["done"], RUN["total"]) if RUN["total"] > 1 else ""))
                run.label(text="Elapsed %d:%02d" % divmod(int(time.time() - RUN["start"]), 60))
                wrapped(run, context, "Leave the scene alone until it finishes", icon="INFO")
                run.operator("wm.ans_garage_cancel_import", text="Cancel", icon="CANCEL")
            surfaces = self.layout.box()
            wrapped(surfaces, context, "Materials from the game's compiled shaders")
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
                wrapped(surfaces, context, "Built %d slots; %d unsupported; %d issues" %
                        (summary["BuiltSlots"], summary["UnsupportedSlots"], summary["IssueSlots"]))
                if summary["UnsupportedSlots"] or summary["IssueSlots"]:
                    wrapped(surfaces, context, "Not a complete car: see the An's Garage surface report in the Text Editor",
                            icon="ERROR")
            if summary:
                if context.scene.get("ans_garage_conditions"):
                    wrapped(surfaces, context, "Dirt, dust and wet: 0 clean and dry", icon="MATFLUID")
                    col = surfaces.column(align=True)
                    for label, prop, _ in surfaces_module().profiles_module().CONDITIONS.values():
                        col.prop(context.scene, prop, text=label, slider=True)
                    surfaces.operator("object.ans_garage_conditions", text="Remove dirt, dust and wet").enable = False
                else:
                    surfaces.operator("object.ans_garage_conditions", text="Add dirt, dust and wet",
                                      icon="MATFLUID").enable = True
            for root in context.scene.collection.children:
                if not root.get("unbound_assembly_path"):
                    continue
                box = self.layout.box()
                wrapped(box, context, root.name, icon="AUTO")
                current = assembly_module().current_preset(root)
                wrapped(box, context, "Current preset: " + label(current))
                for preset in json.loads(root["unbound_presets_json"]):
                    op = box.operator("object.ans_garage_preset", text="Apply preset: " + label(preset),
                                      depress=current == preset)
                    op.root, op.preset = root.name, preset
                wrapped(box, context, "Then choose individual parts below.")
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
                scope = car_scope(root)
                paint = profiles.runtime_group(scope, "Ext_Carpaint_Diffuse")
                if paint:
                    pbox = box.box()
                    wrapped(pbox, context, "Paint", icon="COLOR")
                    pbox.prop(profiles.runtime_rgb(paint), "default_value", text="Color")
                    now, stock = profiles.finish_value(scope)
                    if now:
                        is_stock = now == stock
                        preset = "Stock" if is_stock else profiles.finish_preset(scope) or "Custom"
                        pbox.operator("object.ans_garage_finish", text="Finish: " + preset, icon="DOWNARROW_HLT").root = root.name
                        for idname, title, table, i in (("object.ans_garage_material", "Material", profiles.FINISHES, 0),
                                                         ("object.ans_garage_color_shift", "Color shift", profiles.COLOR_SHIFTS, 1)):
                            text = dict(table).get(now[i], "Type %d" % now[i]) + (" (stock)" if now[i] == stock[i] else "")
                            pbox.operator(idname, text="%s: %s" % (title, text), icon="DOWNARROW_HLT").root = root.name
                        row = pbox.row(align=True)
                        for key, label in [("Stock", "Stock")] + [(str(k), l) for k, l in profiles.GLOSS_LEVELS]:
                            # Levels 2 and up render the same (no clear coat): shown as Matte.
                            on = now[2] == stock[2] if key == "Stock" else now[2] != stock[2] and min(now[2], 2) == int(key)
                            op = row.operator("object.ans_garage_gloss", text=label, depress=on)
                            op.root, op.gloss = root.name, key
                livery_index = liveries_module().load_index(root)
                lbox = box.box()
                current_livery = root.get("ans_garage_livery", "None")
                label_now = next((l["Label"] for l in (livery_index or {}).get("Liveries", []) if l["Key"] == current_livery), "None")
                wrapped(lbox, context, "Livery: " + label_now, icon="IMAGE_DATA")
                if livery_index:
                    row = lbox.row(align=True)
                    op = row.operator("object.ans_garage_livery", text="Choose livery…", icon="VIEWZOOM")
                    op.root = root.name
                    op = row.operator("object.ans_garage_livery", text="None", depress=current_livery == "None")
                    op.root, op.livery, op.pick = root.name, "None", False
                    car = liveries_module().livery_car(root, current_livery) if current_livery != "None" else None
                    if car:
                        text = "Use its paint" + (" and plate text (%s)" % car["PlateText"] if car.get("PlateText") else "")
                        lbox.operator("object.ans_garage_livery_car", text=text, icon="BRUSH_DATA").root = root.name
                else:
                    wrapped(lbox, context, "None exported with this car. Frosty: Tools > An's Garage > Add liveries to an existing export…")
                current = json.loads(root.get("ans_garage_tire_json") or '{"Name": "Stock", "Lettering": "Plain"}')
                tires = box.box()
                wrapped(tires, context, "Tires: %s%s" % (current["Name"], ", brand lettering" if current["Name"] != "Stock"
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
                rims = box.box()
                current_rim = root.get("ans_garage_rim", "Stock")
                wrapped(rims, context, "Rims: " + ("Stock (factory wheel set above)" if current_rim == "Stock" else current_rim),
                        icon="MESH_CIRCLE")
                if library_index("rim", library_folder(context, "rim")) is None:
                    rims.operator("import_scene.ans_garage_locate_rims", text="Locate rim library…")
                else:
                    row = rims.row(align=True)
                    row.operator("object.ans_garage_rim", text="Choose rim…", icon="VIEWZOOM").root = root.name
                    op = row.operator("object.ans_garage_rim", text="Stock", depress=current_rim == "Stock")
                    op.root, op.rim, op.pick = root.name, "Stock", False
                paint_rows = rims_module().rim_paint(root)
                if paint_rows:
                    grid = rims.grid_flow(columns=2, align=True)
                    for label, socket in paint_rows:
                        grid.prop(socket, "default_value", text=label)
                    rims.operator("object.ans_garage_rim_paint_stock", text="Stock rim colors").root = root.name
                plates = box.box()
                folder = plate_library(context)
                pindex = plate_index(folder) if folder else None
                current_plate = root.get("ans_garage_plate", "Stock")
                wrapped(plates, context, "License plate: " + plate_label(pindex, current_plate), icon="TEXTURE")
                text = root.get("ans_garage_plate_text", "")
                op = plates.operator("object.ans_garage_plate_text", text="Plate text: " + (text or "(blank)") + "…")
                op.root = root.name
                if pindex is None:
                    plates.operator("import_scene.ans_garage_locate_plates", text="Locate license plate library…")
                else:
                    row = plates.row(align=True)
                    op = row.operator("object.ans_garage_plate", text="Choose plate…", icon="VIEWZOOM")
                    op.root = root.name
                    op = row.operator("object.ans_garage_plate", text="Stock", depress=current_plate == "Stock")
                    op.root, op.plate = root.name, "Stock"
                moving = box.box()
                obj, controls = animation_module().controls(root)
                if obj is not None and controls:
                    wrapped(moving, context, "Moving parts: 0 closed, 1 open", icon="ARMATURE_DATA")
                    moving.operator("object.ans_garage_close_moving_parts", text="Close all").root = root.name
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
                    wrapped(moving, context, "Moving parts: none in this car's data", icon="ARMATURE_DATA")
                else:
                    if root.get("ans_garage_static_export"):
                        wrapped(moving, context, "Exported as a static model", icon="ARMATURE_DATA")
                    moving.operator("object.ans_garage_moving_parts", icon="ARMATURE_DATA").root = root.name
                wrapped(box, context, "Limits: see the An's Garage assembly report in the Text Editor")
            obj = context.active_object
            if obj and obj.get("unbound_materials_path"):
                box = self.layout.box()
                wrapped(box, context, "Original material slots restored")
                material = obj.active_material
                built = material and material.get("unbound_surface_profile")
                wrapped(box, context, str(material.get("unbound_status", "")) if built else "Surface shader is unresolved")

    def menu(self, context):
        self.layout.operator(IMPORT_SCENE_OT_ans_garage_vehicle.bl_idname, text="An's Garage vehicle (.json)")

    global _registered_classes, _menu
    _registered_classes = [AnsGaragePreferences, IMPORT_SCENE_OT_ans_garage_locate_tires, OBJECT_OT_ans_garage_tire,
                           IMPORT_SCENE_OT_ans_garage_locate_plates, OBJECT_OT_ans_garage_plate, OBJECT_OT_ans_garage_plate_text,
                           IMPORT_SCENE_OT_ans_garage_locate_rims, OBJECT_OT_ans_garage_rim, OBJECT_OT_ans_garage_rim_paint_stock,
                           OBJECT_OT_ans_garage_moving_parts, OBJECT_OT_ans_garage_close_moving_parts,
                           OBJECT_OT_ans_garage_conditions, OBJECT_OT_ans_garage_finish, OBJECT_OT_ans_garage_material,
                           OBJECT_OT_ans_garage_color_shift, OBJECT_OT_ans_garage_gloss,
                           OBJECT_OT_ans_garage_livery, OBJECT_OT_ans_garage_livery_car,
                           IMPORT_SCENE_OT_ans_garage_vehicle, WM_OT_ans_garage_cancel_import,
                           OBJECT_OT_ans_garage_build_materials, IMPORT_SCENE_OT_ans_garage_locate_export,
                           IMPORT_SCENE_OT_ans_garage_locate_shader_defaults,
                           OBJECT_OT_ans_garage_variant, OBJECT_OT_ans_garage_preset,
                           VIEW3D_PT_ans_garage_vehicle]
    _menu = menu
    for cls in _registered_classes:
        bpy.utils.register_class(cls)

    def condition_update(scene, context):
        surfaces_module().profiles_module().show_conditions(scene)
    for label, prop, _ in surfaces_module().profiles_module().CONDITIONS.values():
        setattr(bpy.types.Scene, prop, FloatProperty(name=label, min=0.0, max=1.0, subtype="FACTOR", update=condition_update,
                                                     description="0 clean and dry (can be keyframed)"))
    bpy.types.TOPBAR_MT_file_import.append(_menu)
    bpy.types.STATUSBAR_HT_header.prepend(draw_status)


def unregister():
    import bpy
    bpy.types.TOPBAR_MT_file_import.remove(_menu)
    bpy.types.STATUSBAR_HT_header.remove(draw_status)
    for cls in reversed(_registered_classes):
        bpy.utils.unregister_class(cls)
    for _, prop, _ in surfaces_module().profiles_module().CONDITIONS.values():
        delattr(bpy.types.Scene, prop)


if __name__ == "__main__":
    register()
