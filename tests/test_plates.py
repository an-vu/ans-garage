"""License plate library and plate text on a freshly imported car (factory settings).
blender --background --factory-startup --python-exit-code 1 --python test_plates.py -- <addon parent dir> <export dir> <plate library dir> <out dir>
"""
import importlib
import json
import sys
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, export, library, out_dir = Path(args[0]), Path(args[1]), Path(args[2]), Path(args[3])
out_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
sys.path.insert(0, str(addon_parent))
addon = importlib.import_module("ans_garage")
addon.register()
checks = []


def check(name, ok, detail=None):
    checks.append({"Check": name, "Passed": bool(ok), **({"Detail": detail} if detail is not None else {})})
    print(("PASS " if ok else "FAIL ") + name + ("" if detail is None else "  " + json.dumps(detail, ensure_ascii=False)[:600]))


P = addon.plates_module()
index = P.load_index(library)
keys = [p["Key"] for p in index["Plates"]]
groups = {}
for p in index["Plates"]:
    groups[p["Group"]] = groups.get(p["Group"], 0) + 1
check("Plate library: 50 US states and the chosen extras", groups.get("US states") == 51 and "newjersey" in keys
      and not any(k.startswith(("animated", "nfs", "infinity")) for k in keys), groups)

addon.import_manifest(str(export / "manifest.json"))
root = next(c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path"))
bpy.context.scene["ans_garage_plate_library"] = str(library)
slots = P.plate_slots(root)
check("Car has license plate slots", len(slots) > 0, len(slots))


def plate_state():
    """{(object, slot): (built, plate textures, text values)} of every plate slot."""
    state = {}
    for o, i in slots:
        m = o.material_slots[i].material
        built = bool(m and m.get("unbound_surface_profile"))
        images = set()
        if m and m.node_tree:
            for g in P._addon().surfaces_module().profiles_module().group_nodes(m.node_tree):
                if g.type == "TEX_IMAGE" and g.image and "licenseplate_" in g.image.name.lower():
                    images.add(g.image.name.lower())
        evidence = json.loads(m.get("unbound_surface_evidence_json", "{}")) if m else {}
        text = [a["Value"] for a in evidence.get("Parameters", evidence.get("AppliedParameters", []))
                if isinstance(a, dict) and a.get("Parameter", "").startswith("Ext_LicensePlateText")]
        state[(o.name, i)] = (built, sorted(images), text)
    return state


report_name = bpy.context.scene["unbound_surface_report"]
stock = plate_state()
check("Every plate slot built", all(s[0] for s in stock.values()), sum(s[0] for s in stock.values()))
blank = P._addon().surfaces_module().profiles_module().plate_text_values("")
check("Default plate text is blank (cell 36 everywhere)", blank == {"Ext_LicensePlateText1": [36.0] * 4,
                                                                   "Ext_LicensePlateText2": [36.0] * 3})
values = P._addon().surfaces_module().profiles_module().plate_text_values("an5 grg")
check("Typed text maps to the plate font cells", values == {"Ext_LicensePlateText1": [10.0, 23.0, 5.0, 36.0],
                                                            "Ext_LicensePlateText2": [16.0, 27.0, 16.0]}, values)

ok = bpy.ops.object.ans_garage_plate_text(root=root.name, text="an5 grg") == {"FINISHED"}
after_text = plate_state()
check("Plate text applied and rebuilt", ok and root.get("ans_garage_plate_text") == "AN5 GRG"
      and all(s[0] for s in after_text.values())
      and all(json.loads(o["unbound_parameter_overrides_json"]) == values for o, _ in slots), root.get("ans_garage_plate_text"))

ok = bpy.ops.object.ans_garage_plate(root=root.name, plate="california") == {"FINISHED"}
cal = plate_state()
check("California on every plate", ok and all(s[0] and "licenseplate_california_d.dds" in s[1] for s in cal.values()),
      sorted({tuple(s[1]) for s in cal.values()}))
check("Plate text kept when the background changes",
      all(json.loads(o["unbound_parameter_overrides_json"]) == values for o, _ in slots))

ok = bpy.ops.object.ans_garage_plate(root=root.name, plate="japanese01") == {"FINISHED"}
jp = plate_state()
check("Japanese plate on every plate", ok and all("licenseplate_japanese01_d.dds" in s[1] and
                                                  "licenseplate_california_d.dds" not in s[1] for s in jp.values()))

ok = bpy.ops.object.ans_garage_plate(root=root.name, plate="Stock") == {"FINISHED"}
back = plate_state()
check("Stock brings the car's own plate back", ok and root.get("ans_garage_plate") == "Stock"
      and all(s[1] == stock[k][1] for k, s in back.items()))
check("The car's surface report stays current (plate rebuilds don't replace it)",
      bpy.context.scene["unbound_surface_report"] == report_name, bpy.context.scene["unbound_surface_report"])

result = {"Version": ".".join(map(str, addon.bl_info["version"])), "Checks": checks,
          "Passed": sum(c["Passed"] for c in checks), "Failed": sum(not c["Passed"] for c in checks)}
(out_dir / "plates.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
print("PASSED", result["Passed"], "FAILED", result["Failed"])
if result["Failed"]:
    raise SystemExit(1)
