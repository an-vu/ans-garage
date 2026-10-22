"""Paint colour and finish controls, per car, on two freshly imported cars (factory settings).
blender --background --factory-startup --python-exit-code 1 --python test_paint.py -- <addon parent dir> <export dir> <second export dir> <out dir>
"""
import importlib
import json
import sys
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, first, second, out_dir = Path(args[0]), Path(args[1]), Path(args[2]), Path(args[3])
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


def rgb(scope, name):
    g = P.runtime_group(scope, name)
    return [round(v, 6) for v in next(n for n in g.nodes if n.type == "RGB").outputs[0].default_value[:3]] if g else None


addon.import_manifest(str(first / "manifest.json"))
addon.import_manifest(str(second / "manifest.json"))
roots = [c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path")]
scopes = [addon.car_scope(r) for r in roots]
check("Two cars imported", len(roots) == 2 and len(set(scopes)) == 2, scopes)
a, b = scopes
check("Each car has its own paint colour and finish controls",
      all(P.runtime_group(s, n) for s in scopes for n in ("Ext_Carpaint_Diffuse", "Ext_Carpaint_Material")),
      [g.name for g in bpy.data.node_groups if g.get("unbound_live_scope")])
paint_users = {s: {n.id_data.name for g in bpy.data.node_groups if g.get("unbound_profile_identity")
                   for n in g.nodes if n.type == "GROUP" and n.node_tree == P.runtime_group(s, "Ext_Carpaint_Diffuse")}
               for s in scopes}
check("Paint groups are used only by their own car's surfaces", all(paint_users.values())
      and not (paint_users[a] & paint_users[b]), {s: len(u) for s, u in paint_users.items()})

before_b = rgb(b, "Ext_Carpaint_Diffuse")
g = P.runtime_group(a, "Ext_Carpaint_Diffuse")
next(n for n in g.nodes if n.type == "RGB").outputs[0].default_value = (0.1, 0.2, 0.9, 1.0)
check("Repainting one car leaves the other alone", rgb(a, "Ext_Carpaint_Diffuse") == [0.1, 0.2, 0.9]
      and rgb(b, "Ext_Carpaint_Diffuse") == before_b, [rgb(a, "Ext_Carpaint_Diffuse"), rgb(b, "Ext_Carpaint_Diffuse")])

now, stock = P.finish_value(a)
check("Stock finish read from the car's data", now == stock, {"Now": now, "Stock": stock})
P.set_finish(a, finish="9")
P.set_finish(a, gloss="2")
now, _ = P.finish_value(a)
check("Finish and gloss set (Forged carbon, Matte)", now == (9, 2), now)
check("The other car's finish is unchanged", P.finish_value(b)[0] == P.finish_value(b)[1])
P.set_finish(a, finish="Stock", gloss="Stock")
check("Stock restores the car's own finish", P.finish_value(a)[0] == stock, P.finish_value(a))
ok = bpy.ops.object.ans_garage_gloss(root=roots[0].name, gloss="1") == {"FINISHED"}
check("Gloss operator", ok and P.finish_value(a)[0][1] == 1, P.finish_value(a))
check("Finish list covers the 14 shader types", [t for t, _ in P.FINISHES] == list(range(14)))

result = {"Version": ".".join(map(str, addon.bl_info["version"])), "Checks": checks,
          "Passed": sum(c["Passed"] for c in checks), "Failed": sum(not c["Passed"] for c in checks)}
(out_dir / "paint.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
print("PASSED", result["Passed"], "FAILED", result["Failed"])
if result["Failed"]:
    raise SystemExit(1)
