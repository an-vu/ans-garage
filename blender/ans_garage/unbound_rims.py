"""Rim library: put a real-brand aftermarket rim (BBS, HRE, Rotiform, Work...) on a car.

The library is exported once by An's Garage for Frosty (Tools > An's Garage > Export rim library...) and imported once
per .blend into a hidden collection. Choosing a rim hides the car's own wheel sets and places the library rim on every
wheel's rotation empty, scaled from the rim's declared size (Diameter, Width) to the car's factory rim on that axle; the
game resizes rims in the wheel shader instead. Stock brings the car's own wheel set back. A car's factory wheels come
with its own export, never from the library.
"""
import json
import math
from pathlib import Path

LIBRARY = "An's Garage rim library"
STOCK = "Stock"


def load_index(folder):
    path = Path(folder) / "rims.json"
    if not path.is_file():
        raise FileNotFoundError("No rims.json in %s (export it in Frosty: Tools > An's Garage > Export rim library...)" % folder)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rim_names(index):
    """Model names, by brand then name."""
    return sorted({r["Name"] for r in index["Rims"]}, key=lambda n: (next(r["Brand"] for r in index["Rims"] if r["Name"] == n), n.lower()))


def _addon():
    import importlib
    return importlib.import_module(__package__)


def ensure_library(folder):
    """Import the library once (hidden collection): {mesh asset: [template objects]}."""
    folder = Path(folder).resolve()
    index = load_index(folder)
    lib, fill = _addon().library_collection(LIBRARY, "ans_garage_rim_library", folder)
    if fill:
        for brand in index["Folders"]:
            manifest = folder / brand / "manifest.json"
            objects = _addon().import_library_parts(manifest)
            records = {m["Id"]: m for m in json.loads(manifest.read_text(encoding="utf-8-sig"))["Meshes"]}
            for o in objects:
                o["ans_garage_rim_mesh"] = records.get(o.get("unbound_mesh_id"), {}).get("Asset", "")
                for col in list(o.users_collection):
                    col.objects.unlink(o)
                lib.objects.link(o)
            _addon().surfaces_module().apply_supported_surfaces(objects, manifest)
        _addon().finish_library(lib)
    templates = {}
    for o in lib.all_objects:
        templates.setdefault(o.get("ans_garage_rim_mesh", "").lower(), []).append(o)
    return index, templates


def rim_paint(root):
    """[(label, RGB socket)] of the car's live rim colours (primary/secondary, front/rear) that its surfaces use."""
    addon = _addon()
    P, scope = addon.surfaces_module().profiles_module(), addon.car_scope(root)
    found = []
    for field in P.RIM_COLOR_FIELDS:
        g = P.runtime_group(scope, field=field)
        if g is not None:
            label = field.replace("ColorParameter", "").replace("Rim", " ")
            found.append((label, P.runtime_rgb(g)))
    return found


def stock_rim_paint(root):
    """Put the car's own rim colours back."""
    addon = _addon()
    P, scope = addon.surfaces_module().profiles_module(), addon.car_scope(root)
    for field in P.RIM_COLOR_FIELDS:
        g = P.runtime_group(scope, field=field)
        if g is not None:
            P.runtime_rgb(g).default_value = list(g["unbound_stock_value"][:3]) + [1.0]


def apply_rim(root, name, folder):
    """Show the named library rim on all four wheels, or the car's own wheel set (Stock). Returns notes."""
    import bpy
    from mathutils import Matrix
    for c in list(root.children_recursive):
        if c.get("ans_garage_library_rim"):
            for o in list(c.all_objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.collections.remove(c)
    factory = next((c for c in root.children if c.get("unbound_choice_group") == "Rims"), None)
    root["ans_garage_rim"] = name
    if factory is not None:
        factory.hide_viewport = factory.hide_render = name != STOCK
    if name == STOCK:
        return []
    assembly = Path(root["unbound_assembly_path"])
    if not assembly.is_file():
        raise FileNotFoundError("This car's export folder has moved: %s is missing. Put the export back where it was "
                                "imported from to change its rims." % assembly)
    index, templates = ensure_library(folder)
    data = json.loads(assembly.read_text(encoding="utf-8-sig"))
    conversion = Matrix([tuple(r) for r in json.loads(root["fbx_to_blender_matrix"])])
    inverse = conversion.inverted()
    stock = {i.get("Location"): i["Raw"] for i in data["Items"] if i["Type"] == "RimsItemData" and i["Default"]}
    choices = [r for r in index["Rims"] if r["Name"] == name]
    if not choices:
        raise ValueError("Rim %s is not in the library" % name)
    notes, placed = [], []
    for wheel in data["Wheels"]:
        facing = wheel["Facing"]
        axle = "Front" if facing["Front"] else "Rear"
        side = "left" if facing["Left"] else "right"
        spin = next((o for o in root.all_objects if o.name.startswith(wheel["Name"] + " | Rotation")), None)
        wheel_col = next((c for c in root.children_recursive if c.name.split(".")[0] == wheel["Name"]), None)
        car = stock.get("ItemPosition_" + axle)
        if spin is None or wheel_col is None or car is None:
            notes.append("%s: %s" % (wheel["Name"], "wheel controls not found" if car else "no factory rim size for this axle"))
            continue
        # The model's item for this axle; a model sold for one axle only goes on both.
        rim = next((r for r in choices if r["Position"] == "ItemPosition_" + axle), choices[0])
        desc = next((m for m in rim["Meshes"] if axle.lower() in (m.get("Tag") or "").lower() and side in (m.get("Tag") or "").lower()),
                    next((m for m in rim["Meshes"] if side in (m.get("Tag") or "").lower()), rim["Meshes"][0]))
        sources = templates.get(desc["Mesh"].lower(), [])
        if not sources:
            notes.append("%s: library mesh %s not imported" % (wheel["Name"], desc["Mesh"]))
            continue
        rotation = Matrix.Rotation(math.pi, 4, "Y") if desc["Rotate"] else Matrix.Identity(4)
        radial, axial = car["Diameter"] / rim["Diameter"], car["Width"] / rim["Width"]
        local = conversion @ rotation @ Matrix.Diagonal((axial, radial, radial, 1)) @ inverse
        inst = bpy.data.collections.new("Rim | " + name)
        wheel_col.children.link(inst)
        inst["ans_garage_library_rim"] = True
        inst["source_item"] = rim["Asset"]
        inst["dimension_status"] = ("Library rim %.3f x %.3f m scaled to the factory rim %.3f x %.3f m (object scale; the game "
                                    "resizes rims in the wheel shader)" % (rim["Diameter"], rim["Width"], car["Diameter"], car["Width"]))
        placed.extend(_addon().place_copies(sources, inst, spin, local))
    # Built against the car: rim shaders read per-wheel inputs (front or rear) and the car's rim paint.
    slots = []
    for o in placed:
        if o.type == "MESH":
            o["unbound_car_assembly"] = str(assembly)
            slots.extend((o, i) for i in range(len(o.material_slots)))
    built, failed = _addon().surfaces_module().rebuild(slots)
    notes += sorted({f.get("Reason") or f.get("Issue") or "" for f in failed})
    return notes
