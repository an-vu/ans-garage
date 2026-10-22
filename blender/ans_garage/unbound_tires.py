"""Tire library: swap a car's tires for real-brand tires (Falken, Toyo) at the car's own stock tire size.

The library is exported once by An's Garage for Frosty (Tools > An's Garage > Export tire library...) and imported
once per .blend into a hidden collection: each tire mesh in a plain and a brand-lettered version. Choosing a tire
hides the car's stock tire instances and places the library tire the same way the stock tire is placed: the sidewall
size the game picks for the car's rim, fitted per vertex to the car's tire configuration (Wheel fit), on the wheel's
rotation empty. Nothing about the car's wheel or tire size changes.
"""
import json
import math
from pathlib import Path

from . import unbound_wheels as wheels

LIBRARY = "An's Garage tire library"
STOCK = "Stock"


def load_index(folder):
    path = Path(folder) / "tires.json"
    if not path.is_file():
        raise FileNotFoundError("No tires.json in %s (export it in Frosty: Tools > An's Garage > Export tire library...)" % folder)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def tire_names(index):
    names = []
    for t in index["Tires"]:
        if t["Name"] not in names:
            names.append(t["Name"])
    return names


def _addon():
    import importlib
    return importlib.import_module(__package__)


def ensure_library(folder):
    """Import the library once (hidden collection): {(mesh asset, lettering): [template objects]}."""
    import bpy
    folder = Path(folder).resolve()
    index = load_index(folder)
    lib, fill = _addon().library_collection(LIBRARY, "ans_garage_tire_library", folder)
    if fill:
        overrides = index["ShaderOverrides"]
        for brand in index["Brands"]:
            manifest = folder / brand / "manifest.json"
            # Meshes with their source material slots, then a lettered copy of every object.
            plain = _addon().import_library_parts(manifest)
            records = {m["Id"]: m for m in json.loads(manifest.read_text(encoding="utf-8-sig"))["Meshes"]}
            lettered = []
            for o in plain:
                c = o.copy()
                bpy.context.scene.collection.objects.link(c)
                lettered.append(c)
                for x in (o, c):
                    x["unbound_override_textures"] = str(folder / "override-textures")
                o["ans_garage_lettering"], c["ans_garage_lettering"] = "Plain", "Brand"
            remap = dict(zip(plain, lettered))
            for o, c in remap.items():
                if o.parent in remap:
                    c.parent = remap[o.parent]
                for m in c.modifiers:
                    if m.type == "ARMATURE" and m.object in remap:
                        m.object = remap[m.object]
            # Brand lettering = the brand's tirebomb override, per mesh blueprint.
            mesh_by_blueprint = index["Blueprints"]
            for c in lettered:
                asset = records.get(c.get("unbound_mesh_id"), {}).get("Asset", "")
                textures = {}
                for ov in overrides.values():
                    if brand not in ov["Asset"].lower().replace("toyoproxies", "toyo"):
                        continue
                    for m in ov["Mappings"]:
                        if mesh_by_blueprint.get(m["BlueprintGuid"], "").lower() == asset.lower():
                            textures.update(m["Textures"])
                if textures:
                    c["unbound_texture_overrides_json"] = json.dumps(textures)
            for o in plain + lettered:
                o["ans_garage_tire_mesh"] = records.get(o.get("unbound_mesh_id"), {}).get("Asset", "")
                for col in list(o.users_collection):
                    col.objects.unlink(o)
                lib.objects.link(o)
            _addon().surfaces_module().apply_supported_surfaces(plain + lettered, manifest)
        _addon().finish_library(lib)
    templates = {}
    for o in lib.all_objects:
        templates.setdefault((o.get("ans_garage_tire_mesh", "").lower(), o.get("ans_garage_lettering")), []).append(o)
    return index, templates


