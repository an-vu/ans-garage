import bpy, json, hashlib, re
from pathlib import Path
original=Path(r"C:\Users\anvu1\Desktop\Murcielago-Recovered")
fresh=Path(r"<work-root>\work\geometry-regression-final")
def signature(path):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=str(path),global_scale=1.0,use_manual_orientation=False,bake_space_transform=False,
        use_anim=False,automatic_bone_orientation=False,ignore_leaf_bones=False,use_prepost_rot=True)
    data=[]
    for o in sorted(bpy.data.objects,key=lambda o:o.name):
        row={"name":re.sub(r"\.\d{3}$","",o.name) if o.type=="MESH" else o.name,"type":o.type,"matrix":[list(r) for r in o.matrix_world],
             "parent":o.parent.name if o.parent else None}
        if o.type=="MESH":
            row.update(vertices=[list(v.co) for v in o.data.vertices],polygons=[list(p.vertices) for p in o.data.polygons],
                uvs={u.name:[list(v.uv) for v in u.data] for u in o.data.uv_layers},
                slots=[s.name for s in o.material_slots],
                weights=[sorted((o.vertex_groups[g.group].name,g.weight) for g in v.groups) for v in o.data.vertices])
        if o.type=="ARMATURE":
            row["bones"]=[{"name":b.name,"parent":b.parent.name if b.parent else None,"matrix":[list(r) for r in b.matrix_local]} for b in o.data.bones]
            row["pose"]=[{"name":p.name,"matrix":[list(r) for r in p.matrix]} for p in o.pose.bones]
        data.append(row)
    digest=hashlib.sha256(json.dumps(sorted(data,key=lambda r:json.dumps(r,sort_keys=True)),sort_keys=True).encode()).hexdigest()
    return {"sha256":digest,"objects":len(data),"meshes":[{"name":o.name,"polygons":len(o.data.polygons)} for o in bpy.data.objects if o.type=="MESH"]}
results=[]
for record_file in fresh.glob("*.json"):
    mesh=json.loads(record_file.read_text())
    relative=Path(mesh["Fbx"])
    a=signature(original/relative);b=signature(fresh/relative)
    results.append({"asset":mesh["Asset"],"type":mesh["Type"],"identical_imported_geometry":a["sha256"]==b["sha256"],"original":a,"phase2":b})
fender=list(original.rglob("*035d025c01361064b9be37613c0b91d14402f87b9f263106049fbbdb6dd9febf/LOD0.fbx"))[0]
report={"blender_version":bpy.app.version_string,"comparisons":results,"original_fender_fresh_import":signature(fender),
        "comparison_fields":"vertices, polygons, UV values, world matrices, parenting, skin weights by bone name, bone rest matrices, pose matrices, material slot names",
        "normalization":"Blender-generated .001 mesh name suffixes removed, objects sorted by complete content. Duplicate source section names receive different suffixes across imports."}
Path(r"<work-root>\outputs\Murcielago-Materials\geometry-validation.json").write_text(json.dumps(report,indent=2))
print("COMPARISONS",[(r["type"],r["identical_imported_geometry"]) for r in results])
assert len(results)==2 and all(r["identical_imported_geometry"] for r in results)

