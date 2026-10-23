"""An's Garage for Blender: imports vehicles exported by An's Garage for Frosty.

Imports the manifest's exported FBX files without recentering or applying transforms.
Source slots are restored, then surfaces are built from compiled source-shader profiles
(static state) before vehicle assembly. Shaders without a resolved profile stay unconnected and are reported.
"""
bl_info = {"name": "An's Garage for Blender", "author": "An Vu", "version": (1, 1, 3), "blender": (4, 1, 0),
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


_VISIBLE = {}


def visible_surfaces(context, root=None, ttl=2.0):
    """(visible material slots, built ones) over the visible assembled meshes of a car (or the scene); cached for
    `ttl` seconds."""
    import numpy as np
    key = root.name if root is not None else ""
    if key in _VISIBLE and time.time() - _VISIBLE[key][0] < ttl:
        return _VISIBLE[key][1]
    shown = built = 0
    for o in (root.all_objects if root is not None else context.scene.objects):
        if o.type != "MESH" or not o.get("unbound_mesh_id") or not o.material_slots or not o.visible_get():
            continue
        idx = np.empty(len(o.data.polygons), np.int32)
        o.data.polygons.foreach_get("material_index", idx)
        for i in np.unique(idx):
            if i < len(o.material_slots):
                shown += 1
                m = o.material_slots[i].material
                built += bool(m and m.get("unbound_surface_profile"))
    _VISIBLE[key] = (time.time(), (shown, built))
    return shown, built


LIBRARY_FILES = {"tire": "tires.json", "rim": "rims.json", "plate": "plates.json"}
_SHARED_SCAN = {}


def shared_parts(folder, reload=False):
    """{kind: library folder} found in a shared parts folder: the folder itself or one of its subfolders (Frosty's
    Export shared parts (tires, rims, plates)... writes AnsGarage_TireLibrary, AnsGarage_RimLibrary and AnsGarage_PlateLibrary there).
    Looked up again after a few seconds, so a library exported meanwhile shows up."""
    import bpy
    cached = _SHARED_SCAN.get(folder)
    if cached and not reload and time.time() - cached[0] < 5.0:
        return cached[1]
    found = {}
    try:
        root = Path(bpy.path.abspath(folder))
        subfolders = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: (not d.name.startswith("AnsGarage_"), d.name))
        candidates = [root] + subfolders
    except OSError:
        candidates = []
    for kind, name in LIBRARY_FILES.items():
        hit = next((d for d in candidates if (d / name).is_file()), None)
        if hit is not None:
            found[kind] = str(hit)
    _SHARED_SCAN[folder] = (time.time(), found)
    return found


def library_folder(context, kind):
    """A library's folder, found in the shared parts folder (add-on preference, else the scene's); "" if none."""
    addon = context.preferences.addons.get(__name__)
    prefs = getattr(addon, "preferences", None) if addon else None
    for shared in (getattr(prefs, "shared_parts", ""), context.scene.get("ans_garage_shared_parts", "")):
        if shared and kind in shared_parts(shared):
            return shared_parts(shared)[kind]
    return ""


def library_status(folder):
    """Rows (label, count text or None when missing) of the libraries found in a shared parts folder."""
    found = shared_parts(folder)
    index = {kind: library_index(kind, found[kind]) if kind in found else None for kind in LIBRARY_FILES}
    count = lambda kind, key, unit: ("%d %s" % (len(index[kind][key]), unit)) if index[kind] and index[kind].get(key) else None
    return [("Tires", count("tire", "Tires", "tires")), ("Rims", count("rim", "Rims", "rims")),
            ("License plates", count("plate", "Plates", "plates")), ("Plate frames", count("plate", "Frames", "frames"))]


def draw_library_status(layout, folder):
    """The checklist of shared parts found in `folder`."""
    rows = library_status(folder)
    col = layout.column(align=True)
    for label, found in rows:
        col.label(text="%s: %s" % (label, found or "not found"), icon="CHECKMARK" if found else "X")
    if not all(found for _, found in rows):
        layout.label(text="Missing ones: Frosty > Tools > An's Garage > Export shared parts (tires, rims, plates)...", icon="INFO")


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


def plate_label(index, key, root=None):
    if key == "Stock":
        plate = plates_module().stock_plate(root, index) if root is not None and index else None
        return "Stock (%s)" % plate["Label"] if plate else "Stock (the car's placeholder)"
    if not index:
        return key
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


