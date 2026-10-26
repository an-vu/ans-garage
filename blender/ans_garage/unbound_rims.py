"""Rim library: put a real-brand aftermarket rim (BBS, HRE, Rotiform, Work...) on a car.

The library is exported once by An's Garage for Frosty (Tools > An's Garage > Export shared parts...); each brand is
imported into a hidden collection the first time one of its rims is chosen. Choosing a rim hides the car's own wheel
sets and places the library rim on every wheel's rotation empty, resized from its declared size (Diameter, Width) to the
car's factory rim on that axle the way the game's wheel shader does it (Wheel fit: the barrel and back lip move, the hub
and spokes by the rim's own vertex weights). Stock brings the car's own wheel set back. A car's factory wheels come with its own export, never from
the library.
"""
import json
import math
from pathlib import Path

from . import unbound_wheels as wheels

LIBRARY = "An's Garage rim library"
STOCK = "Stock"


def load_index(folder):
    path = Path(folder) / "rims.json"
    if not path.is_file():
        raise FileNotFoundError("No rims.json in %s (export it in Frosty: Tools > An's Garage > Export shared parts...)" % folder)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def rim_names(index):
    """Model names, by brand then name."""
    return sorted({r["Name"] for r in index["Rims"]}, key=lambda n: (next(r["Brand"] for r in index["Rims"] if r["Name"] == n), n.lower()))


def _addon():
    import importlib
    return importlib.import_module(__package__)


def ensure_library(folder, brands):
    """Import the given brand folders of the library once each (hidden collection): {mesh asset: [template objects]}.
    Templates keep their source material slots only: placed copies are built against their car."""
    folder = Path(folder).resolve()
    index = load_index(folder)
    lib, _ = _addon().library_collection(LIBRARY, "ans_garage_rim_library", folder)
    done = set(lib.get("ans_garage_rim_brands", []))
    for brand in sorted(set(brands) - done):
        manifest = folder / brand / "manifest.json"
        objects = _addon().import_library_parts(manifest)
        records = {m["Id"]: m for m in json.loads(manifest.read_text(encoding="utf-8-sig"))["Meshes"]}
        for o in objects:
            o["ans_garage_rim_mesh"] = records.get(o.get("unbound_mesh_id"), {}).get("Asset", "")
            for col in list(o.users_collection):
                col.objects.unlink(o)
            lib.objects.link(o)
        done.add(brand)
        lib["ans_garage_rim_brands"] = sorted(done)
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


def wheel_of(collection):
    """Name of the wheel a placed part's collection is mounted on (its objects hang from that wheel's empties)."""
    for o in collection.all_objects:
        p = o
        while p is not None and not p.get("wheel_side"):
            p = p.parent
        if p is not None:
            return p["wheel_side"]
    return None


def current_rims(root):
    """{"Front": name, "Rear": name} of the rims shown (Stock = the car's own wheel set)."""
    both = root.get("ans_garage_rim", STOCK)
    return {a: root.get("ans_garage_rim_" + a.lower(), both) for a in AXLES}


AXLES = ("Front", "Rear")


