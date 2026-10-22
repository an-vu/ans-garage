"""License plate library: put a real US state or territory, Japanese or NFS-place plate on a car.

The library is exported once by An's Garage for Frosty (Tools > An's Garage > Export license plate library...). Choosing
a plate overrides the plate shader's background texture (Ext_T_LicensePlate_Diffuse) on every license plate of the car,
the way the game's plate customization does, and rebuilds those material slots. The plate text and frame stay the
car's own. Stock brings the car's own plate back.
"""
import json
from pathlib import Path

STOCK = "Stock"
PLATE_SHADER = "licenseplate_max"
PLATE_PARAMETER = "Ext_T_LicensePlate_Diffuse"  # the library's plates.json "Parameter"


def load_index(folder):
    path = Path(folder) / "plates.json"
    if not path.is_file():
        raise FileNotFoundError("No plates.json in %s (export it in Frosty: Tools > An's Garage > Export license plate "
                                "library...)" % folder)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _addon():
    import importlib
    return importlib.import_module(__package__)


def plate_slots(root):
    """(object, slot index) of every license plate slot of the car that faces use, in every bumper variant."""
    found = []
    for o in root.all_objects:
        if o.type != "MESH" or not o.get("unbound_mesh_id"):
            continue
        used = {p.material_index for p in o.data.polygons}
        for i, material in enumerate(o.data.materials):
            if i not in used or material is None or not material.get("unbound_source_json"):
                continue
            try:
                shader = (json.loads(material["unbound_source_json"]).get("Shader") or {}).get("Asset") or ""
            except ValueError:
                continue
            if shader.lower().endswith(PLATE_SHADER):
                found.append((o, i))
    return found


def apply_plate(root, key, folder):
    """Show the plate `key` of the library in `folder` (or the car's own, for STOCK) on every license plate of the
    car. Returns the number of plate slots built."""
    plate, index = None, None
    if key != STOCK:
        index = load_index(folder)
        plate = next((p for p in index["Plates"] if p["Key"] == key), None)
        if plate is None:
            raise ValueError("Plate %s is not in the library" % key)
    slots = plate_slots(root)
    if not slots:
        raise ValueError("This car has no license plate")
    surfaces = _addon().surfaces_module()
    for o, i in slots:
        surfaces.set_texture_overrides(o, {PLATE_PARAMETER: plate["Texture"] if plate else None})
        if plate:
            o["unbound_override_textures"] = str(Path(folder).resolve() / "textures")
        elif "unbound_override_textures" in o:
            del o["unbound_override_textures"]
    root["ans_garage_plate"] = key
    return _rebuild(slots)


def apply_text(root, text):
    """Put `text` (A-Z, 0-9 and spaces, at most 7 characters) on every license plate of the car, drawn with the
    game's plate font. Returns the number of plate slots built."""
    slots = plate_slots(root)
    if not slots:
        raise ValueError("This car has no license plate")
    profiles = _addon().surfaces_module().profiles_module()
    values = profiles.plate_text_values(text)
    for o, _ in slots:
        o["unbound_parameter_overrides_json"] = json.dumps(values)
    root["ans_garage_plate_text"] = clean_text(text)
    return _rebuild(slots)


def clean_text(text):
    """The text as the plate shows it: upper case, A-Z, 0-9 and spaces only, at most 7 characters."""
    chars = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ "
    return "".join(c for c in (text or "").upper() if c in chars)[:7].strip()


def _rebuild(slots):
    """Rebuild the given plate slots from their source materials with the current overrides."""
    built, failed = _addon().surfaces_module().rebuild(slots)
    if failed and not built:
        raise ValueError("Plate not built: " + (failed[0].get("Reason") or failed[0].get("Issue") or "unknown"))
    return len(built)