class CarReport:
    """The one readable report of a car ("An's Garage report: <car>" in the Text Editor): sections of plain lines."""
    ORDER = ("Import", "Materials", "Assembly", "Moving parts", "License plate", "How the car was built")

    def __init__(self, title):
        self.title, self.sections, self.slots = title, {}, {}

    def add(self, section, *lines):
        self.sections.setdefault(section, []).extend(lines)

    def materials(self, report):
        """Record a build pass: a later pass (the wheels, after assembly) replaces what an earlier one said about a slot."""
        for b in report["Built"]:
            self.slots[(b["Object"], b["Slot"])] = None
        for u in report["Unsupported"] + report["Issues"]:
            self.slots[(u.get("Object", "?"), u.get("Slot", "?"))] = (u.get("Reason") or u.get("Issue") or "unknown reason")[:240]

    def _material_lines(self):
        from collections import defaultdict
        groups = defaultdict(list)
        for (obj, slot), reason in self.slots.items():
            if reason:
                groups[reason].append("%s (slot %s)" % (obj, slot))
        bad = sum(len(v) for v in groups.values())
        lines = ["%d of %d material slots built (every part option, hidden ones too)" % (len(self.slots) - bad, len(self.slots))]
        for reason, where in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            lines += ["  %d not built: %s" % (len(where), reason),
                      "    " + ", ".join(where[:6]) + (", ..." if len(where) > 6 else "")]
        return lines

    def assembly(self, root):
        """Issues and unused source parts from the assembly, then the standing notes on the method."""
        notes = assembly_module().STANDING_NOTES
        lines = [l for l in json.loads(root.get("diagnostics_json") or "[]") if l not in notes]
        unused = [l.split(": ", 1)[-1].rsplit("/", 1)[-1].removesuffix("_mesh")
                  for l in lines if l.startswith("No selected blueprint/item placement")]
        issues = [l for l in lines if not l.startswith("No selected blueprint/item placement")]
        self.add("Assembly", "%d issue%s" % (len(issues), "" if len(issues) == 1 else "s"), *["  " + l for l in issues])
        if unused:
            self.add("Assembly", "%d source parts not used by any option (kept hidden in 'Unassigned source parts'):" % len(unused),
                     *["  " + u for u in unused])
        self.add("How the car was built", *notes)

    def write(self, root=None):
        import bpy
        import datetime
        text = bpy.data.texts.new("An's Garage report: " + self.title)
        out = ["An's Garage report: " + self.title,
               "Imported %s with An's Garage %s" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
                                                   ".".join(map(str, bl_info["version"])))]
        if self.slots:
            self.sections["Materials"] = self.sections.get("Materials", []) + self._material_lines()
        for name in self.ORDER:
            if self.sections.get(name):
                out += ["", name.upper()] + self.sections[name]
        text.write("\n".join(out) + "\n")
        if root is not None:
            root["ans_garage_report"] = text.name
        return text


def add_moving_parts(root, report=None):
    """Sliders for the car's moving parts (doors, windows, hood, boot, active aero): lines for the car's report."""
    try:
        result = animation_module().build(root)
        lines = ["%d sliders: %s" % (len(result["Controls"]), ", ".join(c["Label"] for c in result["Controls"]))]
        lines += ["  " + x for x in result["Issues"]]
    except Exception as exc:
        lines = ["Not built: " + str(exc)]
    if report is not None:
        report.add("Moving parts", *lines)
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
            c.matrix_basis = local @ assembly_module().world_matrix(s)
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
    report = CarReport(vehicle_label(str(path)))
    report.add("Import", "%d of %d meshes imported from %s" % (count, len(records), path.parent.name),
               *["  " + f for f in failures])
    if materials and path.with_name("materials.json").is_file():
        try:
            material_report = yield from _scaled(materials_module().reconstruct_steps(path, imported_objects),
                                                 "Restoring material slots", 20.0, 25.0)
            assignment = ["Materials: " + x["Issue"] for x in material_report["Issues"]
                          if x.get("Severity") == "assignment_failed"]
            failures.extend(assignment)
            if assignment:
                report.add("Materials", "Material slots not restored:", *["  " + a for a in assignment])
            surface_report = yield from _scaled(surfaces_module().surface_steps(imported_objects, path),
                                                "Building materials", 25.0, 75.0)
            report.materials(surface_report)
        except Exception as exc:
            failures.append("Materials: " + str(exc))
            report.add("Materials", "Not built: " + str(exc))
    if assemble and path.with_name("assembly.json").is_file() and not failures:
        try:
            yield "Assembling the vehicle", 75.0, 0, 1
            root, _ = assembly_module().assemble_existing(path)
        except Exception as exc:
            failures.append("Assembly: " + str(exc))
            report.add("Assembly", "Not assembled: " + str(exc))
        else:
            if manifest.get("MovingParts", True):
                yield "Adding moving parts", 78.0, 0, 1
                add_moving_parts(root, report)
            else:
                root["ans_garage_static_export"] = True
                report.add("Moving parts", "Not built: exported as a static model (Add moving parts builds them)")
            if materials and path.with_name("materials.json").is_file():
                # Per-wheel inputs (front/rear selectors) exist only on assembled wheel parts.
                surface_report = yield from _scaled(surfaces_module().surface_steps(None, path),
                                                    "Building per-wheel materials", 80.0, 100.0)
                report.materials(surface_report)
                # The plate the game shows (Lakeshore, no frame, "NFS" on every car checked), not the mesh's placeholder.
                folder = plate_library(bpy.context)
                if folder and plate_index(folder):
                    try:
                        yield "License plate", 99.0, 0, 1
                        report.add("License plate", plates_module().apply_game_stock(root, folder, default_plate_frame()))
                    except Exception as exc:
                        report.add("License plate", "Kept the car's placeholder: %s" % exc)
                else:
                    report.add("License plate", "The car's placeholder: no shared parts folder set at import")
            report.assembly(root)
    report.write(root if "root" in locals() else None)
    materials_module().FBX_TREES.clear()
    yield "Finishing", 100.0, 1, 1
    return count, failures


def default_plate_frame():
    """The plate frame new imports get (add-on preference): "Stock" (as the game) unless set and the plate library has
    frames."""
    import bpy
    addon = bpy.context.preferences.addons.get(__name__)
    key = getattr(getattr(addon, "preferences", None), "plate_frame", "Stock") if addon else "Stock"
    folder = plate_library(bpy.context)
    index = plate_index(folder) if folder else None
    return key if index and any(f["Key"] == key for f in index.get("Frames", [])) else "Stock"


def wrap_lines(context, text, icon=False, reserve=0):
    """`text` split into lines that fit the sidebar, measured with the interface font."""
    import blf
    system = context.preferences.system
    # Blender's interface scale as the UI draws it (dpi already includes Resolution Scale and the screen's scaling).
    scale = getattr(system, "dpi", 72) / 72.0
    # Panel and up to three nested boxes on each side, plus the icon.
    room = context.region.width - (76 + (22 if icon else 0) + reserve) * scale
    try:
        blf.size(0, context.preferences.ui_styles[0].widget.points * scale)
        width = lambda t: blf.dimensions(0, t)[0] * 1.04
    except Exception:
        width = lambda t: len(t) * 7.0 * scale
    lines, line = [], ""
    for word in text.split():
        candidate = (line + " " + word).strip()
        if line and width(candidate) > room:
            lines.append(line)
            line = word
        else:
            line = candidate
    return lines + [line] if line or not lines else lines


