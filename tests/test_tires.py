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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wheel_fit  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, export, library, out_dir = Path(args[0]), Path(args[1]), Path(args[2]), Path(args[3])
bpy.ops.wm.read_factory_settings(use_empty=True)
sys.path.insert(0, str(addon_parent))
addon = importlib.import_module("ans_garage")
addon.register()
group_nodes = addon.surfaces_module().profiles_module().group_nodes
checks = []


def check(name, ok, detail=None):
    checks.append({"Check": name, "Passed": bool(ok), **({"Detail": detail} if detail is not None else {})})
    print(("PASS " if ok else "FAIL ") + name + ("" if detail is None else "  " + json.dumps(detail, ensure_ascii=False)[:500]))


def size(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs if o.type == "MESH" for c in o.bound_box]
    return [round(max(p[i] for p in pts) - min(p[i] for p in pts), 3) for i in range(3)] if pts else None


addon.import_manifest(str(export / "manifest.json"))
root = next(c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path"))
bpy.context.scene["ans_garage_shared_parts"] = str(library.parent)
stock = [c for c in root.children_recursive if json.loads(c.get("source_item_json", "{}")).get("Type") == "TiresItemData"]
bpy.context.view_layer.update()
stock_size = size(stock[0].all_objects) if stock else None
index = json.loads((library / "tires.json").read_text(encoding="utf-8-sig"))
data = json.loads(Path(root["unbound_assembly_path"]).read_text(encoding="utf-8-sig"))
tire_config = {n["Id"]: n for n in data["Nodes"]}[data["TireConfig"]]["Raw"]
factory_rims = addon.assembly_module().wheels.factory_rims(data)
check("Car has four stock tire instances", len(stock) == 4, len(stock))
# The game's own values, read in a frame capture (Lotus Evija rear tire, 2026-10-22): g_wheelCustomizeParam =
# (0.040105, 0.047770, 0.0, 0.091) on the small sidewall; TireConfig diameter 0.72154, rim 0.57221 x 0.345.
W = addon.assembly_module().wheels
evija = [{"InnerDiameter": 0.492, "OuterDiameter": 0.626, "Width": 0.254}, {"InnerDiameter": 0.462, "OuterDiameter": 0.626, "Width": 0.254},
         {"InnerDiameter": 0.412, "OuterDiameter": 0.626, "Width": 0.254}]
picked = W.tire_size(evija, 0.57221, 0.72154, 0.77, 0.71)
offsets = W.tire_offsets(picked, 0.72154, 0.57221, 0.345)
check("Wheel fit inputs match the game's (frame capture: Lotus Evija rear tire)", picked["InnerDiameter"] == 0.492
      and all(abs(a - b) < 2e-6 for a, b in zip(offsets, (0.047770, 0.040105, 0.091))),
      {"Size": picked["InnerDiameter"], "W.y, W.x+W.z, W.w": [round(x, 6) for x in offsets]})
brake = W.brake_scale({"Diameter": 0.57221, "BrakeDiscRatio": 0.77})
check("Brake size matches the game's (frame capture: Lotus Evija rear brake, 1.1015043)", abs(brake - 1.1015043) < 1e-6, brake)

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
    images = {(n.image.get("unbound_asset") or n.image.name) for m in mats for n in group_nodes(m.node_tree)
              if n.type == "TEX_IMAGE" and n.image}
    has_lettering = any("tirebomb" in i.lower() for i in images)
    check("%s (%s): lettering texture %s" % (name, lettering, "used" if lettering == "Brand" else "absent"),
          has_lettering == (lettering == "Brand"), sorted(i.rsplit("/", 1)[-1] for i in images if i)[:8])
    lib_size = size(lib[0].all_objects)
    check("%s (%s): same outer size as the stock tire" % (name, lettering),
          stock_size and lib_size and all(abs(a - b) < 0.03 for a, b in zip(sorted(stock_size)[1:], sorted(lib_size)[1:])),
          {"Stock": stock_size, "Library": lib_size})
    # Fitted like the game's tire shader, in the sidewall size the game picks for the car's rim (the tire's thresholds).
    depsgraph = bpy.context.evaluated_depsgraph_get()
    wheel_of = {child.name: parent.name for parent in root.children_recursive for child in parent.children}
    fits = {}
    for c in lib:
        axle = "Front" if wheel_of[c.name].startswith("Front") else "Rear"
        tire = next(t for t in index["Tires"] if t["Name"] == name and t["Lettering"] == lettering and t["Position"] == "ItemPosition_" + axle)
        diameter, ratio = tire_config["Diameter" + axle], factory_rims[axle]["Diameter"] / tire_config["Diameter" + axle]
        sizes = sorted(tire["Sizes"], key=lambda x: -x["InnerDiameter"])
        expected = sizes[min(0 if ratio >= tire["SmallToMedRatio"] else 1 if ratio >= tire["MedToLargeRatio"] else 2, len(sizes) - 1)]
        for o in c.all_objects:
            if o.type == "MESH" and o.get("unbound_wheel_fit"):
                m = wheel_fit.measure(o, depsgraph)
                fits[wheel_of[c.name]] = {"FormulaError": m["FormulaError"], "Tread": round(m["Radius"][1], 4), "Target": round(diameter / 2, 4),
                                          "Mesh": o.get("ans_garage_tire_mesh", "").rsplit("/", 1)[-1],
                                          "SizeOk": o.get("ans_garage_tire_mesh", "").lower() in [x["Mesh"].lower() for x in expected["Meshes"]]}
    check("%s (%s): fitted per vertex to the car's tire size, sidewall size picked like the game" % (name, lettering),
          len(fits) == 4 and all(f["FormulaError"] < 1e-5 and abs(f["Tread"] - f["Target"]) < 0.005 and f["SizeOk"] for f in fits.values()),
          fits)

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
