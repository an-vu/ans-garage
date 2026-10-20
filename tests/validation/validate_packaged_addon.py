"""Run in background Blender; exercise the packaged add-on import operator."""
import bpy
import hashlib
import json
from pathlib import Path
import sys
import zipfile

root = Path(__import__("os").environ["UNBOUND_VALIDATION_WORKSPACE"]).resolve()
archive = root / "outputs/UnboundBlender-0.4.0.zip"
scratch = root / "work/addon-package-check"
scratch.mkdir(exist_ok=True)
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    assert set(z.namelist()) == {
        "unbound_batch/__init__.py",
        "unbound_batch/unbound_materials.py",
        "unbound_batch/unbound_assembly.py",
    }
    z.extractall(scratch)
sys.path.insert(0, str(scratch))
import unbound_batch

bpy.ops.wm.read_factory_settings(use_empty=True)
unbound_batch.register()
checks = []

def check(name, condition):
    checks.append({"Check": name, "Passed": bool(condition)})

check("Archive version", unbound_batch.bl_info["version"] == (0, 4, 0))
check("Assembly sibling module", unbound_batch.assembly_module().__file__.startswith(str(scratch)))
check("Materials sibling module", unbound_batch.materials_module().__file__.startswith(str(scratch)))
result = bpy.ops.import_scene.unbound_batch(filepath=str(root / "work/full-batch-0.4/manifest.json"))
check("Packaged import operator completed", result == {"FINISHED"})
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
check("593 source and assembly mesh objects", len(meshes) == 593)
check("All mesh objects have original slots", all("unbound_material_slot" in o and o.data.materials for o in meshes))
check("All polygons use original section index", all(
    all(p.material_index == o["unbound_material_slot"] for p in o.data.polygons) for o in meshes))
check("One vehicle assembly", sum(bool(c.get("unbound_assembly_path")) for c in bpy.context.scene.collection.children) == 1)
check("Four tire material assignments", len([
    o for o in meshes if o.get("unbound_assembled") and
    o.material_slots[o["unbound_material_slot"]].material.get("unbound_family") == "Rubber"
]) == 4)
reports = [json.loads(t.as_string()) for t in bpy.data.texts if t.get("unbound_report")]
check("Material report has no assignment failures", bool(reports) and all(
    not any(i.get("Severity") == "assignment_failed" for i in r["Issues"]) for r in reports))
check("Unsupported surfaces are disconnected", all(
    not n.inputs["Surface"].is_linked for mat in bpy.data.materials if mat.get("unbound_state_key")
    for n in mat.node_tree.nodes if n.type == "OUTPUT_MATERIAL"))
unbound_batch.unregister()
check("Import operator unregistered", not hasattr(bpy.types, "IMPORT_SCENE_OT_unbound_batch"))
summary = {"ArchiveSHA256": hashlib.sha256(archive.read_bytes()).hexdigest(),
           "Passed": sum(c["Passed"] for c in checks),
           "Failed": [c for c in checks if not c["Passed"]], "Checks": checks,
           "Mode": "Blender background registration/operator execution; Preferences installation UI not tested"}
(root / "outputs/Murcielago-Assembly/packaged-addon-validation.json").write_text(json.dumps(summary, indent=2))
print("PACKAGED ADDON", summary["Passed"], "FAILED", summary["Failed"])
if summary["Failed"]:
    raise AssertionError("Packaged add-on verification failed")
