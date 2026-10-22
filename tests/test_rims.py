"""Rim library (real aftermarket brands) on a freshly imported car (factory settings).
blender --background --factory-startup --python-exit-code 1 --python test_rims.py -- <addon parent dir> <export dir> <rim library dir> <out dir>
"""
import importlib
import json
import sys
import time
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, export, library, out_dir = Path(args[0]), Path(args[1]), Path(args[2]), Path(args[3])
out_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
sys.path.insert(0, str(addon_parent))
addon = importlib.import_module("ans_garage")
addon.register()
R = addon.rims_module()
checks = []


def check(name, ok, detail=None):
    checks.append({"Check": name, "Passed": bool(ok), **({"Detail": detail} if detail is not None else {})})
    print(("PASS " if ok else "FAIL ") + name + ("" if detail is None else "  " + json.dumps(detail, ensure_ascii=False)[:600]))


index = R.load_index(library)
brands = sorted({r["Brand"] for r in index["Rims"]})
names = R.rim_names(index)
check("Library: real brands only", len(brands) == 16 and not any(
    k in n.lower() for n in names for k in ("turbofan", "led rims", "infinity", "panda", "bleeding", "codenine", "steel")),
    {"Brands": brands, "Models": len(names)})

addon.import_manifest(str(export / "manifest.json"))
root = next(c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path"))
bpy.context.scene["ans_garage_rim_library"] = str(library)
factory = next(c for c in root.children if c.get("unbound_choice_group") == "Rims")


def library_rims():
    return [c for c in root.children_recursive if c.get("ans_garage_library_rim")]


def visible(c):
    return not c.hide_viewport


for name in ("BBS LM", "Work Meister S1"):
    started = time.time()
    ok = bpy.ops.object.ans_garage_rim(root=root.name, rim=name, pick=False) == {"FINISHED"}
    rims = library_rims()
    objs = [o for c in rims for o in c.all_objects if o.type == "MESH"]
    built = [o.material_slots[i].material for o in objs for i in {f.material_index for f in o.data.polygons}
             if i < len(o.material_slots) and o.material_slots[i].material]
    check("%s on all four wheels" % name, ok and len(rims) == 4 and not visible(factory)
          and all(o.parent and "Rotation" in o.parent.name for c in rims for o in c.objects if o.parent is None or "Rotation" in o.parent.name),
          {"Instances": len(rims), "Seconds": round(time.time() - started, 1)})
    check("%s: surfaces built from the compiled shaders" % name, built and all(m.get("unbound_surface_profile") for m in built),
          sorted({m.name for m in built})[:4])
    check("%s: scaled to the factory rim size" % name, all("scaled to the factory rim" in c.get("dimension_status", "") for c in rims),
          rims[0].get("dimension_status") if rims else None)
paint = R.rim_paint(root)
check("Rim colors are live per car (primary/secondary, front/rear)", len(paint) >= 2, [label for label, _ in paint])
if paint:
    stock = [tuple(round(v, 4) for v in s.default_value[:3]) for _, s in paint]
    for _, s in paint:
        s.default_value = (0.9, 0.1, 0.1, 1.0)
    rim_groups = {n.node_tree for c in library_rims() for o in c.all_objects if o.type == "MESH" for sl in o.material_slots
                  if sl.material for n in addon.surfaces_module().profiles_module().group_nodes(sl.material.node_tree)
                  if n.type == "GROUP" and n.node_tree and n.node_tree.get("unbound_live_field", "").endswith("ColorParameter")
                  and "Rim" in n.node_tree.get("unbound_live_field", "")}
    check("Library rims read the car's rim colors", len(rim_groups) >= 1, sorted(g.name for g in rim_groups))
    bpy.ops.object.ans_garage_rim_paint_stock(root=root.name)
    check("Stock rim colors restored", [tuple(round(v, 4) for v in s.default_value[:3]) for _, s in paint] == stock)
ok = bpy.ops.object.ans_garage_rim(root=root.name, rim="Stock", pick=False) == {"FINISHED"}
check("Stock brings the car's own wheel set back", ok and not library_rims() and visible(factory) and root.get("ans_garage_rim") == "Stock")

result = {"Version": ".".join(map(str, addon.bl_info["version"])), "Checks": checks,
          "Passed": sum(c["Passed"] for c in checks), "Failed": sum(not c["Passed"] for c in checks)}
(out_dir / "rims.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
print("PASSED", result["Passed"], "FAILED", result["Failed"])
if result["Failed"]:
    raise SystemExit(1)
