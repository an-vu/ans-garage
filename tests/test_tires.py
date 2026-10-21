"""Tire library: swap a car's tires for library tires and back.
blender --background --factory-startup --python-exit-code 1 --python test_tires.py -- <addon parent dir> <export dir> <tire library dir> <out dir>
"""
import importlib
import json
import sys
import time
from pathlib import Path

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, export, library, out_dir = Path(args[0]), Path(args[1]), Path(args[2]), Path(args[3])
bpy.ops.wm.read_factory_settings(use_empty=True)
sys.path.insert(0, str(addon_parent))
addon = importlib.import_module("ans_garage")
addon.register()
checks = []


def check(name, ok, detail=None):
    checks.append({"Check": name, "Passed": bool(ok), **({"Detail": detail} if detail is not None else {})})
    print(("PASS " if ok else "FAIL ") + name + ("" if detail is None else "  " + json.dumps(detail, ensure_ascii=False)[:500]))


def size(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type == "MESH" for c in o.bound_box]
    return [round(max(p[i] for p in pts) - min(p[i] for p in pts), 3) for i in range(3)] if pts else None


addon.import_manifest(str(export / "manifest.json"))
root = next(c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path"))
bpy.context.scene["ans_garage_tire_library"] = str(library)
stock = [c for c in root.children_recursive if json.loads(c.get("source_item_json", "{}")).get("Type") == "TiresItemData"]
bpy.context.view_layer.update()
stock_size = size(stock[0].all_objects) if stock else None
check("Car has four stock tire instances", len(stock) == 4, len(stock))

for name, lettering in (("Falken Azenis RT615K+", "Plain"), ("Falken Azenis RT615K+", "Brand"), ("Toyo Tires Proxes R888R", "Brand")):
    started = time.perf_counter()
    status = bpy.ops.object.ans_garage_tire(root=root.name, tire=name, lettering=lettering)
    seconds = round(time.perf_counter() - started, 1)
    bpy.context.view_layer.update()
    lib = [c for c in root.children_recursive if c.get("ans_garage_library_tire")]
    shown = [c for c in lib if not c.hide_viewport]
    check("%s (%s): applied" % (name, lettering), status == {"FINISHED"} and len(lib) == 4,
          {"Status": list(status), "Instances": len(lib), "Seconds": seconds})
    check("%s (%s): stock tires hidden" % (name, lettering), all(c.hide_viewport and c.hide_render for c in stock))
    mats = {s.material for c in lib for o in c.all_objects if o.type == "MESH" for s in o.material_slots if s.material}
    built = [m for m in mats if m.get("unbound_surface_profile")]
    check("%s (%s): tire materials built from the compiled shader" % (name, lettering), mats and len(built) == len(mats),
          sorted(m.name for m in mats)[:4])
    images = {(n.image.get("unbound_asset") or n.image.name) for m in mats for g in [n for n in m.node_tree.nodes if n.type == "GROUP"]
              for n in g.node_tree.nodes if n.type == "TEX_IMAGE" and n.image}
    has_lettering = any("tirebomb" in i.lower() for i in images)
    check("%s (%s): lettering texture %s" % (name, lettering, "used" if lettering == "Brand" else "absent"),
          has_lettering == (lettering == "Brand"), sorted(i.rsplit("/", 1)[-1] for i in images if i)[:8])
    lib_size = size(lib[0].all_objects)
    check("%s (%s): same outer size as the stock tire" % (name, lettering),
          stock_size and lib_size and all(abs(a - b) < 0.03 for a, b in zip(sorted(stock_size)[1:], sorted(lib_size)[1:])),
          {"Stock": stock_size, "Library": lib_size})

status = bpy.ops.object.ans_garage_tire(root=root.name, tire="Stock", lettering="Plain")
check("Back to stock: library tires removed, stock shown",
      status == {"FINISHED"} and not [c for c in root.children_recursive if c.get("ans_garage_library_tire")]
      and not any(c.hide_viewport for c in stock))
bpy.ops.object.ans_garage_tire(root=root.name, tire="Toyo Tires Proxes R888R", lettering="Brand")
out_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out_dir / "tires.blend"))
result = {"Checks": checks, "Passed": sum(c["Passed"] for c in checks), "Failed": sum(not c["Passed"] for c in checks)}
(out_dir / "tires.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
print("PASSED", result["Passed"], "FAILED", result["Failed"])
if result["Failed"]:
    raise SystemExit(1)
