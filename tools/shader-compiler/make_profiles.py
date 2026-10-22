"""Derive per-shader bindings/exposed parameters from an export's material states and build profiles."""
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.setrecursionlimit(50000)
import build_profile as bp

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
from settings import path as setting  # noqa: E402

DATA = setting("shader_data_dir")  # game-derived inputs; never committed
spec = importlib.util.spec_from_file_location("um", HERE.parents[1] / "blender" / "ans_garage" / "unbound_materials.py")
um = importlib.util.module_from_spec(spec)
spec.loader.exec_module(um)
# Runtime customization parameters set per vehicle through RaceVehicleCustomizationComponentData keys.
RUNTIME_EXPOSED = {"Ext_Carpaint_Diffuse", "Ext_Carpaint_Material", "Ext_Glass_Color"}
# Runtime damage state, fixed to the undamaged static state. Evidence: the program gates the damage texture with it.
STATIC_UNDAMAGED = {"Ext_GlassDamage": [0.0, 0.0, 0.0, 0.0]}


def vehicle_states(materials_path):
    doc = json.loads(Path(materials_path).read_text(encoding="utf-8-sig"))
    r = um.Resolver(doc)
    states = []
    for mesh in doc["Meshes"]:
        for slot in mesh["Slots"]:
            st, _, _ = r.choose_root(mesh, slot)
            states.append(st)
            for v in mesh.get("Variants", []):
                try:
                    states.append(r.resolve(mesh, slot, v))
                except Exception:
                    pass
    return doc, states


def bindings_for(shader, states, root):
    """{texture parameter: 'image' | uniform [r,g,b,a]} over all states using this shader."""
    values = defaultdict(set)
    for st in states:
        if (st["Shader"] or {}).get("Asset") != shader:
            continue
        for b in st["TextureBindings"]:
            if not b.get("Path"):
                values[b["Parameter"]].add("missing")
                continue
            u = bp.uniform_texture_value(Path(root) / b["Path"], b.get("ColorSpace") == "sRGB")
            values[b["Parameter"]].add(json.dumps(u) if u is not None else "image")
    out = {}
    for p, vs in values.items():
        out[p] = json.loads(next(iter(vs))) if len(vs) == 1 and next(iter(vs)) not in ("image", "missing") else "image"
    return out


def runtime_keys(materials_path):
    """Parameter keys the vehicle binds to runtime customization (ShaderParameterHandle in assembly.json)."""
    path = Path(materials_path).with_name("assembly.json")
    if not path.is_file():
        return set()
    keys = set()
    def walk(o):
        if isinstance(o, dict):
            h = o.get("ShaderParameterHandle")
            if isinstance(h, dict) and isinstance(h.get("Data"), str):
                keys.add(h["Data"].casefold())
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(json.loads(path.read_text(encoding="utf-8-sig")))
    return keys


def overridden_params(shader, states, ext_defaults):
    """External values that some material on this vehicle sets to a non-default value."""
    found = set()
    for st in states:
        if (st["Shader"] or {}).get("Asset") != shader:
            continue
        for p in st["Parameters"]["VectorParameters"].values():
            name = um.plain(p["ParameterName"])
            d = ext_defaults.get(name.casefold())
            if d is None:
                continue
            v = [p.get("Value", {}).get(c, 0) for c in "xyzw"]
            if any(abs(a - b) > 1e-6 for a, b in zip(v, d["Value"][:4])):
                found.add(d["Name"])
        for p in st["Parameters"]["BoolParameters"].values():
            name = um.plain(p["ParameterName"])
            if name.casefold() in ext_defaults:
                found.add(ext_defaults[name.casefold()]["Name"])
    return found
