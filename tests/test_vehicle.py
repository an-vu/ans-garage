"""Fresh import of any exported vehicle (factory settings): names, assembly, switching, materials.
blender --background --factory-startup --python-exit-code 1 --python test_vehicle.py -- <addon parent dir> <export dir> <out dir> <label>
"""
import importlib
import json
import time
import sys
from collections import Counter
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, export, out_dir, label = Path(args[0]), Path(args[1]), Path(args[2]), args[3]
bpy.ops.wm.read_factory_settings(use_empty=True)
sys.path.insert(0, str(addon_parent))
addon = importlib.import_module("ans_garage")
assert Path(addon.__file__).resolve().parent.parent == addon_parent.resolve(), addon.__file__
addon.register()
checks = []


def check(name, ok, detail=None):
    checks.append({"Check": name, "Passed": bool(ok), **({"Detail": detail} if detail is not None else {})})
    print(("PASS " if ok else "FAIL ") + name + ("" if detail is None else "  " + json.dumps(detail, ensure_ascii=False)[:600]))


check("Add-on 1.0.1", addon.bl_info["version"] == (1, 0, 1))
started = time.perf_counter()
status = bpy.ops.import_scene.ans_garage_vehicle(filepath=str(export / "manifest.json"))
import_seconds = time.perf_counter() - started
check("Import operator finished", status == {"FINISHED"}, {"Status": list(status), "Seconds": round(import_seconds, 1)})
imp = bpy.data.texts.get("An's Garage import report")
print("IMPORT REPORT", (imp.as_string()[:4000] if imp else "none"))
if not any(c.get("unbound_assembly_path") for c in bpy.context.scene.collection.children):
    bpy.ops.wm.save_as_mainfile(filepath=str(out_dir / ("vehicle-%s-unassembled.blend" % label)))
report = json.loads(bpy.data.texts[bpy.context.scene["unbound_surface_report"]].as_string())
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
root = next((c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path")), None)
check("Vehicle assembled", root is not None, root.name if root else None)
groups = [g for g in (root.children if root else []) if g.get("unbound_choice_group")]
names = {g.get("unbound_label", g.name): [v.get("unbound_label", v.name) for v in g.children if "unbound_option" in v]
         for g in groups}
check("Parts listed under in-game category names", groups and all(g.get("unbound_label") for g in groups), names)
presets = list(json.loads(root["unbound_presets_json"])) if root else []
check("Presets named", True, presets)
ok, switched = True, 0
for preset in presets:
    ok &= bpy.ops.object.ans_garage_preset(root=root.name, preset=preset) == {"FINISHED"}
for g in groups:
    for v in [v for v in g.children if "unbound_option" in v]:
        ok &= bpy.ops.object.ans_garage_variant(root=root.name, group=g["unbound_choice_group"], option=v["unbound_option"],
                                             preset="") == {"FINISHED"}
        switched += 1
ok &= bpy.ops.object.ans_garage_preset(root=root.name, preset="Stock") == {"FINISHED"}
check("Every preset and part option switches; Stock restored", ok and addon.assembly_module().current_preset(root) == "Stock",
      {"Presets": len(presets), "Options": switched})
moving = json.loads(root.get("ans_garage_moving_parts_json") or "null") if root else None
check("Moving parts built from the source graph", moving is not None and all(c["Attached"] > 0 for c in moving["Controls"]),
      moving and {"Controls": ["%s/%s" % (c["Group"], c["Label"]) for c in moving["Controls"]], "Issues": moving["Issues"],
                  "Skipped": [x["Control"] for x in moving["Skipped"]]})
if moving and moving["Controls"]:
    ctrl = bpy.data.objects[root["ans_garage_controls"]]
    bones = [(a, pb) for a in bpy.data.objects if a.type == "ARMATURE" for pb in a.pose.bones
             if any(c.name == "An's Garage moving part" for c in pb.constraints)]
    items = [o for o in root.all_objects if o.get("ans_garage_rest_matrix_json")]

    def state():
        ctrl.update_tag()
        bpy.context.view_layer.update()
        return [a.matrix_world @ pb.matrix for a, pb in bones] + [o.matrix_world.copy() for o in items]

    def apart(a, b):
        return max(abs(x - y) for m, n in zip(a, b) for r, q in zip(m, n) for x, y in zip(r, q))

    for c in moving["Controls"]:
        ctrl[c["Key"]] = 0.0
    closed = state()
    # At 0 the rig must reproduce the imported car exactly: bones as with their constraints muted, items at their
    # recorded rest matrices.
    for a, pb in bones:
        for con in pb.constraints:
            con.mute = con.name == "An's Garage moving part"
    unrigged = state()
    for a, pb in bones:
        for con in pb.constraints:
            con.mute = False
    rest_items = [json.loads(o["ans_garage_rest_matrix_json"]) for o in items]
    error = max([apart(closed[:len(bones)], unrigged[:len(bones)])] +
                [apart([o.matrix_world], [m]) for o, m in zip(items, rest_items)] + [0.0])
    check("Sliders at 0 leave the car as imported", error < 1e-4, {"MaxDifference": error, "Bones": len(bones), "Items": len(items)})
    moved = {}
    for c in moving["Controls"]:
        ctrl[c["Key"]] = 1.0
        moved[c["Label"]] = round(apart(state(), closed), 3)
        ctrl[c["Key"]] = 0.0
    state()
    check("Every slider moves its parts", all(v > 0.01 for v in moved.values()), moved)
s = report["Summary"]
check("No surface build issues", s["IssueSlots"] == 0, s["IssueReasons"])
visible = [o for o in meshes if o.visible_get() and o.get("unbound_mesh_id")]
occupied = [(o, i) for o in visible for i in sorted({p.material_index for p in o.data.polygons})]
by_shader, unbuilt = {}, Counter()
for o, i in occupied:
    m = o.material_slots[i].material
    st = json.loads(m.get("unbound_source_json", "{}")) if m else {}
    sh = (((st.get("Shader") or {}).get("Asset")) or m.get("unbound_shader") or "?").rsplit("/", 1)[-1] if m else "none"
    built = bool(m and m.get("unbound_surface_profile"))
    by_shader.setdefault(sh, [0, 0])[0] += 1
    by_shader[sh][1] += built
    if not built:
        why = next((u["Reason"] for u in report["Unsupported"] if u.get("Object") == o.name and u.get("Slot") == i),
                   next((x["Issue"] for x in report["Issues"] if x.get("Object") == o.name), "no report"))
        unbuilt[sh + ": " + why[:200]] += 1
built = sum(b for _, b in by_shader.values())
check("Visible surfaces built", True, {"Visible": len(occupied), "Built": built, "ByShader(visible,built)": by_shader})
check("Visible unbuilt surfaces (reasons)", True, dict(unbuilt))
saved = out_dir / ("vehicle-%s.blend" % label)
bpy.ops.wm.save_as_mainfile(filepath=str(saved))
result = {"Version": "1.0.1", "Vehicle": root.name if root else None, "Checks": checks, "Summary": s,
          "Passed": sum(c["Passed"] for c in checks), "Failed": sum(not c["Passed"] for c in checks)}
(out_dir / ("vehicle-%s.json" % label)).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
print("PASSED", result["Passed"], "FAILED", result["Failed"])
if result["Failed"]:
    raise SystemExit(1)