def wrapped(layout, context, text, icon="NONE", reserve=0):
    """A label that wraps to the sidebar's width instead of being cut off with "..."."""
    col = layout.column(align=True)
    for i, line in enumerate(wrap_lines(context, text, icon != "NONE", reserve)):
        col.label(text=line, icon=icon if i == 0 else ("BLANK1" if icon != "NONE" else "NONE"))


def car_notes(context, root):
    """[(key, icon, text)] of what the add-on has to tell about a car (shown together at the end of its section). The key
    changes with the content, so a hidden note comes back when its numbers change."""
    notes = []
    shown, built = visible_surfaces(context, root)
    if built < shown:
        notes.append(("surfaces:%d" % (shown - built), "ERROR", "%d of %d visible surfaces not built (the An's Garage "
                      "report in the Text Editor says why)" % (shown - built, shown)))
    issues, unused = assembly_module().findings(root)
    if issues or unused:
        found = ["%d issue%s" % (issues, "" if issues == 1 else "s")] if issues else []
        found += ["%d source part%s not used by any option" % (unused, "" if unused == 1 else "s")] if unused else []
        notes.append(("assembly:%d:%d" % (issues, unused), "INFO",
                      "%s (listed in the An's Garage report in the Text Editor)" % " and ".join(found)))
    if not any(library_folder(context, kind) for kind in LIBRARY_FILES):
        notes.append(("shared-parts", "INFO", "No shared parts folder yet: tires, rims, plates and frames come from it, and "
                      "the plate shows the car's placeholder until then (Set shared parts folder…)"))
    if not liveries_module().load_index(root):
        notes.append(("liveries", "INFO", "No liveries exported with this car (Frosty: Tools > An's Garage > Add liveries "
                      "to an existing export…)"))
    hidden = set(json.loads(root.get("ans_garage_hidden_notes") or "[]"))
    return [n for n in notes if n[0] not in hidden]


def preset_text(value):
    value = value.rsplit("_template_", 1)[-1].replace("_", " ")
    return re.sub(r"\bSet([A-Za-z]+)\b", lambda m: "Set " + m.group(1).upper(), value)


_GREETING = []


def greeting():
    """The line under the panel's title: one from greetings.txt, picked when the add-on is turned on."""
    if not _GREETING:
        import random
        try:
            lines = [l.strip() for l in Path(__file__).with_name("greetings.txt").read_text(encoding="utf-8").splitlines()]
        except OSError:
            lines = []
        _GREETING.append(random.choice([l for l in lines if l] or ["Welcome to An's Garage"]))
    return _GREETING[0]


def front_to_back(groups):
    """Part groups ordered from the front of the car to the back (Blender -Y is the front), by the centre of each
    group's parts; cached per group."""
    from mathutils import Vector
    for g in groups:
        if g.name not in _GROUP_ORDER:
            ys = [(assembly_module().world_matrix(o) @ Vector(c)).y
                  for o in g.all_objects if o.type == "MESH" for c in o.bound_box]
            _GROUP_ORDER[g.name] = sum(ys) / len(ys) if ys else 0.0
    return sorted(groups, key=lambda g: _GROUP_ORDER[g.name])


_GROUP_ORDER = {}


def section(layout, root, key, default_closed=True):
    """A Blender sub-panel of a car (open state kept per car in the sidebar, saved with the file): (header, body or
    None when closed)."""
    import hashlib
    car = hashlib.md5(root.name.encode("utf-8")).hexdigest()[:10]
    return layout.panel("ans_garage_%s_%s" % (car, key), default_closed=default_closed)


def menu_field(layout, name, menu, text, root, group=None):
    """A "Name | value ▾" row whose dropdown is `menu`, told which car (and part group) it is for."""
    row = field(layout, name)
    row.context_pointer_set("ans_garage_root", root)
    if group is not None:
        row.context_pointer_set("ans_garage_group", group)
    row.menu(menu, text=text)


def field(layout, name):
    """A "Name | value" row laid out like Blender's own properties: the returned row holds the value."""
    split = layout.split(factor=0.4, align=True)
    left = split.row()
    left.alignment = "RIGHT"
    left.label(text=name)
    return split.row(align=True)


_NAMES = {}


