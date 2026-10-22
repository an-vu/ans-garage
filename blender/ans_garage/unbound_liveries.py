"""Stock liveries: the game's own designs for a car (AI racers, rivals, story, delivery and police cars).

An's Garage for Frosty exports the ones ticked in its export dialog (more can be added later with Tools > An's Garage >
Add liveries to an existing export...) into <export>/liveries. Choosing one overrides the paint shader's livery textures
(Ext_T_Livery_Diffuse and Ext_T_Livery_Material) on every paint slot of the car, the way the game applies a static
livery, and rebuilds those slots. None brings the plain stock paint back.

Most liveries belong to a car template in the game (an AI racer's, rival's or story car's whole setup) with its own
paint, finish and plate text; those come along in liveries.json ("Car") and use_livery_car() puts them on the car.
"""
import json
from pathlib import Path

NONE = "None"
_INDEX = {}


def _addon():
    import importlib
    return importlib.import_module(__package__)


def load_index(root):
    """The car's liveries.json (re-read when it changes), or None when no livery was exported."""
    path = Path(root["unbound_assembly_path"]).parent / "liveries" / "liveries.json"
    if not path.is_file():
        return None
    stamp = path.stat().st_mtime
    if _INDEX.get(path, (None,))[0] != stamp:
        _INDEX[path] = (stamp, json.loads(path.read_text(encoding="utf-8-sig")))
    return _INDEX[path][1]


def livery_car(root, key):
    """The car template setup (Paint, Finish, PlateText) of an exported livery, or None."""
    index = load_index(root) or {}
    return next((l.get("Car") for l in index.get("Liveries", []) if l["Key"] == key), None)


def use_livery_car(root, key):
    """Give the car the paint colour, finish and plate text of the livery's car template (as in the game)."""
    setup = livery_car(root, key)
    if not setup:
        raise ValueError("This livery has no car setup of its own")
    addon = _addon()
    P, scope = addon.surfaces_module().profiles_module(), addon.car_scope(root)
    for name, field in (("Ext_Carpaint_Diffuse", "Paint"), ("Ext_Carpaint_Material", "Finish")):
        g = P.runtime_group(scope, name)
        if g is not None and setup.get(field):
            rgb = next(n for n in g.nodes if n.type == "RGB").outputs[0]
            rgb.default_value = list(setup[field][:3]) + [1.0]
    if setup.get("PlateText"):
        addon.plates_module().apply_text(root, setup["PlateText"])


def livery_slots(root, parameter):
    """(object, slot index) of every slot that faces use whose shader reads the livery texture, in every variant."""
    P = _addon().surfaces_module().profiles_module()
    found = []
    for o in root.all_objects:
        if o.type != "MESH" or not o.get("unbound_mesh_id"):
            continue
        used = {p.material_index for p in o.data.polygons}
        for i, material in enumerate(o.data.materials):
            if i not in used or material is None or not material.get("unbound_source_json"):
                continue
            try:
                profile = P.profile_for(json.loads(material["unbound_source_json"]))
            except ValueError:
                continue
            if profile and any((s.get("Parameter") or "") == parameter for e in profile["Entries"] for s in e["Slots"].values()):
                found.append((o, i))
    return found


def apply_livery(root, key):
    """Show the exported livery `key` (or None) on the car. Returns the number of paint slots built."""
    index = load_index(root)
    if index is None:
        raise ValueError("No liveries exported for this car (Frosty: Tools > An's Garage > Add liveries to an existing export...)")
    livery = None
    if key != NONE:
        livery = next((l for l in index["Liveries"] if l["Key"] == key), None)
        if livery is None:
            raise ValueError("Livery %s is not in this export" % key)
    params = index["Parameters"]
    slots = livery_slots(root, params["Diffuse"])
    if not slots:
        raise ValueError("This car has no paint that takes a livery")
    surfaces = _addon().surfaces_module()
    for o, _ in slots:
        surfaces.set_texture_overrides(o, {params["Diffuse"]: livery["Diffuse"] if livery else None,
                                           params["Material"]: livery["Material"] if livery else None})
    root["ans_garage_livery"] = key
    built, failed = surfaces.rebuild(slots)
    if failed and not built:
        raise ValueError("Livery not built: " + (failed[0].get("Reason") or failed[0].get("Issue") or "unknown"))
    return len(built)