def apply_tire(root, name, lettering, folder):
    """Show the named library tire (or the car's stock tire) on all four wheels."""
    import bpy
    from mathutils import Matrix
    for c in list(root.children_recursive):
        if c.get("ans_garage_library_tire"):
            for o in list(c.all_objects):
                bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.collections.remove(c)
    stock_instances = [c for c in root.children_recursive if c.get("source_item") and c.get("unbound_tire_stock")]
    if not stock_instances:
        stock_instances = [c for c in root.children_recursive
                           if (json.loads(c.get("source_item_json", "{}")).get("Type") == "TiresItemData")]
        for c in stock_instances:
            c["unbound_tire_stock"] = True
    root["ans_garage_tire_json"] = json.dumps({"Name": name, "Lettering": lettering})
    for c in stock_instances:
        c.hide_viewport = c.hide_render = name != STOCK
    if name == STOCK:
        return []
    assembly = Path(root["unbound_assembly_path"])
    if not assembly.is_file():
        raise FileNotFoundError("This car's export folder has moved: %s is missing. Put the export back where it was "
                                "imported from to change its tires." % assembly)
    index, templates = ensure_library(folder)
    data = json.loads(assembly.read_text(encoding="utf-8-sig"))
    nodes = {n["Id"]: n for n in data["Nodes"]}
    tire_config = nodes[data["TireConfig"]]["Raw"] if data.get("TireConfig") in nodes else {}
    conversion = Matrix([tuple(r) for r in json.loads(root["fbx_to_blender_matrix"])])
    inverse = conversion.inverted()
    notes = []
    stock_items = [i for i in data["Items"] if i["Type"] == "TiresItemData" and i["Default"]]
    for wheel in data["Wheels"]:
        facing = wheel["Facing"]
        axle = "Front" if facing["Front"] else "Rear"
        side = "left" if facing["Left"] else "right"
        spin = next((o for o in root.all_objects if o.name.startswith(wheel["Name"] + " | Rotation")), None)
        wheel_col = next((c for c in root.children_recursive if c.name.split(".")[0] == wheel["Name"]), None)
        if spin is None or wheel_col is None:
            notes.append("%s: wheel controls not found" % wheel["Name"])
            continue
        tire = next((t for t in index["Tires"] if t["Name"] == name and t["Lettering"] == lettering
                     and t["Position"] == "ItemPosition_" + axle), None)
        outer, width = tire_config.get("Diameter" + axle), tire_config.get("SectionWidth" + axle)
        rim = wheels.rim_diameter(data, tire_config, axle)
        if tire is None or not (outer and width and rim):
            notes.append("%s: %s" % (wheel["Name"], "no library tire for this axle" if tire is None else "tire size unknown"))
            continue
        # The game's sidewall-size thresholds (libraries exported before 1.0.9 don't record them: the stock tire's).
        stock = (stock_items[0]["Raw"] if stock_items else {})
        size = wheels.tire_size(tire["Sizes"], rim, outer, tire.get("SmallToMedRatio") or stock.get("SmallToMedRatio", 0.77),
                                tire.get("MedToLargeRatio") or stock.get("MedToLargeRatio", 0.71))
        desc = next((m for m in size["Meshes"] if side in (m.get("Tag") or "").lower()), size["Meshes"][0])
        sources = templates.get((desc["Mesh"].lower(), lettering), [])
        if not sources:
            notes.append("%s: library mesh %s not imported" % (wheel["Name"], desc["Mesh"]))
            continue
        rotation = Matrix.Rotation(math.pi, 4, "Y") if desc["Rotate"] else Matrix.Identity(4)
        local = conversion @ rotation @ inverse
        inst = bpy.data.collections.new("Tire | " + name)
        wheel_col.children.link(inst)
        inst["ans_garage_library_tire"] = True
        inst["source_item"] = tire["Asset"]
        offsets = wheels.tire_offsets(size, outer, rim, width)
        inst["dimension_status"] = ("Library tire, %.3f m sidewall mesh fitted per vertex (Wheel fit): tread %+.4f m, bead %+.4f m, "
                                    "each side %+.4f m" % ((size["InnerDiameter"],) + offsets))
        wheels.fit(_addon().place_copies(sources, inst, spin, local), offsets)
    return notes