def car_name(context, root):
    """The car's in-game name that fits the sidebar header: long, medium, else short."""
    path = root.get("unbound_assembly_path", "")
    if path not in _NAMES:
        try:
            names = json.loads(Path(path).read_text(encoding="utf-8-sig")).get("VehicleName") or {}
        except (OSError, ValueError):
            names = {}
        _NAMES[path] = [n for n in (names.get("Long"), names.get("Medium"), names.get("Short")) if n] or [root.name]
    for name in _NAMES[path]:
        if not context.region or len(wrap_lines(context, name, True)) == 1:
            return name
    return _NAMES[path][-1]


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
    _GREETING.clear()
    from bpy_extras.io_utils import ImportHelper
    from bpy.props import BoolProperty, EnumProperty, FloatProperty, StringProperty

    class IMPORT_SCENE_OT_ans_garage_vehicle(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.ans_garage_vehicle"
        bl_label = "An's Garage vehicle"
        bl_description = "Import a car exported by An's Garage for Frosty: pick the manifest.json in its export folder"
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
        shared_parts: StringProperty(name="Shared parts folder", subtype="DIR_PATH",
                                     description="The folder Frosty's Tools > An's Garage > Export shared parts (tires, rims, plates)... wrote to; "
                                                 "the tire, rim and plate libraries in it are found by themselves")
        plate_frame: EnumProperty(name="Plate frame for new imports", default="Stock",
                                  items=(("Stock", "Stock (as the game)", "The frame the game shows on the car: none on every car checked"),
                                         ("simple", "Simple", "The game's plain black frame"),
                                         ("none", "None", "No frame")))

        def draw(self, context):
            box = self.layout.box()
            box.prop(self, "shared_parts")
            if self.shared_parts:
                draw_library_status(box, self.shared_parts)
            else:
                box.label(text="Export them once in Frosty (Tools > An's Garage > Export shared parts (tires, rims, plates)...), then pick that folder.")
            self.layout.prop(self, "plate_frame")

    class WM_OT_ans_garage_shared_parts(bpy.types.Operator):
        bl_idname = "wm.ans_garage_shared_parts"
        bl_label = "Set shared parts folder"
        bl_description = ("Pick the folder that Frosty's Tools > An's Garage > Export shared parts (tires, rims, plates)... wrote to. The tire, rim "
                          "and plate libraries in it are found by themselves (also saved in the add-on's preferences)")
        directory: StringProperty(subtype="DIR_PATH")
        filter_folder: BoolProperty(default=True, options={"HIDDEN", "SKIP_SAVE"})

        def invoke(self, context, event):
            context.window_manager.fileselect_add(self)
            return {"RUNNING_MODAL"}

        def execute(self, context):
            found = shared_parts(self.directory, reload=True)
            if not found:
                self.report({"ERROR"}, "No tire, rim or plate library in %s (Frosty: Tools > An's Garage > Export shared parts (tires, rims, plates)...)"
                            % self.directory)
                return {"CANCELLED"}
            context.scene["ans_garage_shared_parts"] = self.directory
            addon = context.preferences.addons.get(__name__)
            if addon and getattr(addon, "preferences", None) is not None:
                addon.preferences.shared_parts = self.directory
            self.report({"INFO"}, "Found: " + ", ".join(label for label, ok in library_status(self.directory) if ok))
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
                self.report({"ERROR"}, "Set the shared parts folder first (the tire library is in it)")
                return {"CANCELLED"}
            try:
                notes = tires_module().apply_tire(root, self.tire, self.lettering, folder)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            if notes:
                self.report({"WARNING"}, "; ".join(notes))
            return {"FINISHED"}

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
        axle: EnumProperty(items=(("Both", "Both axles", ""), ("Front", "Front rims", ""), ("Rear", "Rear rims", "")),
                           name="Axle", options={"SKIP_SAVE"})
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
                self.report({"ERROR"}, "Set the shared parts folder first (the rim library is in it)")
                return {"CANCELLED"}
            try:
                notes = rims_module().apply_rim(root, self.rim, folder, self.axle)
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
        items = [("Stock", "Stock (as the game)", "The plate the game shows on this car (Lakeshore on every car checked)")]
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
                self.report({"ERROR"}, "Set the shared parts folder first (the license plate library is in it)")
                return {"CANCELLED"}
            try:
                count = plates_module().apply_plate(root, self.plate, folder)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
            self.report({"INFO"}, "%s on %d plates" % (plate_label(plate_index(folder), self.plate, root), count))
            return {"FINISHED"}

    _FRAME_ITEMS = []

    def frame_items(self, context):
        index = plate_index(plate_library(context)) if context else None
        items = [("Stock", "Stock (as the game)", "The frame the game shows on this car (none on every car checked)")]
        for f in (index or {}).get("Frames", []):
            items.append((f["Key"], f["Label"], f["Group"]))
        _FRAME_ITEMS[:] = items
        return _FRAME_ITEMS

    class OBJECT_OT_ans_garage_plate_frame(bpy.types.Operator):
        bl_idname = "object.ans_garage_plate_frame"
        bl_label = "Choose plate frame"
        bl_description = "Search the license plate frames (type to filter, e.g. simple or illest)"
        bl_options = {"REGISTER", "UNDO"}
        bl_property = "frame"
        root: StringProperty(options={"SKIP_SAVE"})
        frame: bpy.props.EnumProperty(items=frame_items, name="Frame")
        pick: BoolProperty(default=True, options={"SKIP_SAVE"})

        def invoke(self, context, event):
            if not self.pick:
                return self.execute(context)
            context.window_manager.invoke_search_popup(self)
            return {"RUNNING_MODAL"}

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            folder = plate_library(context)
            if root is None or (self.frame != "Stock" and not folder):
                self.report({"ERROR"}, "Set the shared parts folder first (the license plate library is in it)")
                return {"CANCELLED"}
            try:
                plates_module().apply_frame(root, self.frame, folder)
            except Exception as exc:
                self.report({"ERROR"}, str(exc))
                return {"CANCELLED"}
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
            lines = add_moving_parts(root)
            text = bpy.data.texts.get(root.get("ans_garage_report", ""))
            if text is not None:
                text.write("\nMOVING PARTS (added later)\n" + "\n".join(lines) + "\n")
            self.report({"INFO"}, lines[0] if lines else "Done")
            return {"FINISHED"}

    class ANS_GARAGE_MT_part(bpy.types.Menu):
        """A part group's options (the row sets ans_garage_root and ans_garage_group)."""
        bl_idname = "ANS_GARAGE_MT_part"
        bl_label = "Part"

        def draw(self, context):
            root, group = getattr(context, "ans_garage_root", None), getattr(context, "ans_garage_group", None)
            if root is None or group is None:
                return
            self.layout.operator_context = "EXEC_DEFAULT"
            for v in group.children:
                if "unbound_option" in v:
                    text = "None" if v["unbound_option"] == "none" else v.get("unbound_label") or v.name
                    op = self.layout.operator("object.ans_garage_variant", text=text)
                    op.root, op.group, op.option = root.name, group["unbound_choice_group"], v["unbound_option"]

    class ANS_GARAGE_MT_preset(bpy.types.Menu):
        """The car's presets (the row sets ans_garage_root)."""
        bl_idname = "ANS_GARAGE_MT_preset"
        bl_label = "Preset"

        def draw(self, context):
            root = getattr(context, "ans_garage_root", None)
            if root is None or not root.get("unbound_presets_json"):
                return
            self.layout.operator_context = "EXEC_DEFAULT"
            for name in json.loads(root["unbound_presets_json"]):
                op = self.layout.operator("object.ans_garage_preset", text=preset_text(name))
                op.root, op.preset = root.name, name

    class ANS_GARAGE_MT_tire(bpy.types.Menu):
        """Stock and the tire library's tires (the row sets ans_garage_root)."""
        bl_idname = "ANS_GARAGE_MT_tire"
        bl_label = "Tires"

        def draw(self, context):
            root = getattr(context, "ans_garage_root", None)
            folder = tire_library(context)
            index = tire_index(folder) if folder else None
            if root is None:
                return
            current = json.loads(root.get("ans_garage_tire_json") or '{"Lettering": "Plain"}')
            self.layout.operator_context = "EXEC_DEFAULT"
            for name in ["Stock"] + (tires_module().tire_names(index) if index else []):
                op = self.layout.operator("object.ans_garage_tire", text="Stock (car's own)" if name == "Stock" else name)
                op.root, op.tire, op.lettering = root.name, name, current.get("Lettering", "Plain")

    class OBJECT_OT_ans_garage_hide_note(bpy.types.Operator):
        bl_idname = "object.ans_garage_hide_note"
        bl_label = "Hide note"
        bl_description = "Hide this note (it comes back if what it says changes)"
        bl_options = {"INTERNAL", "UNDO"}
        root: StringProperty(options={"SKIP_SAVE"})
        key: StringProperty(options={"SKIP_SAVE"})

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            if root is None:
                return {"CANCELLED"}
            hidden = json.loads(root.get("ans_garage_hidden_notes") or "[]")
            if self.key not in hidden:
                root["ans_garage_hidden_notes"] = json.dumps(hidden + [self.key])
            return {"FINISHED"}

    class OBJECT_OT_ans_garage_close_moving_parts(bpy.types.Operator):
        bl_idname = "object.ans_garage_close_moving_parts"
        bl_label = "Close all"
        bl_description = "Close every moving part of this car (all sliders to 0)"
        bl_options = {"REGISTER", "UNDO"}
        root: StringProperty(options={"SKIP_SAVE"})
        value: FloatProperty(default=0.0, options={"SKIP_SAVE"})

        def execute(self, context):
            root = bpy.data.collections.get(self.root)
            obj, controls = animation_module().controls(root) if root else (None, [])
            for c in controls:
                if c["Key"] in obj:
                    obj[c["Key"]] = self.value
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

    def value_menu(idname, label, operator, prop, items):
        """A menu that runs `operator` with `prop` set to each of `items` ((value, text, ...)) for the row's car."""
        def draw(self, context):
            root = getattr(context, "ans_garage_root", None)
            if root is None:
                return
            self.layout.operator_context = "EXEC_DEFAULT"  # run directly, not through the search popup
            for item in items:
                op = self.layout.operator(operator, text=item[1])
                op.root = root.name
                setattr(op, prop, item[0])
        return type(idname, (bpy.types.Menu,), {"bl_idname": idname, "bl_label": label, "draw": draw})

    ANS_GARAGE_MT_finish = value_menu("ANS_GARAGE_MT_finish", "Finish", "object.ans_garage_finish", "finish", finish_items)
    ANS_GARAGE_MT_material = value_menu("ANS_GARAGE_MT_material", "Material", "object.ans_garage_material", "material",
                                        material_items)
    ANS_GARAGE_MT_shift = value_menu("ANS_GARAGE_MT_shift", "Color shift", "object.ans_garage_color_shift", "shift", shift_items)
    ANS_GARAGE_MT_gloss = value_menu("ANS_GARAGE_MT_gloss", "Gloss", "object.ans_garage_gloss", "gloss",
                                     [("Stock", "Stock")] + [(str(k), l) for k, l in profiles.GLOSS_LEVELS])

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
        gloss: EnumProperty(name="Gloss", options={"SKIP_SAVE"},
                            items=[("Stock", "Stock", "The car's own")] + [(str(k), l, "") for k, l in profiles.GLOSS_LEVELS])

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
        bl_description = ("Turn the game's dirt, dust and wet on or off for every car in the scene: on rebuilds the "
                          "surfaces that read them so the sliders can set them (heavier shaders); off goes back to clean and dry")
        bl_options = {"REGISTER", "UNDO"}
        enable: BoolProperty(options={"SKIP_SAVE"})

        def execute(self, context):
            if bpy.app.background or not context.window:
                count, built, failed = surfaces_module().set_conditions(self.enable)
                self.report({"WARNING" if failed else "INFO"}, "%d of %d surfaces rebuilt%s" % (
                    len(built), count, "" if not failed else "; %d not built" % len(failed)))
                return {"FINISHED"}
            if RUN:
                self.report({"ERROR"}, "Wait for the running import or rebuild to finish")
                return {"CANCELLED"}

            def steps():
                result = yield from _scaled(surfaces_module().set_conditions_steps(self.enable),
                                            "Rebuilding surfaces", 0.0, 100.0)
                return result
            RUN.update(steps=steps(), name="Dirt, dust and wet " + ("on" if self.enable else "off"), title="",
                       stage="Starting", pct=0.0, done=0, total=0, start=time.time(), cancel=False)
            self._timer = context.window_manager.event_timer_add(0.02, window=context.window)
            context.window_manager.modal_handler_add(self)
            return {"RUNNING_MODAL"}

        def modal(self, context, event):
            if event.type in {"Z", "Y"} and (event.ctrl or event.oskey):
                return {"RUNNING_MODAL"}  # no undo/redo while surfaces are being rebuilt
            if event.type != "TIMER":
                return {"PASS_THROUGH"}
            result = None
            deadline = time.perf_counter() + 0.15
            try:
                while time.perf_counter() < deadline:
                    RUN["stage"], RUN["pct"], RUN["done"], RUN["total"] = next(RUN["steps"])
            except StopIteration as stop:
                result = stop.value
            for area in context.screen.areas:
                if area.type in {"VIEW_3D", "STATUSBAR"}:
                    area.tag_redraw()
            if result is None:
                return {"PASS_THROUGH"}
            context.window_manager.event_timer_remove(self._timer)
            elapsed = time.time() - RUN["start"]
            RUN.clear()
            count, built, failed = result
            self.report({"WARNING" if failed else "INFO"}, "%d of %d visible surfaces rebuilt in %d:%02d%s" % (
                len(built), count, *divmod(int(elapsed), 60), "" if not failed else "; %d not built" % len(failed)))
            return {"FINISHED"}

    class OBJECT_OT_ans_garage_catch_up(bpy.types.Operator):
        bl_idname = "object.ans_garage_catch_up"
        bl_label = "Update shown parts"
        bl_description = ("Rebuild parts you showed yourself (e.g. in the Outliner) that still have the old dirt, dust "
                          "and wet setting; parts switched in this sidebar update by themselves")
        bl_options = {"REGISTER", "UNDO"}

        def execute(self, context):
            count = surfaces_module().catch_up()
            self.report({"INFO"}, "%d surfaces updated" % count if count else "Every shown part is up to date")
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
        bl_description = ("Build every material that isn't built yet from the game's compiled shaders (e.g. after "
                          "updating the add-on). Materials already built, and your own node edits, are kept")
        bl_options = {"REGISTER", "UNDO"}
        def execute(self, context):
            result = surfaces_module().apply_supported_surfaces()
            self.report({"WARNING" if result["Issues"] else "INFO"},
                "%d slots built, %d already built, %d unsupported, %d issues" %
                tuple(len(result[k]) for k in ("Built", "AlreadyBuilt", "Unsupported", "Issues")))
            return {"FINISHED"}

    class IMPORT_SCENE_OT_ans_garage_locate_export(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.ans_garage_locate_export"
        bl_label = "Locate export manifest"
        bl_description = ("The car's export folder moved: choose its manifest.json (or materials.json) so the add-on "
                          "finds the textures again, then build the materials")
        bl_options = {"REGISTER", "UNDO"}
        filename_ext = ".json"
        filter_glob: StringProperty(default="*.json", options={"HIDDEN"})
        def execute(self, context):
            result = surfaces_module().apply_supported_surfaces(export_path=self.filepath)
            self.report({"WARNING" if result["Issues"] else "INFO"},
                "%d slots built; %d not built" %
                (len(result["Built"]), len(result["Issues"])))
            return {"FINISHED"}

    class IMPORT_SCENE_OT_ans_garage_locate_shader_defaults(bpy.types.Operator, ImportHelper):
        bl_idname = "import_scene.ans_garage_locate_shader_defaults"
        bl_label = "Locate shader default textures"
        bl_description = ("The shared shader-defaults folder (textures all cars use) moved or is missing: choose its "
                          "textures.json, then build the materials")
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
                "%d slots built; %d not built" % (len(result["Built"]), len(result["Issues"])))
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
                root = bpy.data.collections[self.root]
                assembly_module().set_variant(root, self.group, self.option)
                surfaces_module().catch_up(root.all_objects)
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
                root = bpy.data.collections[self.root]
                assembly_module().apply_preset(root, self.preset)
                surfaces_module().catch_up(root.all_objects)
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
            self.draw_cars(context)
            header, tools = self.layout.panel("ans_garage_tools", default_closed=True)
            header.label(text="Tools")
            if tools:
                for idname, text in (("object.ans_garage_build_materials", "Build missing materials"),
                                     ("import_scene.ans_garage_locate_export", "Find moved car folder…"),
                                     ("import_scene.ans_garage_locate_shader_defaults", "Find moved shared textures…"),
                                     ("object.ans_garage_catch_up", "Refresh dirt on unhidden parts")):
                    tools.operator(idname, text=text)

        def draw_cars(self, context):
            cars =[r for r in context.scene.collection.children if r.get("unbound_assembly_path")]
            if not RUN:
                wrapped(self.layout, context, greeting())
                self.layout.operator("import_scene.ans_garage_vehicle", text="Import car…", icon="IMPORT")
            if RUN:
                run = self.layout.box()
                wrapped(run, context, RUN.get("title", "Importing ") + RUN["name"], icon="IMPORT")
                text = "%d%%" % RUN["pct"]
                run.progress(factor=RUN["pct"] / 100.0, type="BAR", text=text)
                run.label(text=RUN["stage"] + ("  %d / %d" % (RUN["done"], RUN["total"]) if RUN["total"] > 1 else ""))
                run.label(text="Elapsed %d:%02d" % divmod(int(time.time() - RUN["start"]), 60))
                wrapped(run, context, "Leave the scene alone until it finishes", icon="INFO")
                if "title" not in RUN:  # an import; a surface rebuild runs to the end
                    run.operator("wm.ans_garage_cancel_import", text="Cancel", icon="CANCEL")
            for root in cars:
                self.draw_car(context, root)

        def draw_car(self, context, root):
            header, car = section(self.layout, root, "car", default_closed=False)
            header.label(text=car_name(context, root), icon="AUTO")
            if car is None:
                return
            current = assembly_module().current_preset(root)
            menu_field(car, "Preset", "ANS_GARAGE_MT_preset", preset_text(current), root)
            groups = [g for g in root.children if g.get("unbound_choice_group")]
            wheel_sets = [g for g in groups if g["unbound_choice_group"] == "Rims"]

            def part_row(layout, group, name=None):
                key = group["unbound_choice_group"]
                shown = [v for v in group.children if "unbound_option" in v and not v.hide_viewport]
                text = ("None" if shown[0]["unbound_option"] == "none" else shown[0].get("unbound_label") or shown[0].name) \
                    if len(shown) == 1 else "Custom"
                menu_field(layout, name or group.get("unbound_label", key), "ANS_GARAGE_MT_part", text, root, group)

            header, body = section(car, root, "body")
            header.label(text="Body parts")
            if body:
                for group in front_to_back([g for g in groups if g not in wheel_sets]):
                    part_row(body, group)

            header, paint_panel = section(car, root, "paint")
            header.label(text="Paint and livery")
            if paint_panel:
                self.draw_paint(context, root, paint_panel)

            header, wheels = section(car, root, "wheels")
            header.label(text="Wheels")
            if wheels:
                for group in wheel_sets:
                    part_row(wheels, group, "Factory rims")
                self.draw_wheels(context, root, wheels)

            header, plates = section(car, root, "plate")
            header.label(text="License plate")
            if plates:
                self.draw_plate(context, root, plates)

            header, moving = section(car, root, "moving")
            header.label(text="Moving parts")
            if moving:
                self.draw_moving(context, root, moving)

            shown, built = visible_surfaces(context, root)
            header, materials = section(car, root, "materials")
            header.label(text=("Materials: all %d built" % shown) if built == shown else "Materials: %d of %d built" % (built, shown))
            if materials:
                part = context.active_object
                if part is not None and part.get("unbound_mesh_id") and part.name in root.all_objects:
                    material = part.active_material
                    where = part.users_collection[0].name if part.users_collection else part.name
                    field(materials, "Selected").label(text=where)
                    field(materials, "Material").label(text=re.sub(r"\.\d+$", "", material.name) if material else "None")
                    ok = bool(material and material.get("unbound_surface_profile"))
                    field(materials, "Built").label(text="From the game's shader" if ok else "No (see the report)",
                                                    icon="CHECKMARK" if ok else "ERROR")
                else:
                    wrapped(materials, context, "Select a part of the car to see its material.")

            if built:
                on = bool(context.scene.get("ans_garage_conditions"))
                header, conditions = section(car, root, "conditions")
                op = header.operator("object.ans_garage_conditions", text="", emboss=False,
                                     icon="CHECKBOX_HLT" if on else "CHECKBOX_DEHLT")
                op.enable = not on
                header.label(text="Dirt, dust and wet")
                if conditions:
                    col = conditions.column(align=True)
                    col.use_property_split = True
                    col.use_property_decorate = False
                    col.enabled = on
                    for slider_text, prop, _ in surfaces_module().profiles_module().CONDITIONS.values():
                        col.prop(context.scene, prop, text=slider_text, slider=True)

            notes = car_notes(context, root)
            if notes:
                col = car.column()
                for key, icon, text in notes:
                    row = col.row(align=False)
                    wrapped(row.column(), context, text, icon=icon, reserve=26)
                    op = row.operator("object.ans_garage_hide_note", text="", icon="X", emboss=False)
                    op.root, op.key = root.name, key

        def draw_paint(self, context, root, layout):
            scope = car_scope(root)
            paint = profiles.runtime_group(scope, "Ext_Carpaint_Diffuse")
            if paint:
                col = layout.column()
                col.use_property_split = True
                col.use_property_decorate = False
                col.prop(profiles.runtime_rgb(paint), "default_value", text="Color")
                now, stock = profiles.finish_value(scope)
                if now:
                    preset = "Stock" if now == stock else profiles.finish_preset(scope) or "Custom"
                    menu_field(layout, "Finish", "ANS_GARAGE_MT_finish", preset, root)
                    for menu, title, table, i in (("ANS_GARAGE_MT_material", "Material", profiles.FINISHES, 0),
                                                  ("ANS_GARAGE_MT_shift", "Color shift", profiles.COLOR_SHIFTS, 1)):
                        text = dict(table).get(now[i], "Type %d" % now[i]) + (" (stock)" if now[i] == stock[i] else "")
                        menu_field(layout, title, menu, text, root)
                    # Levels 2 and up render the same (no clear coat): shown as Matte.
                    gloss = dict(profiles.GLOSS_LEVELS).get(min(now[2], 2), "Matte") + (" (stock)" if now[2] == stock[2] else "")
                    menu_field(layout, "Gloss", "ANS_GARAGE_MT_gloss", gloss, root)
            livery_index = liveries_module().load_index(root)
            if livery_index:
                current = root.get("ans_garage_livery", "None")
                text = next((l["Label"] for l in livery_index.get("Liveries", []) if l["Key"] == current), "None")
                row = field(layout, "Livery")
                row.operator("object.ans_garage_livery", text=text, icon="VIEWZOOM").root = root.name
                if current != "None":
                    op = row.operator("object.ans_garage_livery", text="", icon="X")
                    op.root, op.livery, op.pick = root.name, "None", False
                    car = liveries_module().livery_car(root, current)
                    if car:
                        text = "Use its paint" + (" and plate text (%s)" % car["PlateText"] if car.get("PlateText") else "")
                        field(layout, "").operator("object.ans_garage_livery_car", text=text).root = root.name

        def draw_wheels(self, context, root, layout):
            current = json.loads(root.get("ans_garage_tire_json") or '{"Name": "Stock", "Lettering": "Plain"}')
            if tire_index(tire_library(context)) if tire_library(context) else None:
                menu_field(layout, "Tires", "ANS_GARAGE_MT_tire",
                           "Stock (car's own)" if current["Name"] == "Stock" else current["Name"], root)
                if current["Name"] != "Stock":
                    row = field(layout, "Sidewall")
                    for lettering, text in (("Plain", "Plain"), ("Brand", "Brand lettering")):
                        op = row.operator("object.ans_garage_tire", text=text, depress=current["Lettering"] == lettering)
                        op.root, op.tire, op.lettering = root.name, current["Name"], lettering
            else:
                field(layout, "Tires").operator("wm.ans_garage_shared_parts", text="Set folder…", icon="FILE_FOLDER")
            now = rims_module().current_rims(root)
            if library_index("rim", library_folder(context, "rim")) is not None:
                for axle in ("Front", "Rear"):
                    row = field(layout, axle + " rims")
                    op = row.operator("object.ans_garage_rim", text="Stock (factory)" if now[axle] == "Stock" else now[axle], icon="VIEWZOOM")
                    op.root, op.axle = root.name, axle
                row = field(layout, "")
                row.operator("object.ans_garage_rim", text="All four…").root = root.name
                op = row.operator("object.ans_garage_rim", text="", icon="LOOP_BACK")
                op.root, op.rim, op.pick = root.name, "Stock", False
            else:
                field(layout, "Rims").operator("wm.ans_garage_shared_parts", text="Set folder…", icon="FILE_FOLDER")
            paint_rows = rims_module().rim_paint(root)
            if paint_rows:
                header, colors = section(layout, root, "rim_colors")
                header.label(text="Rim colors")
                if colors:
                    col = colors.column()
                    col.use_property_split = True
                    col.use_property_decorate = False
                    for paint_text, socket in paint_rows:
                        col.prop(socket, "default_value", text=paint_text.rstrip(":"))
                    field(colors, "").operator("object.ans_garage_rim_paint_stock", text="Stock rim colors").root = root.name

        def draw_plate(self, context, root, layout):
            folder = plate_library(context)
            index = plate_index(folder) if folder else None
            current = root.get("ans_garage_plate", "Stock")
            if index is not None:
                row = field(layout, "Plate")
                row.operator("object.ans_garage_plate", text=plate_label(index, current, root), icon="VIEWZOOM").root = root.name
                if current != "Stock":
                    op = row.operator("object.ans_garage_plate", text="", icon="LOOP_BACK")
                    op.root, op.plate = root.name, "Stock"
                frames = {f["Key"]: f["Label"] for f in index.get("Frames", [])}
                if frames:
                    frame = root.get("ans_garage_plate_frame", "Stock")
                    row = field(layout, "Frame")
                    row.operator("object.ans_garage_plate_frame", text=frames.get(frame, "Stock (as the game)"),
                                 icon="VIEWZOOM").root = root.name
                    if frame != "Stock":
                        op = row.operator("object.ans_garage_plate_frame", text="", icon="LOOP_BACK")
                        op.root, op.frame, op.pick = root.name, "Stock", False
            else:
                field(layout, "Plate").operator("wm.ans_garage_shared_parts", text="Set folder…", icon="FILE_FOLDER")
            text = root.get("ans_garage_plate_text", "")
            field(layout, "Text").operator("object.ans_garage_plate_text", text=text or "(blank)").root = root.name

        def draw_moving(self, context, root, layout):
            obj, controls = animation_module().controls(root)
            if obj is not None and controls:
                row = field(layout, "")
                op = row.operator("object.ans_garage_close_moving_parts", text="Open all")
                op.root, op.value = root.name, 1.0
                row.operator("object.ans_garage_close_moving_parts", text="Close all").root = root.name
                col = layout.column(align=True)
                col.use_property_split = True
                col.use_property_decorate = False
                for group in animation_module().GROUPS:
                    for c in [c for c in controls if c["Group"] == group]:
                        if c["Key"] in obj:
                            col.prop(obj, '["%s"]' % c["Key"], text=c["Label"], slider=True)
            elif root.get("ans_garage_moving_parts_json"):
                layout.label(text="None in this car's data")
            else:
                if root.get("ans_garage_static_export"):
                    layout.label(text="Exported as a static model")
                layout.operator("object.ans_garage_moving_parts", icon="ARMATURE_DATA").root = root.name

    def menu(self, context):
        self.layout.operator(IMPORT_SCENE_OT_ans_garage_vehicle.bl_idname, text="An's Garage vehicle (.json)")

    global _registered_classes, _menu
    _registered_classes = [AnsGaragePreferences, WM_OT_ans_garage_shared_parts, OBJECT_OT_ans_garage_tire,
                           OBJECT_OT_ans_garage_plate, OBJECT_OT_ans_garage_plate_frame,
                           OBJECT_OT_ans_garage_plate_text,
                           OBJECT_OT_ans_garage_rim, OBJECT_OT_ans_garage_rim_paint_stock,
                           OBJECT_OT_ans_garage_moving_parts, OBJECT_OT_ans_garage_close_moving_parts, OBJECT_OT_ans_garage_hide_note, ANS_GARAGE_MT_part,
                           ANS_GARAGE_MT_preset, ANS_GARAGE_MT_tire, ANS_GARAGE_MT_finish, ANS_GARAGE_MT_material,
                           ANS_GARAGE_MT_shift, ANS_GARAGE_MT_gloss,
                           OBJECT_OT_ans_garage_conditions, OBJECT_OT_ans_garage_catch_up, OBJECT_OT_ans_garage_finish, OBJECT_OT_ans_garage_material,
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
