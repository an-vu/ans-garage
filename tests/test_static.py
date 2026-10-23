"""A car exported as a static model (Frosty: Moving parts unticked) on a fresh import (factory settings).
blender --background --factory-startup --python-exit-code 1 --python test_static.py -- <addon parent dir> <export dir> <out dir>
"""
import importlib
import json
import sys
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
addon_parent, export, out_dir = Path(args[0]), Path(args[1]), Path(args[2])
out_dir.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
sys.path.insert(0, str(addon_parent))
addon = importlib.import_module("ans_garage")
addon.register()
checks = []


def check(name, ok, detail=None):
    checks.append({"Check": name, "Passed": bool(ok), **({"Detail": detail} if detail is not None else {})})
    print(("PASS " if ok else "FAIL ") + name + ("" if detail is None else "  " + json.dumps(detail, ensure_ascii=False)[:600]))


# The export's own manifest marked static, next to it (the import reads the other files beside the manifest).
manifest = json.loads((export / "manifest.json").read_text(encoding="utf-8-sig"))
manifest["MovingParts"] = False
static = export / "manifest.static-test.json"
static.write_text(json.dumps(manifest), encoding="utf-8")
try:
    count, failures = addon.import_manifest(str(static))
finally:
    static.unlink()
root = next(c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path"))
obj, controls = addon.animation_module().controls(root)
report = bpy.data.texts[root["ans_garage_report"]].as_string()
check("Static export imports without a moving-parts rig", not failures and not controls and root.get("ans_garage_static_export")
      and "exported as a static model" in report, {"Parts": count, "Failures": failures[:2], "Controls": len(controls)})
ok = bpy.ops.object.ans_garage_moving_parts(root=root.name) == {"FINISHED"}
obj, controls = addon.animation_module().controls(root)
check("Add moving parts still builds them later", ok and len(controls) > 0, [c["Label"] for c in controls])

result = {"Version": ".".join(map(str, addon.bl_info["version"])), "Checks": checks,
          "Passed": sum(c["Passed"] for c in checks), "Failed": sum(not c["Passed"] for c in checks)}
(out_dir / "static.json").write_text(json.dumps(result, indent=1, ensure_ascii=False), encoding="utf-8")
print("PASSED", result["Passed"], "FAILED", result["Failed"])
if result["Failed"]:
    raise SystemExit(1)
