"""Existing-scene validation (run on a COPY of the delivered scene).
blender --background --factory-startup <copy.blend> --python-exit-code 1 --python test_existing_full.py -- <addon parent dir> <materials.json> <out dir>
"""
import hashlib
import importlib
import json
import sys
from pathlib import Path

import bpy
import numpy as np

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, materials, out_dir = Path(args[0]), args[1], Path(args[2])
sys.path.insert(0, str(addon_parent))
addon = importlib.import_module("ans_garage")
assert Path(addon.__file__).resolve().parent.parent == addon_parent.resolve(), addon.__file__
addon.register()
checks = []


def check(label, ok, detail=None):
    checks.append({"Check": label, "Passed": bool(ok), **({"Detail": str(detail)[:500]} if detail is not None else {})})
    print(("PASS " if ok else "FAIL ") + label + ("" if detail is None else "  " + str(detail)[:200]))


def digest(mesh):
    h = hashlib.sha256()
    h.update(str((len(mesh.vertices), len(mesh.edges), len(mesh.polygons), len(mesh.loops))).encode())
    for attr in mesh.attributes:
        h.update(str((attr.name, attr.domain, attr.data_type, len(attr.data))).encode())
        if not attr.data:
            continue
        prop = next(p for p in attr.data[0].bl_rna.properties if p.identifier != "rna_type"
                    and p.type in ("INT", "FLOAT", "BOOLEAN"))
        values = np.empty(len(attr.data) * max(1, prop.array_length),
                          dtype=np.float64 if prop.type == "FLOAT" else np.int32)
        attr.data.foreach_get(prop.identifier, values)
        h.update(values.tobytes())
    values = np.empty(len(mesh.corner_normals) * 3, dtype=np.float32)
    mesh.corner_normals.foreach_get("vector", values)
    h.update(values.tobytes())
    return h.hexdigest()


def objects_state():
    return {o.name: (o.data.name if o.data else None, o.parent.name if o.parent else None,
                     tuple(tuple(round(x, 9) for x in r) for r in o.matrix_basis),
                     tuple(tuple(round(x, 9) for x in r) for r in o.matrix_parent_inverse),
                     tuple(g.name for g in o.vertex_groups), tuple(sorted(c.name for c in o.users_collection)),
                     o.hide_render, o.hide_viewport, o.hide_get(), len(o.material_slots),
                     tuple(s.link for s in o.material_slots))
            for o in bpy.context.scene.objects}


def slot_sources():
    return {o.name: tuple((s.material.get("unbound_state_key") if s.material else None) for s in o.material_slots)
            for o in bpy.context.scene.objects if o.type == "MESH"}


meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.get("unbound_mesh_id")]
baseline = {m.name: digest(m) for m in bpy.data.meshes}
before_objects = objects_state()
before_sources = slot_sources()
before_materials = {m.name for m in bpy.data.materials}
check("Development add-on 1.0.3 loaded", addon.bl_info["version"] == (1, 0, 3))
check("Baseline scene has 593 Unbound meshes", len(meshes) == 593, len(meshes))

status = bpy.ops.import_scene.ans_garage_locate_export(filepath=materials)
check("Locate export manifest operator finished", status == {"FINISHED"}, status)
report = json.loads(bpy.data.texts[bpy.context.scene["unbound_surface_report"]].as_string())
summary = report["Summary"]
check("No build issues", summary["IssueSlots"] == 0, summary["IssueReasons"])
check("Car paint slots built", summary["BuiltByShader"].get("cs_pbr_carpaint_max", 0) >= 100, summary["BuiltByShader"])
check("Opaque slots built", summary["BuiltByShader"].get("cs_pbr_opaque_max", 0) >= 140, summary["BuiltByShader"])
check("Mesh data unchanged (topology, attributes, UVs, colours, normals, material indices)",
      {m.name: digest(m) for m in bpy.data.meshes} == baseline)
check("Objects unchanged (data, parent, transforms, groups, collections, visibility, slot links)",
      objects_state() == before_objects)
after_sources = slot_sources()
check("Every slot keeps its original source material identity", after_sources == before_sources)
built = [m for m in bpy.data.materials if m.get("unbound_surface_profile") == "unbound-compiled-gbuffer-v1"]
check("Built materials have a connected active output",
      all(any(n.type == "OUTPUT_MATERIAL" and n.is_active_output and n.inputs["Surface"].is_linked
              for n in m.node_tree.nodes) for m in built), len(built))
