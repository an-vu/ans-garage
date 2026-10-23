"""Dirt, dust and wet controls on a freshly imported car (factory settings).
blender --background --factory-startup --python-exit-code 1 --python test_conditions.py -- <addon parent dir> <export dir> <out dir>
"""
import importlib
import json
import sys
import time
from pathlib import Path

import bpy

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wheel_fit  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, export, out_dir = Path(args[0]), Path(args[1]), Path(args[2])
out_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
sys.path.insert(0, str(addon_parent))
addon = importlib.import_module("ans_garage")
addon.register()
P = addon.surfaces_module().profiles_module()
checks = []


def check(name, ok, detail=None):
    checks.append({"Check": name, "Passed": bool(ok), **({"Detail": detail} if detail is not None else {})})
    print(("PASS " if ok else "FAIL ") + name + ("" if detail is None else "  " + json.dumps(detail, ensure_ascii=False)[:600]))


def built_slots():
    """{(object, slot): (material, condition groups used)} of every built slot."""
    state = {}
    for o in bpy.context.scene.objects:
        if o.type != "MESH" or not o.get("unbound_mesh_id"):
            continue
        for i, s in enumerate(o.material_slots):
            m = s.material
            if s.link == "OBJECT" and m and m.get("unbound_surface_profile"):
                groups = {n.node_tree.get("unbound_condition") for n in P.group_nodes(m.node_tree)
                          if n.type == "GROUP" and n.node_tree.get("unbound_condition")}
                state[(o.name, i)] = (m.name, groups)
    return state


def evidence(state, key):
    o = bpy.data.objects[key[0]]
    return json.loads(o.material_slots[key[1]].material.get("unbound_surface_evidence_json", "{}"))


