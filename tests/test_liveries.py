"""Stock liveries exported with a car (headless: export.ps1 liveries <export> all), on a fresh import (factory settings).
blender --background --factory-startup --python-exit-code 1 --python test_liveries.py -- <addon parent dir> <export dir> <plate library dir> <out dir>
"""
import importlib
import json
import sys
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, export, plates, out_dir = Path(args[0]), Path(args[1]), Path(args[2]), Path(args[3])
out_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene["ans_garage_shared_parts"] = str(Path(args[1]).parent)  # the test exports folder: shader textures and libraries
sys.path.insert(0, str(addon_parent))
addon = importlib.import_module("ans_garage")
addon.register()
L = addon.liveries_module()
P = addon.surfaces_module().profiles_module()
checks = []


def check(name, ok, detail=None):
    checks.append({"Check": name, "Passed": bool(ok), **({"Detail": detail} if detail is not None else {})})
    print(("PASS " if ok else "FAIL ") + name + ("" if detail is None else "  " + json.dumps(detail, ensure_ascii=False)[:600]))


addon.import_manifest(str(export / "manifest.json"))
root = next(c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path"))
index = L.load_index(root)
check("Exported liveries listed", index and len(index["Liveries"]) >= 1, [l["Label"] for l in (index or {}).get("Liveries", [])])
slots = L.livery_slots(root, index["Parameters"]["Diffuse"])
check("Paint slots that take a livery", len(slots) > 0, len(slots))


def images(o, i):
    m = o.material_slots[i].material
    return {n.image.get("unbound_asset", "").lower() for n in P.group_nodes(m.node_tree) if n.type == "TEX_IMAGE" and n.image} if m else set()


def state():
    return {(o.name, i): (bool(o.material_slots[i].material and o.material_slots[i].material.get("unbound_surface_profile")),
                          images(o, i)) for o, i in slots}


def skipped(key):
    """Reason recorded when this slot's shader can't take the livery (it keeps its stock look)."""
    m = bpy.data.objects[key[0]].material_slots[key[1]].material
    return json.loads(m.get("unbound_surface_evidence_json", "{}")).get("LiveryNotApplied") if m else None


clean = state()
check("Paint built before (stock, no livery texture)", all(b for b, _ in clean.values())
      and not any("staticliveries" in a for _, im in clean.values() for a in im))
report_name = addon.surfaces_module().last_report()

# A plate on the rear bumper first: the livery must not remove it (same object can hold both).
bpy.context.scene["ans_garage_shared_parts"] = str(plates.parent)
bpy.ops.object.ans_garage_plate(root=root.name, plate="california")
livery = index["Liveries"][0]
ok = bpy.ops.object.ans_garage_livery(root=root.name, livery=livery["Key"], pick=False) == {"FINISHED"}
on = state()
with_livery = {k for k, (b, im) in on.items() if b and livery["Diffuse"].lower() in im}
without = {k: skipped(k) for k in on if k not in with_livery}
check("Livery applied on every slot that can take it; the rest built stock with the reason recorded",
      ok and len(with_livery) > len(without) and all(on[k][0] and r for k, r in without.items()),
      {"Livery": livery["Label"], "WithLivery": len(with_livery), "Stock": len(without),
       "Reasons": sorted({(r or {}).get("Reason", "none")[:100] for r in without.values()})})
check("Livery material texture used too", all(livery["Material"].lower() in on[k][1] for k in with_livery))
plate_objs = {o.name for o, _ in addon.plates_module().plate_slots(root)}
both = [o for o, _ in slots if o.name in plate_objs]
check("Plate kept on parts that also carry the livery", all(
    json.loads(o["unbound_texture_overrides_json"]).get("Ext_T_LicensePlate_Diffuse") for o in both), len(both))
if len(index["Liveries"]) > 1:
    other = index["Liveries"][1]
    bpy.ops.object.ans_garage_livery(root=root.name, livery=other["Key"], pick=False)
    swapped = state()
    check("Switching to another livery", all(other["Diffuse"].lower() in swapped[k][1] and livery["Diffuse"].lower() not in swapped[k][1]
                                             for k in with_livery))
with_car = next((l for l in index["Liveries"] if (l.get("Car") or {}).get("Paint")), None)
check("A livery carries its car template's paint (AI/rival setups)", with_car is not None,
      [(l["Label"], l.get("Car")) for l in index["Liveries"]])
if with_car:
    bpy.ops.object.ans_garage_livery(root=root.name, livery=with_car["Key"], pick=False)
    ok = bpy.ops.object.ans_garage_livery_car(root=root.name) == {"FINISHED"}
    scope = addon.car_scope(root)
    paint = [round(v, 4) for v in next(n for n in P.runtime_group(scope, "Ext_Carpaint_Diffuse").nodes if n.type == "RGB").outputs[0].default_value[:3]]
    finish = [round(v, 4) for v in next(n for n in P.runtime_group(scope, "Ext_Carpaint_Material").nodes if n.type == "RGB").outputs[0].default_value[:3]]
    car = with_car["Car"]
    check("Use its paint: colour, finish and plate text from the template", ok and paint == [round(v, 4) for v in car["Paint"][:3]]
          and finish == [round(v, 4) for v in car["Finish"][:3]]
          and (not car.get("PlateText") or root.get("ans_garage_plate_text") == addon.plates_module().clean_text(car["PlateText"])),
          {"Paint": paint, "Finish": finish, "Plate": root.get("ans_garage_plate_text"), "Template": car})
ok = bpy.ops.object.ans_garage_livery(root=root.name, livery="None", pick=False) == {"FINISHED"}
back = state()
check("None brings the stock paint back", ok and root.get("ans_garage_livery") == "None"
      and all(b and not any("staticliveries" in a for a in im) for b, im in back.values()))
check("Plate still there after removing the livery", all(
    json.loads(o.get("unbound_texture_overrides_json", "{}")).get("Ext_T_LicensePlate_Diffuse") for o in both))
check("The car's surface report stays current", addon.surfaces_module().last_report() is report_name)

result = {"Version": ".".join(map(str, addon.bl_info["version"])), "Checks": checks,
          "Passed": sum(c["Passed"] for c in checks), "Failed": sum(not c["Passed"] for c in checks)}
(out_dir / "liveries.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
print("PASSED", result["Passed"], "FAILED", result["Failed"])
if result["Failed"]:
    raise SystemExit(1)
