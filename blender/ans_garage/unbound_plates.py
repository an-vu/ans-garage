"""License plate library: put a real US state or territory, Japanese, NFS-place, plain or Palifornia plate on a car,
and a plate frame.

The library is exported once by An's Garage for Frosty (Tools > An's Garage > Export shared parts...). Choosing
a plate overrides the plate shader's background texture (Ext_T_LicensePlate_Diffuse) on every license plate of the car,
the way the game's plate customization does, and rebuilds those material slots; choosing a frame overrides its frame
textures (Ext_T_Frame_Diffuse, Ext_T_Frame_Normalmap) the same way. The plate's text colour comes from its own texture,
as in the game.

Stock is what the game shows: the plate and frame items of the car as bought (its RaceVehicleItemData sub-items; every
car checked has the Lakeshore plate and no frame item, so the component's default no-frame textures) and its default
text. The plate mesh's own textures (a California-style plate with a Speedhunters frame) are a placeholder the game
replaces; they stay only while the plate library isn't set.
"""
import json
from pathlib import Path

STOCK = "Stock"
PLATE_SHADER = "licenseplate_max"
PLATE_PARAMETER = "Ext_T_LicensePlate_Diffuse"  # the library's plates.json "Parameter"


def load_index(folder):
    path = Path(folder) / "plates.json"
    if not path.is_file():
        raise FileNotFoundError("No plates.json in %s (export it in Frosty: Tools > An's Garage > Export shared parts...)"
                                % folder)
    return json.loads(path.read_text(encoding="utf-8-sig"))


def game_stock(root):
    """{"Plate": library key or None, "Frame": library frame item leaf or None (no frame item), "Text": text} of the
    car as the game sells it, from its assembly data."""
    try:
        data = json.loads(Path(root["unbound_assembly_path"]).read_text(encoding="utf-8-sig"))
    except (KeyError, OSError, ValueError):
        return {"Plate": None, "Frame": None, "Text": None}
    cars = [n for n in data.get("Nodes", []) if n.get("Type") == "RaceVehicleItemData"]
    car = next((n for n in cars if n.get("Id") == data.get("StockItem")), cars[0] if cars else None)
    raw = (car or {}).get("Raw") or {}
    leaves = [(s.get("Asset") or "").rsplit("/", 1)[-1].lower() for s in raw.get("SubItems") or []]
    plate = next((l[len("licenseplatebackground_"):] for l in leaves if l.startswith("licenseplatebackground_")), None)
    frame = next((l for l in leaves if l.startswith("licenseplateframe_")), None)
    return {"Plate": plate, "Frame": frame, "Text": raw.get("DefaultLicensePlateText")}


def stock_plate(root, index):
    """The library plate the game shows on this car, or None (no library, or not in it)."""
    key = game_stock(root)["Plate"]
    return next((p for p in (index or {}).get("Plates", []) if p["Key"] == key), None)


def stock_frame(root, index):
    """The library frame the game shows on this car: its frame item's, else the no-frame textures (the component's
    default); None without a library that has frames."""
    frames = (index or {}).get("Frames", [])
    item = game_stock(root)["Frame"]
    if item:
        return next((f for f in frames if (f.get("Item") or "").rsplit("/", 1)[-1].lower() == item), None)
    return next((f for f in frames if f["Key"] == "none"), None)


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
    """Show the plate `key` of the library in `folder` (STOCK: the game's, see stock_plate; the mesh's placeholder
    without a library) on every license plate of the car. Returns the number of plate slots built."""
    index = load_index(folder) if folder else None
    if key == STOCK:
        plate = stock_plate(root, index)
    else:
        if index is None:
            raise ValueError("No license plate library")
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
        elif index is None and "unbound_override_textures" in o:
            del o["unbound_override_textures"]
    root["ans_garage_plate"] = key
    return _rebuild(slots)


def apply_frame(root, key, folder):
    """Show the frame `key` of the library in `folder` (STOCK: the game's, see stock_frame; the mesh's placeholder
    without a library that has frames) on every license plate of the car. Returns the number of plate slots built."""
    index = load_index(folder) if folder else None
    if key == STOCK:
        frame = stock_frame(root, index)
    else:
        frame = next((f for f in (index or {}).get("Frames", []) if f["Key"] == key), None)
        if frame is None:
            raise ValueError("Frame %s is not in the library (export Plate frames in Frosty)" % key)
    slots = plate_slots(root)
    if not slots:
        raise ValueError("This car has no license plate")
    params = (index or {}).get("FrameParameters") or {"Diffuse": "Ext_T_Frame_Diffuse", "Normal": "Ext_T_Frame_Normalmap"}
    surfaces = _addon().surfaces_module()
    for o, i in slots:
        surfaces.set_texture_overrides(o, {params["Diffuse"]: frame["Diffuse"] if frame else None,
                                           params["Normal"]: frame["Normal"] if frame else None})
        if frame:
            o["unbound_override_textures"] = str(Path(folder).resolve() / "textures")
        elif index is None and "unbound_override_textures" in o:
            del o["unbound_override_textures"]
    root["ans_garage_plate_frame"] = key
    return _rebuild(slots)


def plate_on(root):
    return root.get("ans_garage_plate", STOCK)


def apply_game_stock(root, folder, frame=STOCK):
    """At import: the plate, frame (`frame`: STOCK or a library key, the add-on preference) and text the game shows.
    Returns a line for the import report."""
    stock = game_stock(root)
    index = load_index(folder)
    plate = stock_plate(root, index)
    chosen = stock_frame(root, index) if frame == STOCK else next((f for f in index.get("Frames", []) if f["Key"] == frame), None)
    apply_plate(root, STOCK, folder)
    if chosen:
        apply_frame(root, frame if frame != STOCK else STOCK, folder)
    if stock["Text"]:
        apply_text(root, stock["Text"])
    return "%s, frame %s, text %s (as the game)" % (plate["Label"] if plate else "the car's placeholder",
                                                    chosen["Label"] if chosen else "the car's placeholder", stock["Text"] or "kept")


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
