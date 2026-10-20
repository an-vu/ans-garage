import bpy,json
from collections import Counter
report={"blender_version":bpy.app.version_string,"meshes":[],"images":[]}
for o in bpy.data.objects:
    if o.type=="MESH":
        report["meshes"].append({"object":o.name,"vertices":len(o.data.vertices),"polygons":len(o.data.polygons),
          "uvs":[u.name for u in o.data.uv_layers],"slots":[s.name for s in o.material_slots],
          "unbound_mesh_id":o.get("unbound_mesh_id"),"polygon_material_indices":dict(Counter(p.material_index for p in o.data.polygons))})
report["images"]=[{"name":i.name,"path":i.filepath} for i in bpy.data.images]
with open(r"<work-root>\work\blend-audit.json","w") as f: json.dump(report,f,indent=2)
print("AUDIT meshes",len(report["meshes"]),"slots",sum(len(m["slots"]) for m in report["meshes"]))