check("Original source materials still present", before_materials <= {m.name for m in bpy.data.materials})
paint = bpy.data.node_groups.get("Unbound | Runtime Ext_Carpaint_Diffuse")
rgb = next((n for n in paint.nodes if n.type == "RGB"), None) if paint else None
check("Runtime paint control from RaceVehicleItemData.DefaultPaint",
      rgb is not None and np.allclose(rgb.outputs[0].default_value[:3], (0.767768741, 0.399131775, 0.00345915067), atol=1e-6),
      tuple(rgb.outputs[0].default_value) if rgb else None)
visible = [o for o in meshes if o.visible_get()]
occupied = [(o, i) for o in visible for i in sorted({p.material_index for p in o.data.polygons})]
connected = [(o, i) for o, i in occupied if o.material_slots[i].material and
             o.material_slots[i].material.get("unbound_surface_profile")]
check("Visible assembled slots counted", True, {"VisibleObjects": len(visible), "OccupiedSlots": len(occupied),
                                                "Connected": len(connected)})
from collections import Counter
unbuilt = Counter()
for o, i in occupied:
    m = o.material_slots[i].material
    if not (m and m.get("unbound_surface_profile")):
        st = next((u for u in report["Unsupported"] if u["Object"] == o.name and u["Slot"] == i), None)
        unbuilt[((st or {}).get("Shader") or {}).get("Asset", "?").rsplit("/", 1)[-1] + ": " + str((st or {}).get("Reason", "no report"))[:140]] += 1
check("Visible unbuilt slots listed", True, dict(unbuilt))
groups_before = {g.name for g in bpy.data.node_groups}
mats_before = {m.name for m in bpy.data.materials}
status = bpy.ops.object.ans_garage_build_materials()
report2 = json.loads(bpy.data.texts[bpy.context.scene["unbound_surface_report"]].as_string())
check("Repeat build is idempotent (no new materials or groups)",
      status == {"FINISHED"} and {m.name for m in bpy.data.materials} == mats_before
      and {g.name for g in bpy.data.node_groups} == groups_before, len(report2["AlreadyBuilt"]))

root = next(c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path"))
mat_assign = {o.name: tuple(s.material.name if s.material else None for s in o.material_slots) for o in meshes}
presets = list(json.loads(root["unbound_presets_json"]))
ok = True
for preset in presets:
    ok &= bpy.ops.object.ans_garage_preset(root=root.name, preset=preset) == {"FINISHED"}
groups = [g for g in root.children if g.get("unbound_choice_group")]
switched = 0
for g in groups:
    options = [v for v in g.children if "unbound_option" in v]
    for v in options:
        ok &= bpy.ops.object.ans_garage_variant(root=root.name, group=g["unbound_choice_group"], option=v["unbound_option"], preset="") == {"FINISHED"}
        switched += 1
ok &= bpy.ops.object.ans_garage_preset(root=root.name, preset="Stock") == {"FINISHED"}
check("Presets and every individual part option still switch", ok, {"Presets": presets, "OptionsSwitched": switched})
check("Part switching leaves built material assignments intact",
      {o.name: tuple(s.material.name if s.material else None for s in o.material_slots) for o in meshes} == mat_assign)
check("Stock preset restored", addon.assembly_module().current_preset(root) == "Stock", addon.assembly_module().current_preset(root))

saved = out_dir / "existing-validated.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(saved))
bpy.ops.wm.open_mainfile(filepath=str(saved))
check("Save/reopen keeps mesh data", {m.name: digest(m) for m in bpy.data.meshes} == baseline)
check("Save/reopen keeps built materials",
      len([m for m in bpy.data.materials if m.get("unbound_surface_profile") == "unbound-compiled-gbuffer-v1"]) == len(built))
result = {"Version": "1.0.3", "Checks": checks, "Summary": summary,
          "Passed": sum(c["Passed"] for c in checks), "Failed": sum(not c["Passed"] for c in checks)}
(out_dir / "existing-validation.json").write_text(json.dumps(result, indent=1))
print("PASSED", result["Passed"], "FAILED", result["Failed"])
if result["Failed"]:
    raise SystemExit(1)
