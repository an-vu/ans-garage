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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wheel_fit  # noqa: E402

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, export, out_dir, label = Path(args[0]), Path(args[1]), Path(args[2]), args[3]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene["ans_garage_shared_parts"] = str(Path(args[1]).parent)  # the test exports folder: shader textures and libraries
sys.path.insert(0, str(addon_parent))
addon = importlib.import_module("ans_garage")
assert Path(addon.__file__).resolve().parent.parent == addon_parent.resolve(), addon.__file__
addon.register()
checks = []


def check(name, ok, detail=None):
    checks.append({"Check": name, "Passed": bool(ok), **({"Detail": detail} if detail is not None else {})})
    print(("PASS " if ok else "FAIL ") + name + ("" if detail is None else "  " + json.dumps(detail, ensure_ascii=False)[:600]))


VERSION = ".".join(map(str, addon.bl_info["version"]))
started = time.perf_counter()
bpy.context.scene.render.fps, bpy.context.scene.render.fps_base = 25, 1.0
status = bpy.ops.import_scene.ans_garage_vehicle(filepath=str(export / "manifest.json"))
import_seconds = time.perf_counter() - started
check("Import operator finished", status == {"FINISHED"}, {"Status": list(status), "Seconds": round(import_seconds, 1)})
check("The scene keeps its frame rate and no staging scene is left", bpy.context.scene.render.fps == 25
      and len(bpy.data.scenes) == 1, {"Fps": bpy.context.scene.render.fps, "Scenes": [s.name for s in bpy.data.scenes]})
if not any(c.get("unbound_assembly_path") for c in bpy.context.scene.collection.children):
    bpy.ops.wm.save_as_mainfile(filepath=str(out_dir / ("vehicle-%s-unassembled.blend" % label)))