def apply_rim(root, name, folder, axle=None):
    """Show the named library rim, or the car's own wheel set (Stock), on both axles or one ("Front"/"Rear"), as the
    game's Front Rims / Rear Rims. Returns notes."""
    import bpy
    from mathutils import Matrix
    axles = AXLES if axle in (None, "Both") else (axle,)
    assembly = Path(root["unbound_assembly_path"])
    if name != STOCK and not assembly.is_file():
        raise FileNotFoundError("This car's export folder has moved: %s is missing. Put the export back where it was "
                                "imported from to change its rims." % assembly)
    data = json.loads(assembly.read_text(encoding="utf-8-sig")) if assembly.is_file() else {"Wheels": [], "Items": []}
    targets = {w["Name"] for w in data["Wheels"] if ("Front" if w["Facing"]["Front"] else "Rear") in axles}
    for c in list(root.children_recursive):
        if c.get("ans_garage_library_rim") and wheel_of(c) in targets:
            for o in list(c.all_objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.collections.remove(c)
    for a in axles:
        root["ans_garage_rim_" + a.lower()] = name
    now = current_rims(root)
    root["ans_garage_rim"] = now["Front"] if now["Front"] == now["Rear"] else "Mixed"
    # The car's own wheel set stays the choice group; its rims are hidden on the axles that carry a library rim.
    factory = next((c for c in root.children if c.get("unbound_choice_group") == "Rims"), None)
    if factory is not None:
        factory.hide_viewport = factory.hide_render = False
        for c in factory.children_recursive:
            if c.get("source_item") and wheel_of(c) in targets:
                c.hide_viewport = c.hide_render = name != STOCK
    if name == STOCK:
        stock = wheels.factory_rims(data)
        for a in axles:
            size_axle_brakes(root, data, a, wheels.brake_scale(stock.get(a)))
        return []
    if not assembly.is_file():
        raise FileNotFoundError("This car's export folder has moved: %s is missing. Put the export back where it was "
                                "imported from to change its rims." % assembly)
    index = load_index(folder)
    choices = [r for r in index["Rims"] if r["Name"] == name]
    if not choices:
        raise ValueError("Rim %s is not in the library" % name)
    index, templates = ensure_library(folder, {r["Folder"] for r in choices})
    conversion = Matrix([tuple(r) for r in json.loads(root["fbx_to_blender_matrix"])])
    inverse = conversion.inverted()
    stock = {i.get("Location"): i["Raw"] for i in data["Items"] if i["Type"] == "RimsItemData" and i["Default"]}
    notes, placed = [], []
    for wheel in data["Wheels"]:
        facing = wheel["Facing"]
        axle = "Front" if facing["Front"] else "Rear"
        if wheel["Name"] not in targets:
            continue
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
        local = conversion @ rotation @ inverse
        offsets = wheels.rim_offsets(rim, car["Diameter"], car["Width"])
        inst = bpy.data.collections.new("Rim | " + name)
        wheel_col.children.link(inst)
        inst["ans_garage_library_rim"] = True
        inst["source_item"] = rim["Asset"]
        inst["dimension_status"] = ("Library rim %.3f x %.3f m fitted per vertex (Wheel fit) to the factory rim %.3f x %.3f m: "
                                    "barrel %+.4f m, back lip %+.4f m"
                                    % (rim["Diameter"], rim["Width"], car["Diameter"], car["Width"], offsets[1], offsets[2]))
        copies = _addon().place_copies(sources, inst, spin, local)
        wheels.fit(copies, offsets)
        placed.extend(copies)
        # The brakes follow the rim: its BrakeDiscRatio at its fitted diameter (libraries before 1.1.0 lack the ratio).
        scale = wheels.brake_scale(rim, car["Diameter"])
        if scale:
            size_axle_brakes(root, data, axle, scale, wheel["Name"])
    # Built against the car: rim shaders read per-wheel inputs (front or rear) and the car's rim paint.
    slots = []
    for o in placed:
        if o.type == "MESH":
            o["unbound_car_assembly"] = str(assembly)
            slots.extend((o, i) for i in range(len(o.material_slots)))
    built, failed = _addon().surfaces_module().rebuild(slots)
    notes += sorted({f.get("Reason") or f.get("Issue") or "" for f in failed})
    return notes


def size_axle_brakes(root, data, axle, scale, wheel_name=None):
    """Resize the brake discs and calipers on an axle's wheels (or one wheel) to `scale`."""
    if not scale:
        return
    names = [w["Name"] for w in data["Wheels"] if (w["Facing"]["Front"]) == (axle == "Front")]
    for c in root.children_recursive:
        item = json.loads(c.get("source_item_json", "{}")).get("Type")
        if item not in ("BrakeDiscsItemData", "CalipersItemData"):
            continue
        wheel = next((p for p in root.children_recursive if c.name in p.children), None)
        wname = wheel.name.split(".")[0] if wheel else None
        if wname in names and (wheel_name is None or wname == wheel_name):
            wheels.size_brakes(c.all_objects, scale)
