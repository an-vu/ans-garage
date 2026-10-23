"""Fresh import from the install ZIP (factory settings), with negative test for missing shader defaults.
blender --background --factory-startup --python-exit-code 1 --python test_fresh.py -- <zip> <scratch dir> <export dir with shader-defaults> <export dir without shader-defaults> <out dir>
"""
import json
import shutil
import sys
import zipfile
from pathlib import Path

import bpy

args = sys.argv[sys.argv.index("--") + 1:]
archive, scratch, export_ok, export_bare, out_dir = map(Path, args[:5])
if scratch.exists():
    shutil.rmtree(scratch)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    names = z.namelist()
    z.extractall(scratch)
sys.path.insert(0, str(scratch))
import ans_garage as unbound_batch  # noqa: E402
assert Path(unbound_batch.__file__).resolve().parent.parent == scratch.resolve()
checks = []


def check(label, ok, detail=None):
    checks.append({"Check": label, "Passed": bool(ok), **({"Detail": str(detail)[:400]} if detail is not None else {})})
    print(("PASS " if ok else "FAIL ") + label + ("" if detail is None else "  " + str(detail)[:200]))


def report():
    return unbound_batch.surfaces_module().last_report()


ADDON_FILES = ["__init__.py", "greetings.txt", "shader_profiles.json.gz", "unbound_animation.py", "unbound_assembly.py",
               "unbound_liveries.py", "unbound_materials.py", "unbound_plates.py", "unbound_profiles.py", "unbound_rims.py",
               "unbound_surfaces.py", "unbound_tires.py", "unbound_wheels.py"]
check("Install ZIP has exactly the add-on files", sorted(names) == ["ans_garage/" + n for n in ADDON_FILES], names)
VERSION = ".".join(map(str, unbound_batch.bl_info["version"]))
check("Installed version matches the ZIP's name", Path(args[0]).stem.endswith("-" + VERSION), VERSION)

# Negative case first: export without shader-defaults must fail closed with an explicit reason.
bpy.ops.wm.read_factory_settings(use_empty=True)
unbound_batch.register()
status = bpy.ops.import_scene.ans_garage_vehicle(filepath=str(export_bare / "manifest.json"))
r = report()
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
check("Bare export imports geometry (593 meshes)", status == {"FINISHED"} and len(meshes) == 593, len(meshes))
missing = [i for i in r["Issues"] if "Shader default texture not exported" in i.get("Issue", "")]
check("Missing shader defaults fail closed with explicit reason", missing and r["Summary"]["IssueSlots"] == len(missing),
      r["Summary"]["IssueReasons"])
check("Swatch-dependent opaque surfaces not connected without shader defaults",
      r["Summary"]["BuiltByShader"].get("cs_pbr_opaque_max", 0) == 0, r["Summary"]["BuiltByShader"])
status = bpy.ops.import_scene.ans_garage_locate_shader_defaults(filepath=str(export_ok / "shader-defaults" / "textures.json"))
r = report()
check("Locate shader default textures operator recovers the build", status == {"FINISHED"} and r["Summary"]["IssueSlots"] == 0
      and r["Summary"]["BuiltByShader"].get("cs_pbr_opaque_max", 0) > 0, r["Summary"])
unbound_batch.unregister()

# Normal fresh import.
bpy.ops.wm.read_factory_settings(use_empty=True)
unbound_batch.register()
status = bpy.ops.import_scene.ans_garage_vehicle(filepath=str(export_ok / "manifest.json"))
r = report()
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
check("Fresh import operator finished", status == {"FINISHED"})
check("All 593 source and assembled meshes imported", len(meshes) == 593, len(meshes))
check("Original slots / per-face assignments", all("unbound_material_slot" in o and o.data.materials and
      all(p.material_index == o["unbound_material_slot"] for p in o.data.polygons) for o in meshes))
check("No surface build issues", r["Summary"]["IssueSlots"] == 0, r["Summary"]["IssueReasons"])
root = next((c for c in bpy.context.scene.collection.children if c.get("unbound_assembly_path")), None)
check("Vehicle assembled", root is not None)
visible = [o for o in meshes if o.visible_get()]
occupied = [(o, o["unbound_material_slot"]) for o in visible]
built = [(o, i) for o, i in occupied if o.material_slots[i].material and o.material_slots[i].material.get("unbound_surface_profile")]
by_shader = {}
for o, i in occupied:
    m = o.material_slots[i].material
    sh = (m.get("unbound_shader") or "").rsplit("/", 1)[-1]
    by_shader.setdefault(sh, [0, 0])[0] += 1
    if m.get("unbound_surface_profile"):
        by_shader[sh][1] += 1
check("Visible assembled surfaces", True, {"Visible": len(visible), "Built": len(built), "ByShader(visible,built)": by_shader})
paint = [o for o, i in occupied if (o.material_slots[i].material.get("unbound_shader") or "").endswith("carpaint_max")]
check("All visible paint surfaces built", paint and all(o.material_slots[o["unbound_material_slot"]].material.get("unbound_surface_profile") for o in paint), len(paint))
opaque = [o for o, i in occupied if (o.material_slots[i].material.get("unbound_shader") or "").endswith("opaque_max")]
check("All visible opaque surfaces built", opaque and all(o.material_slots[o["unbound_material_slot"]].material.get("unbound_surface_profile") for o in opaque), len(opaque))
for suffix, label in (("cs_rim", "rims"), ("caliper_LookDev", "brake calipers"), ("caliperbadge_LookDev", "caliper badges")):
    parts = [o for o, i in occupied if (o.material_slots[i].material.get("unbound_shader") or "").endswith(suffix)]
    check("All visible %s built (stock item colours, per-wheel front/rear selector)" % label,
          parts and all(o.material_slots[o["unbound_material_slot"]].material.get("unbound_surface_profile") for o in parts), len(parts))
tires = [o for o in meshes if o.get("unbound_assembled") and o.visible_get() and
         (o.material_slots[o["unbound_material_slot"]].material.get("unbound_shader") or "").endswith("tire_max_lookdev")]
check("Four assembled tires built from the compiled tire profile", len(tires) == 4 and all(
    o.material_slots[o["unbound_material_slot"]].material.get("unbound_surface_profile") for o in tires), len(tires))
saved = out_dir / "fresh.blend"
bpy.ops.wm.save_as_mainfile(filepath=str(saved))
result = {"Version": VERSION, "Checks": checks, "Summary": r["Summary"], "VisibleByShader": by_shader,
          "Passed": sum(c["Passed"] for c in checks), "Failed": sum(not c["Passed"] for c in checks)}
(out_dir / "fresh-validation.json").write_text(json.dumps(result, indent=1))
print("PASSED", result["Passed"], "FAILED", result["Failed"])
if result["Failed"]:
    raise SystemExit(1)