report = addon.surfaces_module().last_report()
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
root = next((c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path")), None)
check("Vehicle assembled", root is not None, root.name if root else None)
groups = [g for g in (root.children if root else []) if g.get("unbound_choice_group")]
names = {g.get("unbound_label", g.name): [v.get("unbound_label", v.name) for v in g.children if "unbound_option" in v]
         for g in groups}
check("Parts listed under in-game category names", groups and all(g.get("unbound_label") for g in groups), names)
presets = list(json.loads(root["unbound_presets_json"])) if root else []
check("Presets named", True, presets)
def misplaced(variant):
    """Parts of a shown option that are not where the assembly placed them (moving parts closed): Blender only
    refreshes positions of shown parts, so a step that read a hidden option's stale position put it at the car's
    origin (the Aventador S's spoilers)."""
    from mathutils import Matrix
    out = []
    for inst in [variant] + list(variant.children_recursive):
        if "unbound_instance_key" not in inst:
            continue
        meshid, transform, wheel = json.loads(inst["unbound_instance_key"])
        if wheel:
            continue
        transform = Matrix([transform[i:i + 4] for i in range(0, 16, 4)])
        for o in inst.objects:
            if o.parent is not None and o.parent.name in inst.objects:
                continue
            if o.get("ans_garage_rest_moves"):
                continue  # held at the game's rest pose by the moving-parts rig (checked below)
            baseline = Matrix(json.loads(o["unbound_baseline_matrix_world"]))
            gap = ((transform @ baseline).translation - o.matrix_world.translation).length
            if gap > 1e-3:
                out.append([inst.name, o.name, round(gap, 3)])
    return out


ok, switched, wrong = True, 0, []
for preset in presets:
    ok &= bpy.ops.object.ans_garage_preset(root=root.name, preset=preset) == {"FINISHED"}
for g in groups:
    for v in [v for v in g.children if "unbound_option" in v]:
        ok &= bpy.ops.object.ans_garage_variant(root=root.name, group=g["unbound_choice_group"], option=v["unbound_option"]) == {"FINISHED"}
        bpy.context.view_layer.update()
        wrong += [[v.get("unbound_label", v.name)] + m for m in misplaced(v)]
        switched += 1
check("Every part option sits where the assembly placed it when shown", not wrong, wrong[:12])
# The sidebar's dropdowns are menus told which car and part group they are for (row context): draw them on a recorder
# and run what an entry would run.
from types import SimpleNamespace


class Recorder:
    operator_context = ""

    def __init__(self):
        self.entries = []

    def operator(self, idname, text=""):
        props = SimpleNamespace()
        self.entries.append((idname, text, props))
        return props


def menu_entries(menu, **context):
    layout = Recorder()
    getattr(bpy.types, menu).draw(SimpleNamespace(layout=layout), SimpleNamespace(**context))
    return layout


def run(entry):
    idname, _, props = entry
    category, name = idname.split(".")
    return getattr(getattr(bpy.ops, category), name)(**vars(props)) == {"FINISHED"}


group = next(g for g in groups if len([v for v in g.children if "unbound_option" in v]) > 2)
options = [v for v in group.children if "unbound_option" in v]
menu = menu_entries("ANS_GARAGE_MT_part", ans_garage_root=root, ans_garage_group=group)
check("Part dropdown lists every option of its part and runs directly", len(menu.entries) == len(options)
      and menu.operator_context == "EXEC_DEFAULT" and run(menu.entries[2]) and not options[2].hide_viewport
      and all(v.hide_viewport for i, v in enumerate(options) if i != 2), [e[1] for e in menu.entries[:4]])
menu = menu_entries("ANS_GARAGE_MT_preset", ans_garage_root=root)
check("Preset dropdown lists the car's presets; its first entry is Stock", len(menu.entries) == len(presets)
      and run(menu.entries[0]) and addon.assembly_module().current_preset(root) == "Stock", [e[1] for e in menu.entries])
menu = menu_entries("ANS_GARAGE_MT_gloss", ans_garage_root=root)
check("Paint dropdowns run directly, not through a second search window", menu.operator_context == "EXEC_DEFAULT"
      and [e[1] for e in menu.entries] == ["Stock", "Gloss", "Satin", "Matte"])
texts = [t.name for t in bpy.data.texts if t.name.startswith("An's Garage")]
check("One report text for the car, and nothing else in the Text Editor", texts == [root.get("ans_garage_report")], texts)
ok &= bpy.ops.object.ans_garage_preset(root=root.name, preset="Stock") == {"FINISHED"}
check("Every preset and part option switches; Stock restored", ok and addon.assembly_module().current_preset(root) == "Stock",
      {"Presets": len(presets), "Options": switched})
rims = next((g for g in groups if g["unbound_choice_group"] == "Rims"), None)
rim_sets = {}
for v in [v for v in (rims.children if rims else []) if "unbound_option" in v]:
    addon.assembly_module().set_variant(root, "Rims", v["unbound_option"])
    rim_sets[v["unbound_label"]] = sum(1 for c in v.children if c.get("source_item") and not v.hide_viewport)
addon.assembly_module().apply_preset(root, "Stock")
check("Each of the car's wheel sets mounts on all four wheels", rims is not None and rim_sets and all(n == 4 for n in rim_sets.values())
      and next(v for v in rims.children if "unbound_option" in v and not v.hide_viewport)["unbound_label"] == "Stock", rim_sets)
# Stock tires: the game's tire shader per vertex, at the car's tire size, in the sidewall size the game picks.
data = json.loads(Path(root["unbound_assembly_path"]).read_text(encoding="utf-8-sig"))
tire_config = {n["Id"]: n for n in data["Nodes"]}[data["TireConfig"]]["Raw"]
factory_rims = addon.assembly_module().wheels.factory_rims(data)
blueprint_of = {u["MeshId"]: u["BlueprintGuid"] for u in data["MeshUses"]}
bpy.context.view_layer.update()
depsgraph = bpy.context.evaluated_depsgraph_get()
tires, sizes_exported = {}, True
for w in data["Wheels"]:
    axle = "Front" if w["Facing"]["Front"] else "Rear"
    diameter, width = tire_config["Diameter" + axle], addon.assembly_module().wheels.rim_width(data, tire_config, axle)
    rim = factory_rims[axle]["Diameter"] if axle in factory_rims else tire_config["RimDiameter" + axle]
    wheel = next(c for c in root.children_recursive if c.name.split(".")[0] == w["Name"])
    for inst in [c for c in wheel.children if json.loads(c.get("source_item_json", "{}")).get("Type") == "TiresItemData"]:
        item = next(i for i in data["Items"] if i["Asset"] == inst["source_item"])
        infos = sorted(item["TireMeshInfos"], key=lambda x: -x["InnerDiameter"])
        ratio = rim / diameter
        expected = infos[min(0 if ratio >= item["Raw"]["SmallToMedRatio"] else 1 if ratio >= item["Raw"]["MedToLargeRatio"] else 2, len(infos) - 1)]
        sizes_exported &= all(m["MeshGuid"] in blueprint_of.values() for i in infos for m in i["Meshes"])
        for o in inst.all_objects:
            if o.type == "MESH":
                m = wheel_fit.measure(o, depsgraph) if o.get("unbound_wheel_fit") else None
                placed = next((i for i in infos if any(x["MeshGuid"] == blueprint_of.get(o.get("unbound_mesh_id")) for x in i["Meshes"])), None)
                tires[w["Name"]] = m and {"FormulaError": m["FormulaError"],
                                          "Tread": [round(m["Radius"][1], 4), round(diameter / 2, 4)],
                                          "Bead": [round(m["Radius"][0], 4), round(rim / 2, 4)],
                                          "Width": [round(m["Width"], 4), round(width, 4)],
                                          "Sidewall": [placed and placed["InnerDiameter"], expected["InnerDiameter"]]}
check("Stock tires fitted per vertex with the game's tire shader formula",
      len(tires) == len(data["Wheels"]) and all(t and t["FormulaError"] < 1e-5 for t in tires.values()), tires)
check("Stock tires at the car's tire size: tread at the diameter, bead at the rim, width at the rim width",
      tires and all(t and abs(t["Tread"][0] - t["Tread"][1]) < 0.005 and abs(t["Bead"][0] - t["Bead"][1]) < 0.005
                    and 0 <= t["Width"][0] - t["Width"][1] < 0.04 for t in tires.values()))
check("Stock tire sidewall size as the game picks it (rim/tire ratio)" + ("" if sizes_exported else ": export before 1.0.9 holds one size"),
      tires and (not sizes_exported or all(t and t["Sidewall"][0] == t["Sidewall"][1] for t in tires.values())),
      {k: t and t["Sidewall"] for k, t in tires.items()})
# Brake discs and calipers: scaled about the wheel centre by rim diameter x BrakeDiscRatio / 0.4, like the game.
import numpy as np  # noqa: E402
brakes, brake_ok = {}, True
for w in data["Wheels"]:
    axle = "Front" if w["Facing"]["Front"] else "Rear"
    rim = factory_rims.get(axle, {})
    expected = rim["Diameter"] * rim["BrakeDiscRatio"] / 0.4 if rim.get("BrakeDiscRatio") else None
    wheel = next(c for c in root.children_recursive if c.name.split(".")[0] == w["Name"])
    for inst in [c for c in wheel.children if json.loads(c.get("source_item_json", "{}")).get("Type") in ("BrakeDiscsItemData", "CalipersItemData")]:
        for o in [o for o in inst.all_objects if o.type == "MESH"]:
            co = np.empty(len(o.data.vertices) * 3); o.data.vertices.foreach_get("co", co)
            ev = o.evaluated_get(depsgraph).to_mesh(); fitted = np.empty(len(ev.vertices) * 3); ev.vertices.foreach_get("co", fitted)
            o.evaluated_get(depsgraph).to_mesh_clear()
            error = float(np.abs(fitted - co * (expected or 1.0)).max()) if fitted.shape == co.shape else float("inf")
            brake_ok &= expected is not None and abs(o.get("unbound_brake_scale", 0) - expected) < 1e-9 and error < 1e-5
            brakes.setdefault(w["Name"], []).append([o.name[:24], round(o.get("unbound_brake_scale", 0), 4), error])
check("Brake discs and calipers sized like the game (rim diameter x BrakeDiscRatio / 0.4)", brakes and brake_ok, brakes)
moving = json.loads(root.get("ans_garage_moving_parts_json") or "null") if root else None
check("Moving parts built from the source graph", moving is not None and all(c["Attached"] > 0 for c in moving["Controls"]),
      moving and {"Controls": ["%s/%s" % (c["Group"], c["Label"]) for c in moving["Controls"]], "Issues": moving["Issues"],
                  "Skipped": [x["Control"] for x in moving["Skipped"]]})
profiles_mod = addon.surfaces_module().profiles_module()
scope = addon.car_scope(root)
tint_groups = {text: profiles_mod.runtime_group(scope, field=f) for f, text in profiles_mod.TINT_FIELDS}
# Light tints only where the car's lens shaders take them (not the Evija's, Integra's or Chiron's).
check("Window tint (and headlight/taillight tints where the lenses take them) are live controls with the car's own values",
      tint_groups["Window tint"] is not None and all(g is None or g.users > 0 for g in tint_groups.values()),
      {t: (list(g["unbound_stock_value"]), g.users) if g else None for t, g in tint_groups.items()})
stance = addon.stance_module()
st_obj, st_rows = stance.controls(root), stance.sliders(root)
check("Stance sliders from the car's own data (ride height, front and rear camber)",
      st_obj is not None and {s["Key"] for s in st_rows} >= {"ride_height", "camber_front", "camber_rear"},
      [(s["Text"], s["Min"], s["Max"], s["Stock"]) for s in st_rows])
if st_obj is not None:
    from mathutils import Vector
    susp = [o for o in root.all_objects if o.get("wheel_side") and o.name.split(".")[0].endswith("| Suspension")]

    def wheel_state():
        st_obj.update_tag()  # a script setting a custom property doesn't tag it (the sidebar slider does)
        bpy.context.view_layer.update()
        return {o["wheel_side"]: (o.matrix_world.translation.copy(), (o.matrix_world.to_3x3() @ Vector((0, 0, 1))).normalized())
                for o in susp}
    stock_state = wheel_state()
    rest = {o["wheel_side"]: o.parent.matrix_world.translation.copy() for o in susp}
    check("Stance at stock leaves the wheels where the assembly put them",
          len(susp) == 4 and all((stock_state[k][0] - rest[k]).length < 1e-6 for k in stock_state),
          {k: round((stock_state[k][0] - rest[k]).length, 6) for k in stock_state})
    rows = {s["Key"]: s for s in st_rows}
    travel = -min(c["Min"] for c in rows["ride_height"]["Changes"] if c["Attribute"] == "ATM_XCarBodyYOffset")
    st_obj["ride_height"] = rows["ride_height"]["Min"]
    low = wheel_state()
    lifts = {k: round(low[k][0].z - stock_state[k][0].z, 4) for k in low}
    outs = {k: round(abs(low[k][0].x) - abs(stock_state[k][0].x), 4) for k in low}
    check("Lowest ride height: wheels rise into the body by the car's travel and move out (front 17.5 mm, rear 12.5 mm)",
          all(abs(v - travel) < 1e-4 for v in lifts.values())
          and all(abs(outs[k] - (0.0175 if "Front" in k else 0.0125)) < 1e-4 for k in outs), {"Lift": lifts, "Out": outs})
    st_obj["ride_height"] = rows["ride_height"]["Stock"]
    st_obj["camber_front"] = rows["camber_front"]["Max"]
    tilted = wheel_state()
    import math
    tops_in = {k: round(math.degrees(math.asin(max(-1, min(1, -math.copysign(1, tilted[k][0].x) * tilted[k][1].x)))), 2)
               for k in tilted}
    check("Front camber at 10: front wheel tops lean in by 0.2 rad (11.46 degrees), rear wheels unchanged",
          all(abs(v - (11.46 if "Front" in k else 0.0)) < 0.05 for k, v in tops_in.items()), tops_in)
    stance.set_stock(root)
    check("Stock button puts the stance back", wheel_state() == stock_state or all(
        (wheel_state()[k][0] - stock_state[k][0]).length < 1e-6 for k in stock_state))
if moving and moving["Controls"]:
    labels = [c["Label"] for c in moving["Controls"]]
    pairs = ["Rear wing" if l == "Airbrake" else l.replace("Left ", "").replace("Right ", "") for l in labels]
    fronts = [min(c["Y"] for c in moving["Controls"] if pairs[labels.index(c["Label"])] == p) for p in pairs]
    check("Moving parts listed front to back (where their geometry sits), each left/right pair together, left first",
          None not in [c.get("Y") for c in moving["Controls"]] and fronts == sorted(fronts)
          and all(not l.startswith("Right ") or (i and labels[i - 1] == l.replace("Right ", "Left ", 1))
                  for i, l in enumerate(labels) if "Left " + l[6:] in labels),
          [(c["Label"], c.get("Y")) for c in moving["Controls"]])
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
    # Parts whose game rest pose is their modelled one stay exactly as imported at 0; the others (the Ford GT's wing,
    # modelled raised) are moved to the rest pose the game's sequences start from.
    still_b = [i for i, (a, pb) in enumerate(bones) if not pb.get("ans_garage_rest_moves")]
    still_i = [i for i, o in enumerate(items) if not o.get("ans_garage_rest_moves")]
    error = max([apart([closed[i] for i in still_b], [unrigged[i] for i in still_b])] +
                [apart([items[i].matrix_world], [rest_items[i]]) for i in still_i] + [0.0])
    check("Sliders at 0 leave the car as imported where the game's rest pose is the modelled one", error < 1e-4,
          {"MaxDifference": error, "Bones": len(still_b), "Items": len(still_i)})
    moved = [round(apart([items[i].matrix_world], [rest_items[i]]), 3) for i in range(len(items)) if i not in still_i]
    check("Parts modelled away from their rest pose are moved to it at 0, staying on the car (under 30 cm)",
          all(1e-3 < m < 0.3 for m in moved), moved)
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
exposure = {k: n for k, n in unbuilt.items() if k.endswith("after specialization: 44.w")}
check("No visible surface left unbuilt by the camera exposure alone (a live tint falls back to the stock tint)",
      not exposure, exposure)
saved = out_dir / ("vehicle-%s.blend" % label)
bpy.ops.wm.save_as_mainfile(filepath=str(saved))
result = {"Version": VERSION, "Vehicle": root.name if root else None, "Checks": checks, "Summary": s,
          "Passed": sum(c["Passed"] for c in checks), "Failed": sum(not c["Passed"] for c in checks)}
(out_dir / ("vehicle-%s.json" % label)).write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
print("PASSED", result["Passed"], "FAILED", result["Failed"])
if result["Failed"]:
    raise SystemExit(1)