addon.import_manifest(str(export / "manifest.json"))
root = next(c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path"))
report_name = bpy.context.scene["unbound_surface_report"]
clean = built_slots()
check("Imported clean and dry: no condition controls", clean and not any(g for _, g in clean.values())
      and not bpy.context.scene.get("ans_garage_conditions"), len(clean))

bpy.ops.object.ans_garage_plate_text(root=root.name, text="DIRT 1")
started = time.time()
ok = bpy.ops.object.ans_garage_conditions(enable=True) == {"FINISHED"}
seconds = round(time.time() - started, 1)
dirty = built_slots()
with_conditions = {k: g for k, (_, g) in dirty.items() if g}
check("Every slot still built after adding the controls", ok and set(dirty) == set(clean), {"Seconds": seconds,
      "Built": len(dirty), "Before": len(clean), "Missing": sorted(map(str, set(clean) - set(dirty)))[:5]})
check("Paint, body and lens surfaces read the controls",
      len(with_conditions) > 0 and set().union(*with_conditions.values()) == set(P.CONDITIONS),
      {"Slots": len(with_conditions), "Parameters": sorted(set().union(*with_conditions.values()))})
fallback = {}
for k in dirty:
    status = evidence(dirty, k).get("VehicleCondition") or {}
    if status.get("Status", "").startswith("not applied"):
        fallback[status["Reason"][:120]] = fallback.get(status["Reason"][:120], 0) + 1
check("Slots that can't take the controls stay built clean, with the reason recorded",
      sum(fallback.values()) < len(with_conditions), fallback)
key = next(iter(with_conditions))
record = evidence(dirty, key).get("VehicleCondition")
check("Surface evidence records the condition values", record and record["Parameters"], record)
check("Plate text kept through the rebuild", root.get("ans_garage_plate_text") == "DIRT 1")
# Only visible parts are rebuilt; a hidden part option catches up when it is shown.
S = addon.surfaces_module()
hidden_stale = S.stale_condition_slots(root.all_objects, visible_only=False)
group = next((g for g in root.children if g.get("unbound_choice_group") and g["unbound_choice_group"] != "Rims"
              and any(o in {x for x, _ in hidden_stale} for v in g.children if v.hide_viewport for o in v.all_objects)), None)
shown = next((v for v in group.children if v.hide_viewport and "unbound_option" in v
              and any(o in {x for x, _ in hidden_stale} for o in v.all_objects)), None) if group else None
before = len([1 for o, _ in hidden_stale if shown and o in set(shown.all_objects)])
original = next((v for v in group.children if "unbound_option" in v and not v.hide_viewport), None) if group else None
ok = shown is not None and bpy.ops.object.ans_garage_variant(root=root.name, group=group["unbound_choice_group"],
                                                             option=shown["unbound_option"]) == {"FINISHED"}
check("Hidden part options catch up when shown (only visible parts are rebuilt when the controls change)",
      hidden_stale and ok and before and not S.stale_condition_slots(root.all_objects),
      {"HiddenStale": len(hidden_stale), "Shown": shown.name if shown else None, "CaughtUp": before})
if original is not None:
    bpy.ops.object.ans_garage_variant(root=root.name, group=group["unbound_choice_group"], option=original["unbound_option"])
ok, error = wheel_fit.panel_draws(addon, bpy.context)
check("The sidebar draws in full with the controls on (parts, paint, wheels stay reachable)", ok, error)
check("The car's surface report stays current", bpy.context.scene["unbound_surface_report"] == report_name)

groups = {g["unbound_condition"]: g for g in bpy.data.node_groups if g.get("unbound_condition")}
scene = bpy.context.scene
scene.ans_garage_dirt, scene.ans_garage_dust, scene.ans_garage_wet = 0.5, 0.25, 1.0
bpy.context.view_layer.update()
amounts = {n: round(g.nodes["Amount"].outputs[0].default_value, 6) for n, g in groups.items()}
check("Sliders drive the shared groups", amounts == {"Ext_DirtColor_Amt": 0.5, "Ext_DustColor_Amt": 0.25, "WaterCycle": 1.0},
      amounts)
scene.ans_garage_wet = 0.0
scene.keyframe_insert("ans_garage_wet", frame=1)
scene.ans_garage_wet = 1.0
scene.keyframe_insert("ans_garage_wet", frame=11)
played = []
for frame in (1, 6, 11):
    scene.frame_set(frame)
    played.append(round(groups["WaterCycle"].nodes["Amount"].outputs[0].default_value, 3))
check("A keyframed slider plays back (Wet 0 -> 1 over frames 1-11)", played[0] == 0.0 and 0.0 < played[1] < 1.0
      and played[2] == 1.0, played)
scene.animation_data_clear()
colours = {n: round(next(x for x in g.nodes if x.type == "VALUE" and x.name != "Amount").outputs[0].default_value, 6)
           for n, g in groups.items() if n != "WaterCycle"}
check("Dirt and dust colours are the paint shader's own", colours == {"Ext_DirtColor_Amt": 0.033105, "Ext_DustColor_Amt": 0.138955},
      colours)
wet = groups["WaterCycle"]
maths = sorted((n.operation, round(n.inputs[1].default_value, 6), round(n.inputs[2].default_value, 6))
               for n in wet.nodes if n.type == "MATH")
check("Wet follows the rising edge of the wet ramp (phase 0.6 + 0.1 x wet, 0 when dry)",
      ("MULTIPLY_ADD", 0.1, 0.6) in maths and any(m[0] == "GREATER_THAN" and m[1] == 0.0 for m in maths), maths)

ok = bpy.ops.object.ans_garage_conditions(enable=False) == {"FINISHED"}
back = built_slots()
visible = {(o.name, i) for o in bpy.context.scene.objects if o.type == "MESH" and o.visible_get() for i in range(len(o.material_slots))}
check("Removing the controls rebuilds the visible surfaces clean and dry (hidden options catch up when shown)",
      ok and set(back) == set(clean) and not any(g for k, (_, g) in back.items() if k in visible)
      and not scene.get("ans_garage_conditions"))
check("Clean visible surfaces match the import again", all(back[k][0] == clean[k][0] or back[k][0].split(".")[0] == clean[k][0].split(".")[0]
                                                           for k in clean if k in visible))

result = {"Version": ".".join(map(str, addon.bl_info["version"])), "Checks": checks, "EnableSeconds": seconds,
          "Passed": sum(c["Passed"] for c in checks), "Failed": sum(not c["Passed"] for c in checks)}
(out_dir / "conditions.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
print("PASSED", result["Passed"], "FAILED", result["Failed"])
if result["Failed"]:
    raise SystemExit(1)
